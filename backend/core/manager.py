"""
MiDM - Download Manager
Manages the download queue, persists state, and coordinates the engine.
"""

import asyncio
import json
import uuid
import time
import os
import logging
from pathlib import Path
from typing import Optional, Callable
from urllib.parse import urlparse, unquote

from .downloader import DownloadEngine, DownloadTask, DownloadStatus, Segment
from .settings import SettingsManager


STATE_FILE = Path.home() / ".midm" / "state.json"

log = logging.getLogger("MiDM.manager")


class DownloadManager:
    """
    High-level orchestrator.
    - Maintains the task registry
    - Supports unlimited simultaneous downloads (no semaphore cap)
    - Persists state across restarts
    - Emits events to the UI layer
    """

    def __init__(self, on_event: Optional[Callable] = None, ssl_context=None):
        self.tasks: dict[str, DownloadTask] = {}
        self.on_event = on_event
        self._engine = DownloadEngine(on_progress=self._on_progress, ssl_context=ssl_context)
        self._running = False

        # Track the asyncio.Task for each active download so we can
        # detect whether a download is truly still running before resuming.
        # key = task.id, value = asyncio.Task
        self._active_tasks: dict[str, asyncio.Task] = {}
        self.settings = SettingsManager()

    # ─────────────────────────────────────────────
    # Lifecycle
    # ─────────────────────────────────────────────

    async def start(self):
        self._running = True
        self._load_state()
        asyncio.create_task(self._auto_remove_loop())
        await asyncio.sleep(0.5)
        await self._start_next_queued()

    async def stop(self):
        self._running = False
        self._save_state()

    # ─────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────

    async def add_download(
        self,
        url: str,
        save_dir: str = "",
        filename: str = "",
        num_connections: int = 0,
    ) -> DownloadTask:
        if not save_dir:
            save_dir = self.settings.get("save_dir", str(Path.home() / "Downloads"))
        if not filename:
            filename = self._filename_from_url(url)
        if num_connections <= 0:
            num_connections = self.settings.get("connections", 8)

        task = DownloadTask(
            id=str(uuid.uuid4())[:8],
            url=url,
            filename=filename,
            save_dir=save_dir,
            num_connections=min(num_connections, DownloadEngine.MAX_CONNECTIONS),
        )
        # Inject retry settings from config
        auto_retry = self.settings.get("auto_retry", True)
        max_retries = self.settings.get("max_retries", 3)
        task._segment_retries = max_retries if auto_retry else 0
        task._speed_limit_kbps = self.settings.get("speed_limit_kbps", 0)

        self.tasks[task.id] = task
        await self._emit("task_added", task.to_dict())
        self._save_state()
        log.info(f"[{task.id}] Queued: {url}")
        auto_start = self.settings.get("auto_start", True)
        if auto_start:
            self._launch(task)
        else:
            task.status = DownloadStatus.QUEUED
            log.info(f"[{task.id}] Auto-start disabled — task queued")
            await self._emit("task_updated", task.to_dict())

        return task

    async def pause_download(self, task_id: str):
        task = self.tasks.get(task_id)
        if task and task.status == DownloadStatus.DOWNLOADING:
            self._engine.pause(task_id)
            task.status = DownloadStatus.PAUSED
            await self._emit("task_updated", task.to_dict())
            log.info(f"[{task_id}] Paused")

    async def resume_download(self, task_id: str):
        task = self.tasks.get(task_id)
        if not task:
            log.warning(f"[{task_id}] resume_download: task not found")
            return
        if task.status != DownloadStatus.PAUSED:
            log.warning(f"[{task_id}] resume_download: not paused (status={task.status})")
            return

        active = self._active_tasks.get(task_id)

        if active and not active.done():
            # Original coroutine is still alive — just unpause it.
            # Do NOT launch a second _run(); that would cause two coroutines
            # writing to the same .part files simultaneously.
            log.info(f"[{task_id}] Resuming existing coroutine (still alive)")
            self._engine.resume(task_id)
            task.status = DownloadStatus.DOWNLOADING
            await self._emit("task_updated", task.to_dict())
        else:
            # Original coroutine is gone — safe to launch a fresh one.
            log.info(f"[{task_id}] Original coroutine gone, launching fresh _run")
            self._engine.resume(task_id)   # clear any stale pause flag
            task.status = DownloadStatus.QUEUED
            await self._emit("task_updated", task.to_dict())
            self._launch(task)

        log.info(f"[{task_id}] Resumed")
    
    async def retry_download(self, task_id: str):
        task = self.tasks.get(task_id)
        if not task:
            log.warning(f"[{task_id}] retry_download: task not found")
            return
        if task.status != DownloadStatus.FAILED:
            log.warning(f"[{task_id}] retry_download: not failed (status={task.status})")
            return
        log.info(f"[{task_id}] Retrying failed download: {task.url}")

        # Re-inject all runtime settings fresh from current config
        auto_retry  = self.settings.get("auto_retry", True)
        max_retries = self.settings.get("max_retries", 3)
        task._segment_retries  = max_retries if auto_retry else 0
        task._speed_limit_kbps = self.settings.get("speed_limit_kbps", 0)
        task._auto_retry_count = 0  # reset so auto-retry works fresh

        task.status = DownloadStatus.QUEUED
        task.error = None
        task.speed = 0.0
        task.eta = 0.0
        # Re-apply retry settings in case user changed them in settings
        auto_retry  = self.settings.get("auto_retry", True)
        max_retries = self.settings.get("max_retries", 3)
        task._segment_retries = max_retries if auto_retry else 0
        task._speed_limit_kbps = self.settings.get("speed_limit_kbps", 0)
        for seg in task.segments:
            if not seg.done:
                tmp_path = os.path.join(
                    os.path.expanduser("~"), ".midm", "tmp",
                    f"{task.id}_seg{seg.index}.part"
                )
                if os.path.exists(tmp_path):
                    actual_size = os.path.getsize(tmp_path)
                    if actual_size != seg.file_bytes or actual_size == 0:
                        # File is corrupt or mismatched — delete and restart this segment
                        os.remove(tmp_path)
                        seg.downloaded = 0
                        seg.file_bytes = 0
                        log.debug(
                            f"[{task.id}] seg{seg.index} corrupt temp file "
                            f"(expected {seg.file_bytes}, got {actual_size}) — deleted"
                        )
                    else:
                        log.debug(
                            f"[{task.id}] seg{seg.index} temp file OK "
                            f"({actual_size} bytes) — resuming"
                        )
                else:
                    seg.downloaded = 0
                    seg.file_bytes = 0
                    log.debug(
                        f"[{task.id}] seg{seg.index} temp file missing "
                        f"— reset downloaded to 0"
                    )

                await self._emit("task_updated", task.to_dict())
                self._save_state()
                self._launch(task)
    
    async def start_download(self, task_id: str):
        """Manually start a queued task, bypassing the simultaneous limit check."""
        task = self.tasks.get(task_id)
        if not task:
            log.warning(f"[{task_id}] start_download: task not found")
            return
        if task.status != DownloadStatus.QUEUED:
            log.warning(f"[{task_id}] start_download: not queued (status={task.status})")
            return

        log.info(f"[{task_id}] Manually starting queued task")
        # Launch directly, bypassing the simultaneous cap
        # so the user's explicit intent is always respected
        log.info(f"[{task_id}] Launching download coroutine (manual start)")
        t = asyncio.create_task(self._run_download(task))
        self._active_tasks[task_id] = t

        def _on_done(fut):
            self._active_tasks.pop(task_id, None)
            asyncio.create_task(self._start_next_queued())

        t.add_done_callback(_on_done)
        await self._emit("task_updated", task.to_dict())

    async def cancel_download(self, task_id: str):
        task = self.tasks.get(task_id)
        if not task:
            return

        self._engine.cancel(task_id)
        task.status = DownloadStatus.CANCELLED
        await self._emit("task_updated", task.to_dict())
        log.info(f"[{task_id}] Cancelled — waiting for coroutine to exit before cleanup")

        # Wait for the active asyncio.Task to finish so the .part files are
        # no longer open before we try to delete them (fixes WinError 32).
        active = self._active_tasks.get(task_id)
        if active and not active.done():
            try:
                await asyncio.wait_for(asyncio.shield(active), timeout=5.0)
            except (asyncio.TimeoutError, asyncio.CancelledError, Exception):
                pass   # best-effort; we'll still attempt cleanup below

        self._cleanup_temp(task)

    async def remove_download(self, task_id: str, delete_file: bool = False):
        task = self.tasks.get(task_id)
        if not task:
            return

        # cancel handles waiting + temp cleanup
        await self.cancel_download(task_id)

        if delete_file:
            save_path = getattr(task, "save_path", None)
            if save_path and os.path.exists(save_path):
                os.remove(save_path)
                log.info(f"[{task_id}] Deleted file: {save_path}")

        del self.tasks[task_id]
        self._active_tasks.pop(task_id, None)
        await self._emit("task_removed", {"id": task_id})
        self._save_state()
        log.info(f"[{task_id}] Removed")

    def get_all_tasks(self) -> list[dict]:
        return [t.to_dict() for t in self.tasks.values()]

    def get_stats(self) -> dict:
        tasks = list(self.tasks.values())
        total_speed = sum(t.speed for t in tasks if t.status == DownloadStatus.DOWNLOADING)
        return {
            "total_downloads": len(tasks),
            "active": sum(1 for t in tasks if t.status == DownloadStatus.DOWNLOADING),
            "completed": sum(1 for t in tasks if t.status == DownloadStatus.COMPLETED),
            "total_speed": total_speed,
            "speed_human": self._human_speed(total_speed),
        }
    def update_settings(self, data: dict) -> dict:
        return self.settings.update(data)

    def get_settings(self) -> dict:
        return self.settings.get_all()

    async def _auto_remove_loop(self):
        """Background loop that removes completed tasks older than auto_remove_hours."""
        while self._running:
            try:
                hours = self.settings.get("auto_remove_hours", 0)
                if hours and hours > 0:
                    now = time.time()
                    threshold = hours * 3600
                    to_remove = [
                        tid for tid, t in list(self.tasks.items())
                        if t.status == DownloadStatus.COMPLETED
                        and t.completed_at
                        and (now - t.completed_at) >= threshold
                    ]
                    for tid in to_remove:
                        log.info(f"[{tid}] Auto-removing completed task (older than {hours}h)")
                        await self.remove_download(tid)
            except Exception as e:
                log.error(f"_auto_remove_loop error: {e}", exc_info=True)
            # Check every 60 seconds
            await asyncio.sleep(60)

    # ─────────────────────────────────────────────
    # Internal
    # ─────────────────────────────────────────────

    def _launch(self, task: DownloadTask):
        """
        Launch a download only if under the simultaneous limit.
        If over the limit, queue it — it will be picked up when
        an active download finishes.
        """
        max_sim = self.settings.get("max_simultaneous", 5)
        active_count = sum(
            1 for t in self.tasks.values()
            if t.status in (
                DownloadStatus.DOWNLOADING,
                DownloadStatus.CONNECTING,
                DownloadStatus.MERGING,
            )
        )

        if active_count >= max_sim:
            log.info(f"[{task.id}] Queued — max simultaneous ({max_sim}) reached")
            task.status = DownloadStatus.QUEUED
            return

        log.info(f"[{task.id}] Launching download coroutine")
        t = asyncio.create_task(self._run_download(task))
        self._active_tasks[task.id] = t

        def _on_done(fut):
            self._active_tasks.pop(task.id, None)
            # When a download finishes, try to start the next queued one
            asyncio.create_task(self._start_next_queued())

        t.add_done_callback(_on_done)
    
    async def _start_next_queued(self):
        """Pick the oldest queued task and launch it if under the limit."""
        max_sim = self.settings.get("max_simultaneous", 5)
        active_count = sum(
            1 for t in self.tasks.values()
            if t.status in (
                DownloadStatus.DOWNLOADING,
                DownloadStatus.CONNECTING,
                DownloadStatus.MERGING,
            )
        )

        if active_count >= max_sim:
            return

        # Find oldest queued task (by created_at)
        queued = [
            t for t in self.tasks.values()
            if t.status == DownloadStatus.QUEUED
        ]
        if not queued:
            return

        next_task = min(queued, key=lambda t: t.created_at)
        log.info(f"[{next_task.id}] Starting from queue")
        self._launch(next_task)
        await self._emit("task_updated", next_task.to_dict())

    async def _run_download(self, task: DownloadTask):
        """Drive a single download from start to finish."""
        log.info(f"[{task.id}] Download starting")
        try:
            result = await self._engine.start(task)

            # engine.start() returns an asyncio.Task; await it.
            if asyncio.isfuture(result) or asyncio.iscoroutine(result):
                await result

            log.info(f"[{task.id}] Download finished with status={task.status}")

        except asyncio.CancelledError:
            log.info(f"[{task.id}] Download cancelled (CancelledError)")
            if task.status not in (DownloadStatus.CANCELLED, DownloadStatus.COMPLETED):
                task.status = DownloadStatus.CANCELLED
                await self._emit("task_updated", task.to_dict())

        except Exception as e:
            log.exception(f"[{task.id}] Download failed: {e}")
            if task.status not in (
                DownloadStatus.CANCELLED,
                DownloadStatus.COMPLETED,
                DownloadStatus.FAILED,
            ):
                auto_retry  = self.settings.get("auto_retry", True)
                max_retries = self.settings.get("max_retries", 3)
        
                # Check how many times this task has already been auto-retried
                retry_count = getattr(task, '_auto_retry_count', 0)
        
                if auto_retry and retry_count < max_retries:
                    task._auto_retry_count = retry_count + 1
                    log.info(
                        f"[{task.id}] Auto-retrying "
                        f"({task._auto_retry_count}/{max_retries})..."
                    )
                    task.status = DownloadStatus.QUEUED
                    task.error  = None
                    task.speed  = 0.0
                    task.eta    = 0.0
                    for seg in getattr(task, 'segments', []):
                        if not seg.done:
                            seg.speed = 0.0
                    await self._emit("task_updated", task.to_dict())
                    self._save_state()
                    # Wait briefly before relaunching
                    await asyncio.sleep(3)
                    for seg in getattr(task, 'segments', []):
                        if not seg.done:
                            tmp_path = os.path.join(
                                os.path.expanduser("~"), ".midm", "tmp",
                                f"{task.id}_seg{seg.index}.part"
                            )
                            if os.path.exists(tmp_path):
                                actual_size = os.path.getsize(tmp_path)
                                if actual_size != seg.file_bytes or actual_size == 0:
                                    os.remove(tmp_path)
                                    seg.downloaded = 0
                                    seg.file_bytes = 0
                            else:
                                seg.downloaded = 0
                                seg.file_bytes = 0
                    self._launch(task)
                else:
                    task.status = DownloadStatus.FAILED
                    task.error  = str(e)
                    task._auto_retry_count = 0  # reset for next manual retry
                    await self._emit("task_updated", task.to_dict())
                    self._save_state()

    async def _on_progress(self, task: DownloadTask):
        await self._emit("task_progress", task.to_dict())
        self._save_state()

    async def _emit(self, event: str, data: dict):
        if self.on_event:
            try:
                await self.on_event(event, data)
            except Exception as e:
                log.error(f"_emit({event}) callback raised: {e}", exc_info=True)

    # ─────────────────────────────────────────────
    # Persistence
    # ─────────────────────────────────────────────

    def _save_state(self):
        try:
            STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            data = {tid: t.to_dict() for tid, t in self.tasks.items()}
            tmp_file = STATE_FILE.with_suffix('.tmp')
            tmp_file.write_text(json.dumps(data, indent=2), encoding='utf-8')
            # Keep previous state as backup before replacing
            if STATE_FILE.exists():
                import shutil
                shutil.copy(STATE_FILE, STATE_FILE.with_suffix('.bak'))
            tmp_file.replace(STATE_FILE)
        except Exception as e:
            log.error(f"_save_state failed: {e}", exc_info=True)

    def _load_state(self):
        # Try main state file first, then backup
        for path in [STATE_FILE, STATE_FILE.with_suffix('.bak')]:
            if not path.exists():
                continue
            try:
                text = path.read_text(encoding='utf-8').strip()
                if not text:
                    log.warning(f"State file empty: {path} — skipping")
                    continue
                data = json.loads(text)
                for tid, td in data.items():
                    status = DownloadStatus(td.get("status", "queued"))
                    if status in (DownloadStatus.DOWNLOADING,
                                  DownloadStatus.CONNECTING,
                                  DownloadStatus.MERGING):
                        td["status"] = DownloadStatus.PAUSED.value
                        log.info(f"[{tid}] Restored as PAUSED (was {status.value})")
                    elif status == DownloadStatus.QUEUED:
                        log.info(f"[{tid}] Restored as QUEUED")
                    elif status == DownloadStatus.FAILED:
                        log.info(f"[{tid}] Restored as FAILED — awaiting manual retry")

                    raw_segments = td.get("segments", [])
                    converted_segments = []
                    for s in raw_segments:
                        if isinstance(s, dict):
                            converted_segments.append(Segment(
                                index       = s.get("index", 0),
                                start       = s.get("start", 0),
                                end         = s.get("end", 0),
                                downloaded  = s.get("downloaded", 0),
                                speed       = s.get("speed", 0.0),
                                done        = s.get("done", False),
                                temp_path   = s.get("temp_path", ""),
                                file_offset = s.get("file_offset", 0),
                                file_bytes  = s.get("file_bytes", 0),
                            ))
                        else:
                            converted_segments.append(s)

                    task_fields = {
                        k: v for k, v in td.items()
                        if k in DownloadTask.__dataclass_fields__
                    }
                    task_fields["segments"] = converted_segments
                    task = DownloadTask(**task_fields)

                    # Re-inject runtime settings lost on restart
                    auto_retry  = self.settings.get("auto_retry", True)
                    max_retries = self.settings.get("max_retries", 3)
                    task._segment_retries  = max_retries if auto_retry else 0
                    task._speed_limit_kbps = self.settings.get("speed_limit_kbps", 0)
                    task._auto_retry_count = 0

                    if task.status in (DownloadStatus.FAILED, DownloadStatus.PAUSED):
                        for seg in task.segments:
                            if hasattr(seg, 'speed'):
                                seg.speed = 0.0
                        task.speed = 0.0
                        task.eta   = 0.0

                    self.tasks[tid] = task

                log.info(f"Loaded {len(self.tasks)} task(s) from {path.name}")
                # If we loaded from backup, restore it as main
                if path != STATE_FILE:
                    import shutil
                    shutil.copy(path, STATE_FILE)
                    log.info("Restored state from backup file")
                return  # success — stop trying
            except Exception as e:
                log.error(f"_load_state failed for {path}: {e}", exc_info=True)
                continue

        log.warning("No valid state file found — starting fresh")
    # ─────────────────────────────────────────────
    # Utilities
    # ─────────────────────────────────────────────

    def _filename_from_url(self, url: str) -> str:
        path = unquote(urlparse(url).path)
        name = os.path.basename(path)
        if not name or "." not in name:
            name = f"download_{int(time.time())}"
        return name

    def _cleanup_temp(self, task: DownloadTask):
        """
        Delete all .part files for a task.
        Called only after the download coroutine has exited so files are
        guaranteed to be closed (no WinError 32).
        """
        for seg in getattr(task, "segments", []):
            try:
                if hasattr(seg, "temp_path"):
                    temp_path = seg.temp_path
                elif isinstance(seg, dict):
                    temp_path = seg.get("temp_path", "")
                else:
                    continue

                if temp_path and os.path.exists(temp_path):
                    os.remove(temp_path)
                    log.debug(f"Removed temp file: {temp_path}")
            except Exception as e:
                log.warning(f"_cleanup_temp: could not remove segment file: {e}")

    def _human_speed(self, bps: float) -> str:
        if bps >= 1_000_000:
            return f"{bps/1_000_000:.1f} MB/s"
        if bps >= 1_000:
            return f"{bps/1_000:.1f} KB/s"
        return f"{bps:.0f} B/s"