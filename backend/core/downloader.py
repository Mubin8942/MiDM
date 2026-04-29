"""
MiDM - Download Engine
Dynamic multi-segment downloader with async I/O
"""

import asyncio
import aiohttp
import aiofiles
import logging
import os
import gc
import time
from dataclasses import dataclass, field, asdict
from typing import Optional, Callable
from enum import Enum


log = logging.getLogger("MiDM.engine")


class DownloadStatus(str, Enum):
    QUEUED      = "queued"
    CONNECTING  = "connecting"
    DOWNLOADING = "downloading"
    PAUSED      = "paused"
    MERGING     = "merging"
    COMPLETED   = "completed"
    FAILED      = "failed"
    CANCELLED   = "cancelled"


@dataclass
class Segment:
    index: int
    start: int
    end: int
    downloaded: int = 0
    speed: float = 0.0
    done: bool = False
    temp_path: str = ""

    @property
    def remaining(self) -> int:
        return (self.end - self.start + 1) - self.downloaded

    @property
    def current_pos(self) -> int:
        return self.start + self.downloaded


@dataclass
class DownloadTask:
    id: str
    url: str
    filename: str
    save_dir: str
    total_size: int = 0
    downloaded: int = 0
    status: DownloadStatus = DownloadStatus.QUEUED
    segments: list = field(default_factory=list)
    speed: float = 0.0
    eta: float = 0.0
    created_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None
    error: Optional[str] = None
    supports_resume: bool = False
    num_connections: int = 8
    file_type: str = "unknown"

    @property
    def progress(self) -> float:
        if self.total_size == 0:
            return 0.0
        return min((self.downloaded / self.total_size) * 100, 100.0)

    @property
    def save_path(self) -> str:
        return os.path.join(self.save_dir, self.filename)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["status"] = self.status.value if hasattr(self.status, "value") else self.status
        d["progress"] = self.progress
        d["save_path"] = self.save_path
        return d


# Browser-like headers that satisfy most servers rejecting bot-like requests
_DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "identity",   # prevent gzip so Content-Length stays accurate
    "Connection": "keep-alive",
}


