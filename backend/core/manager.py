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

from .downloader import DownloadEngine, DownloadTask, DownloadStatus


STATE_FILE = Path.home() / ".midm" / "state.json"

log = logging.getLogger("MiDM.manager")


class DownloadManager:
    """
    High-level orchestrator.
    - Maintains the task queue
    - Controls concurrency (max N simultaneous downloads)
    - Persists state across restarts
    - Emits events to the UI layer
    """

    MAX_CONCURRENT = 3

    def __init__(self, on_event: Optional[Callable] = None, ssl_context=None):
        self.tasks: dict[str, DownloadTask] = {}
        self.on_event = on_event        # async callback(event_type, data)
        self._engine = DownloadEngine(on_progress=self._on_progress, ssl_context=ssl_context)
        self._queue: asyncio.Queue = asyncio.Queue()
        self._semaphore: Optional[asyncio.Semaphore] = None
        self._running = False

    # ─────────────────────────────────────────────
    # Lifecycle
    # ─────────────────────────────────────────────

    async def start(self):
        self._running = True
        self._semaphore = asyncio.Semaphore(self.MAX_CONCURRENT)
        self._load_state()
        asyncio.create_task(self._queue_worker())

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
        num_connections: int = 8,
    ) -> DownloadTask:
        """Create and enqueue a new download task."""

        if not save_dir:
            save_dir = str(Path.home() / "Downloads")

        if not filename:
            filename = self._filename_from_url(url)

        task = DownloadTask(
            id=str(uuid.uuid4())[:8],
            url=url,
            filename=filename,
            save_dir=save_dir,
            num_connections=min(num_connections, DownloadEngine.MAX_CONNECTIONS),
        )

        self.tasks[task.id] = task
        await self._queue.put(task)
        await self._emit("task_added", task.to_dict())
        self._save_state()
        log.info(f"[{task.id}] Queued: {url}")
        return task

    async def pause_download(self, task_id: str):
        task = self.tasks.get(task_id)
        if task and task.status == DownloadStatus.DOWNLOADING:
            self._engine.pause(task_id)
            task.status = DownloadStatus.PAUSED
            await self._emit("task_updated", task.to_dict())
            log.info(f"[{task_id}] Paused")

    async def resume_download(self, task_id: str):
        """
        FIX: Previously only flipped the status flag without re-queuing,
        so the download never actually restarted.
        Now we re-enqueue the task so _queue_worker picks it up again.
        """
        task = self.tasks.get(task_id)
        if not task:
            log.warning(f"[{task_id}] resume_download: task not found")
            return
        if task.status != DownloadStatus.PAUSED:
            log.warning(f"[{task_id}] resume_download: task is not paused (status={task.status})")
            return

        # Tell the engine to resume (clears its internal pause flag)
        self._engine.resume(task_id)
        # Re-queue so the worker actually drives the download again
        task.status = DownloadStatus.QUEUED
        await self._queue.put(task)
        await self._emit("task_updated", task.to_dict())
        log.info(f"[{task_id}] Resumed and re-queued")

    async def cancel_download(self, task_id: str):
        task = self.tasks.get(task_id)
        if task:
            self._engine.cancel(task_id)
            task.status = DownloadStatus.CANCELLED
            await self._emit("task_updated", task.to_dict())
            self._cleanup_temp(task)
            log.info(f"[{task_id}] Cancelled")

    async def remove_download(self, task_id: str, delete_file: bool = False):
        task = self.tasks.get(task_id)
        if not task:
            return
        await self.cancel_download(task_id)
        if delete_file:
            save_path = getattr(task, "save_path", None)
            if save_path and os.path.exists(save_path):
                os.remove(save_path)
                log.info(f"[{task_id}] Deleted file: {save_path}")
        del self.tasks[task_id]
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

    # ─────────────────────────────────────────────
    # Internal
    # ─────────────────────────────────────────────

    async def _queue_worker(self):
        """Pull tasks from queue and run them, respecting MAX_CONCURRENT."""
        while self._running:
            try:
                task = await asyncio.wait_for(self._queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue

            if task.status in (DownloadStatus.CANCELLED, DownloadStatus.COMPLETED):
                log.debug(f"[{task.id}] Skipping task with status={task.status}")
                continue

            log.info(f"[{task.id}] Dispatching to engine (status={task.status})")
            # Launch in a separate task so the queue worker is unblocked
            # and can pick up the next item immediately (up to MAX_CONCURRENT).
            asyncio.create_task(self._run_with_semaphore(task))

    async def _run_with_semaphore(self, task: DownloadTask):
        """
        Acquire semaphore slot then drive the full download.

        FIX: The original code did:
            download_task = await self._engine.start(task)   # got the asyncio.Task
            await download_task                              # awaited it
        This is correct IF engine.start() is a coroutine that internally
        creates-and-returns an asyncio.Task.  BUT if engine.start() is itself
        a coroutine that does the work directly (not returning a Task), the
        second await would raise TypeError or silently no-op depending on the
        return value.  We now handle both patterns safely.
        """
        async with self._semaphore:
            log.info(f"[{task.id}] Download starting (semaphore acquired)")
            try:
                result = await self._engine.start(task)

                # engine.start() may return:
                #   a) an asyncio.Task  -> we must await it
                #   b) None / other    -> download already ran inline; nothing to await
                if asyncio.isfuture(result) or asyncio.iscoroutine(result):
                    await result

                log.info(f"[{task.id}] Download finished with status={task.status}")

            except asyncio.CancelledError:
                # Task was cancelled cleanly — don't mark as FAILED
                log.info(f"[{task.id}] Download cancelled (CancelledError)")
                if task.status not in (DownloadStatus.CANCELLED, DownloadStatus.COMPLETED):
                    task.status = DownloadStatus.CANCELLED
                    await self._emit("task_updated", task.to_dict())

            except Exception as e:
                # Catch-all: log the full traceback so it is NEVER silently swallowed
                log.exception(f"[{task.id}] Download failed: {e}")
                if task.status not in (
                    DownloadStatus.CANCELLED,
                    DownloadStatus.COMPLETED,
                    DownloadStatus.FAILED,
                ):
                    task.status = DownloadStatus.FAILED
                    task.error = str(e)
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
                # FIX: log instead of silently swallowing — previously you could
                # never tell if the UI callback itself was crashing.
                log.error(f"_emit({event}) callback raised: {e}", exc_info=True)

    # ─────────────────────────────────────────────
    # Persistence
    # ─────────────────────────────────────────────

    def _save_state(self):
        try:
            STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            data = {tid: t.to_dict() for tid, t in self.tasks.items()}
            STATE_FILE.write_text(json.dumps(data, indent=2))
        except Exception as e:
            # FIX: was silently ignored
            log.error(f"_save_state failed: {e}", exc_info=True)

    def _load_state(self):
        if not STATE_FILE.exists():
            return
        try:
            data = json.loads(STATE_FILE.read_text())
            for tid, td in data.items():
                # Restore only non-active tasks; treat in-flight as paused
                status = DownloadStatus(td.get("status", "queued"))
                if status in (DownloadStatus.DOWNLOADING, DownloadStatus.CONNECTING):
                    td["status"] = DownloadStatus.PAUSED.value
                    log.info(f"[{tid}] Restored as PAUSED (was {status.value})")
                task = DownloadTask(**{
                    k: v for k, v in td.items()
                    if k in DownloadTask.__dataclass_fields__
                })
                self.tasks[tid] = task
            log.info(f"Loaded {len(self.tasks)} task(s) from state file")
        except Exception as e:
            # FIX: was silently ignored — a corrupt state file would cause
            # a blank task list with zero indication of why.
            log.error(f"_load_state failed: {e}", exc_info=True)

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
        FIX: original code mixed attribute access and dict access without
        a consistent check, causing AttributeError on dict segments or
        KeyError on object segments — both silently swallowed.
        """
        for seg in getattr(task, "segments", []):
            try:
                # Support both dataclass/object segments and plain dicts
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