class DownloadEngine:
    """
    Core async download engine.
    Implements IDM-style dynamic segmentation:
      - Splits file into N segments
      - Each segment downloads in parallel
      - Finished threads steal half of the slowest remaining segment
      - All threads stay busy until the last byte
    """

    MIN_SEGMENT_SIZE = 512 * 1024   # 512 KB minimum chunk to split
    CHUNK_SIZE       = 64 * 1024    # 64 KB read buffer
    MAX_CONNECTIONS  = 16
    DEFAULT_CONNECTIONS = 8

    # How many times to retry a segment on transient errors before giving up
    SEGMENT_RETRIES = 3
    RETRY_BACKOFF   = [1, 3, 7]     # seconds between retries

    def __init__(self, on_progress: Optional[Callable] = None, ssl_context=None):
        self.on_progress = on_progress
        self._ssl_context = ssl_context
        self._active: dict[str, asyncio.Task] = {}
        self._cancel_flags: dict[str, bool] = {}
        self._pause_events: dict[str, asyncio.Event] = {}

    # ─────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────

    async def start(self, task: DownloadTask) -> asyncio.Task:
        """Begin or resume a download task. Returns the asyncio.Task."""
        self._cancel_flags[task.id] = False
        ev = asyncio.Event()
        ev.set()    # not paused initially
        self._pause_events[task.id] = ev

        t = asyncio.create_task(self._run(task))
        self._active[task.id] = t
        return t

    def pause(self, task_id: str):
        ev = self._pause_events.get(task_id)
        if ev:
            ev.clear()
            log.info(f"[{task_id}] Engine: paused")

    def resume(self, task_id: str):
        ev = self._pause_events.get(task_id)
        if ev:
            ev.set()
            log.info(f"[{task_id}] Engine: resumed")

    def cancel(self, task_id: str):
        self._cancel_flags[task_id] = True
        self.resume(task_id)    # unblock if paused so the task can exit cleanly
        t = self._active.get(task_id)
        if t:
            t.cancel()
            log.info(f"[{task_id}] Engine: cancelled")

    # ─────────────────────────────────────────────
    # Internal engine
    # ─────────────────────────────────────────────

    async def _run(self, task: DownloadTask):
        task.status = DownloadStatus.CONNECTING
        await self._notify(task)
        log.info(f"[{task.id}] Connecting to {task.url}")

        try:
            connector = aiohttp.TCPConnector(
                limit=self.MAX_CONNECTIONS,
                ssl=self._ssl_context,   # None → aiohttp default; SSLContext → certifi
            )
            async with aiohttp.ClientSession(
                headers=_DEFAULT_HEADERS,
                connector=connector,
            ) as session:

                # Step 1: Probe for file info
                await self._probe(session, task)
                log.info(
                    f"[{task.id}] Probed — size={task.total_size} "
                    f"resume={task.supports_resume} type={task.file_type}"
                )

                # Step 2: Build segments
                self._build_segments(task)
                log.info(f"[{task.id}] {len(task.segments)} segment(s) planned")

                task.status = DownloadStatus.DOWNLOADING
                await self._notify(task)

                # Step 3: Download all segments concurrently
                await self._download_all(session, task)

                if self._cancel_flags.get(task.id):
                    task.status = DownloadStatus.CANCELLED
                    await self._notify(task)
                    log.info(f"[{task.id}] Cancelled after download_all")
                    return

                # Step 4: Merge segments
                gc.collect()
                await asyncio.sleep(0.2)
                task.status = DownloadStatus.MERGING
                await self._notify(task)
                log.info(f"[{task.id}] Merging segments → {task.save_path}")
                await self._merge_segments(task)

                task.status = DownloadStatus.COMPLETED
                task.completed_at = time.time()
                task.downloaded = task.total_size if task.total_size > 0 else task.downloaded
                await self._notify(task)
                log.info(f"[{task.id}] ✓ Completed: {task.filename}")

        except asyncio.CancelledError:
            task.status = DownloadStatus.CANCELLED
            await self._notify(task)
            log.info(f"[{task.id}] CancelledError caught in _run")

        except Exception as e:
            task.status = DownloadStatus.FAILED
            task.error = str(e)
            await self._notify(task)
            log.exception(f"[{task.id}] Download failed: {e}")
            raise

        finally:
            self._active.pop(task.id, None)

    async def _probe(self, session: aiohttp.ClientSession, task: DownloadTask):
        """
        Discover file size and resume support.

        Strategy (in order):
          1. HEAD request  — cleanest, no body transfer
          2. GET Range:0-0 — servers that reject HEAD but honour Range
          3. Plain GET     — stream just enough to read headers, then abort
                             (catches servers that return 403 on Range requests
                              but allow a plain GET, e.g. some CDNs / redirect chains)

        A 403/401 on any method does NOT raise immediately — we try the next
        strategy so the actual download GET has a fair shot.
        """
        timeout = aiohttp.ClientTimeout(total=20)

        # ── Strategy 1: HEAD ──────────────────────────────────────────────
        try:
            async with session.head(task.url, allow_redirects=True, timeout=timeout) as r:
                if r.status == 200:
                    self._extract_probe_headers(r.headers, task)
                    log.debug(
                        f"[{task.id}] HEAD {r.status} — "
                        f"Content-Length={task.total_size} "
                        f"Accept-Ranges={r.headers.get('Accept-Ranges', '')!r}"
                    )
                    return
                else:
                    log.debug(f"[{task.id}] HEAD returned {r.status}, trying Range GET")
        except Exception as e:
            log.warning(f"[{task.id}] HEAD failed ({e}), trying Range GET")

        # ── Strategy 2: GET Range: bytes=0-0 ─────────────────────────────
        try:
            async with session.get(
                task.url,
                headers={"Range": "bytes=0-0"},
                timeout=timeout,
            ) as r:
                if r.status in (200, 206):
                    self._extract_probe_headers(r.headers, task)
                    # 206 with Content-Range tells us the real total
                    cr = r.headers.get("Content-Range", "")
                    if cr and "/" in cr:
                        total_str = cr.split("/")[-1]
                        if total_str.isdigit():
                            task.total_size = int(total_str)
                            task.supports_resume = True
                    log.debug(
                        f"[{task.id}] Range-GET {r.status} — "
                        f"total={task.total_size} resume={task.supports_resume}"
                    )
                    return
                else:
                    log.debug(f"[{task.id}] Range GET returned {r.status}, trying plain GET probe")
        except Exception as e:
            log.warning(f"[{task.id}] Range GET failed ({e}), trying plain GET probe")

        # ── Strategy 3: plain GET (read headers only, close immediately) ──
        # Some servers (e.g. link.testfile.org) return 403 on HEAD/Range but
        # serve fine on a plain GET.  We open the connection, grab the headers,
        # then immediately close without reading the body.
        try:
            async with session.get(task.url, timeout=timeout) as r:
                if r.status == 200:
                    self._extract_probe_headers(r.headers, task)
                    log.debug(
                        f"[{task.id}] Plain-GET probe {r.status} — "
                        f"total={task.total_size}"
                    )
                    # supports_resume stays False — we'll use a single segment
                    return
                else:
                    # Even plain GET is blocked — log and continue; the real
                    # download attempt below may still succeed (redirect, cookie, etc.)
                    log.warning(
                        f"[{task.id}] Plain-GET probe returned {r.status}. "
                        "Will attempt download anyway."
                    )
        except Exception as e:
            log.warning(f"[{task.id}] All probe strategies failed ({e}). "
                        "Attempting download without size info.")

    def _extract_probe_headers(self, headers, task: DownloadTask):
        """Pull file metadata out of response headers."""
        cl = headers.get("Content-Length", "0")
        if cl.isdigit():
            task.total_size = int(cl)

        accept = headers.get("Accept-Ranges", "").lower()
        task.supports_resume = (accept == "bytes" and task.total_size > 0)

        ct = headers.get("Content-Type", "")
        task.file_type = self._classify_mime(ct)

        cd = headers.get("Content-Disposition", "")
        if "filename=" in cd and not task.filename:
            task.filename = cd.split("filename=")[-1].strip().strip('"\'')

    def _build_segments(self, task: DownloadTask):
        """Divide file into equal initial segments."""
        if task.segments:
            log.debug(f"[{task.id}] Reusing {len(task.segments)} existing segments (resume)")
            return

        n = task.num_connections if (task.supports_resume and task.total_size > 0) else 1

        if task.total_size == 0 or n == 1:
            task.segments = [Segment(
                index=0, start=0,
                end=task.total_size - 1 if task.total_size > 0 else 0,
                temp_path=self._temp_path(task, 0),
            )]
            return

        seg_size = task.total_size // n
        task.segments = []
        for i in range(n):
            start = i * seg_size
            end = (start + seg_size - 1) if i < n - 1 else task.total_size - 1
            task.segments.append(Segment(
                index=i, start=start, end=end,
                temp_path=self._temp_path(task, i),
            ))

    async def _download_all(self, session: aiohttp.ClientSession, task: DownloadTask):
        """
        Download all segments in parallel.
        Each segment is retried up to SEGMENT_RETRIES times on transient errors.
        Implements IDM's dynamic segment stealing when a segment finishes early.
        """
        segment_retries = getattr(task, '_segment_retries', self.SEGMENT_RETRIES)
        lock = asyncio.Lock()

        async def download_segment(seg: Segment):
            if seg.done:
                return

            pause_ev = self._pause_events[task.id]

            for attempt in range(segment_retries + 1):
                if self._cancel_flags.get(task.id):
                    return

                # Build request headers for this segment
                req_headers: dict = {}
                if task.supports_resume:
                    req_headers["Range"] = f"bytes={seg.current_pos}-{seg.end}"

                range_label = req_headers.get("Range", "no-range")
                log.debug(
                    f"[{task.id}] seg{seg.index} attempt {attempt + 1} — {range_label}"
                )

                try:
                    async with session.get(
                        task.url,
                        headers=req_headers,
                        timeout=aiohttp.ClientTimeout(total=None, connect=20, sock_read=60),
                    ) as resp:

                        # ── Status validation ────────────────────────────
                        if resp.status not in (200, 206):
                            # 403/401 on a ranged request sometimes means the
                            # server doesn't support Range but accepts plain GET.
                            # Retry without the Range header using a single segment.
                            if resp.status in (403, 401) and task.supports_resume:
                                log.warning(
                                    f"[{task.id}] seg{seg.index} got {resp.status} "
                                    "with Range header — disabling multi-segment and retrying"
                                )
                                task.supports_resume = False
                                # Collapse to a single segment and restart
                                task.segments.clear()
                                task.downloaded = 0
                                seg.downloaded = 0
                                seg.start = 0
                                seg.end = 0
                                seg.temp_path = self._temp_path(task, 0)
                                req_headers.pop("Range", None)
                                # Re-enter with the corrected segment next attempt
                                continue

                            raise RuntimeError(
                                f"seg{seg.index}: unexpected HTTP {resp.status} for {task.url}"
                            )

                        # ── Stream to temp file ──────────────────────────
                        mode = "ab" if seg.downloaded > 0 else "wb"
                        async with aiofiles.open(seg.temp_path, mode) as f:
                            t_last = time.monotonic()
                            bytes_since = 0

                            async for chunk in resp.content.iter_chunked(self.CHUNK_SIZE):
                                if self._cancel_flags.get(task.id):
                                    return

                                await pause_ev.wait()   # block while paused

                                await f.write(chunk)
                                n = len(chunk)
                                seg.downloaded += n
                                bytes_since += n

                                now = time.monotonic()
                                elapsed = now - t_last
                                if elapsed >= 0.5:
                                    seg.speed = bytes_since / elapsed
                                    bytes_since = 0
                                    t_last = now
                                    async with lock:
                                        await self._update_stats(task)
                                        await self._notify(task)

                        seg.done = True
                        log.debug(f"[{task.id}] seg{seg.index} done ({seg.downloaded} bytes)")

                        # Try to steal half of largest remaining segment
                        async with lock:
                            stolen = self._try_steal(task, seg)

                        if stolen:
                            log.debug(
                                f"[{task.id}] seg{seg.index} stealing → new seg{stolen.index}"
                            )
                            await download_segment(stolen)

                        return  # success — exit retry loop

                except asyncio.CancelledError:
                    raise

                except Exception as e:
                    if self._cancel_flags.get(task.id):
                        return

                    if attempt < segment_retries:
                        wait = self.RETRY_BACKOFF[min(attempt, len(self.RETRY_BACKOFF) - 1)]
                        log.warning(
                            f"[{task.id}] seg{seg.index} error (attempt {attempt + 1}): {e}. "
                            f"Retrying in {wait}s…"
                        )
                        await asyncio.sleep(wait)
                    else:
                        log.exception(
                            f"[{task.id}] seg{seg.index} failed after "
                            f"{segment_retries + 1} attempts: {e}"
                        )
                        raise

        workers = [download_segment(s) for s in task.segments]
        await asyncio.gather(*workers, return_exceptions=False)

    def _try_steal(self, task: DownloadTask, finished_seg: Segment) -> Optional[Segment]:
        """
        IDM's core: find the segment with the most bytes remaining,
        split it in half, and return the new second-half segment.
        """
        candidates = [
            s for s in task.segments
            if not s.done and s.remaining > self.MIN_SEGMENT_SIZE * 2
        ]
        if not candidates:
            return None

        victim = max(candidates, key=lambda s: s.remaining)
        split_at = victim.current_pos + (victim.remaining // 2)

        new_index = max(s.index for s in task.segments) + 1
        new_seg = Segment(
            index=new_index,
            start=split_at,
            end=victim.end,
            temp_path=self._temp_path(task, new_index),
        )
        victim.end = split_at - 1
        task.segments.append(new_seg)
        return new_seg

    async def _update_stats(self, task: DownloadTask):
        task.downloaded = sum(s.downloaded for s in task.segments)
        task.speed = sum(s.speed for s in task.segments if not s.done)
        remaining = task.total_size - task.downloaded
        task.eta = (remaining / task.speed) if task.speed > 0 and remaining > 0 else 0.0

    async def _merge_segments(self, task: DownloadTask):
        """Concatenate all segment temp files into the final file."""
        os.makedirs(task.save_dir, exist_ok=True)
        ordered = sorted(task.segments, key=lambda s: s.start)

        async with aiofiles.open(task.save_path, "wb") as out:
            for seg in ordered:
                if os.path.exists(seg.temp_path):
                    async with aiofiles.open(seg.temp_path, "rb") as f:
                        while True:
                            chunk = await f.read(self.CHUNK_SIZE * 4)
                            if not chunk:
                                break
                            await out.write(chunk)
                    await asyncio.sleep(0.1)
                    try:
                        os.remove(seg.temp_path)
                    except PermissionError:
                        await asyncio.sleep(0.5)
                        os.remove(seg.temp_path)
                else:
                    log.warning(
                        f"[{task.id}] Missing temp file for seg{seg.index}: {seg.temp_path}"
                    )

        # Clean up ~/.midm/tmp if it is now empty
        try:
            tmp_dir = os.path.join(os.path.expanduser("~"), ".midm", "tmp")
            if os.path.isdir(tmp_dir) and not os.listdir(tmp_dir):
                os.rmdir(tmp_dir)
        except Exception:
            pass

    # ─────────────────────────────────────────────
    # Helpers
    # ─────────────────────────────────────────────

    def _temp_path(self, task: DownloadTask, seg_index: int) -> str:
        # Always store .part files in ~/.midm/tmp/ so they never appear
        # inside the user's chosen download folder.
        tmp_dir = os.path.join(os.path.expanduser("~"), ".midm", "tmp")
        os.makedirs(tmp_dir, exist_ok=True)
        return os.path.join(tmp_dir, f"{task.id}_seg{seg_index}.part")

    def _classify_mime(self, mime: str) -> str:
        mime = mime.lower()
        if any(x in mime for x in ["video", "mp4", "mkv", "avi"]):      return "video"
        if any(x in mime for x in ["audio", "mp3", "flac"]):            return "audio"
        if any(x in mime for x in ["zip", "rar", "7z", "tar", "gz"]):   return "archive"
        if any(x in mime for x in ["pdf", "doc", "spreadsheet"]):       return "document"
        if any(x in mime for x in ["image", "jpeg", "png", "gif"]):     return "image"
        if any(x in mime for x in ["exe", "msi", "octet-stream"]):      return "software"
        return "other"

    async def _notify(self, task: DownloadTask):
        if self.on_progress:
            try:
                await self.on_progress(task)
            except Exception as e:
                log.error(f"[{task.id}] _notify callback raised: {e}", exc_info=True)