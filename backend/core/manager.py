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

    # ─────────────────────────────────────────────
    # Lifecycle
    # ─────────────────────────────────────────────

    async def start(self):
        self._running = True
        self._load_state()

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
        """Create and immediately start a new download task."""

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
        await self._emit("task_added", task.to_dict())
        self._save_state()
        log.info(f"[{task.id}] Queued: {url}")

        # Start immediately — no queue, no semaphore cap
        self._launch(task)
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
        task.status = DownloadStatus.QUEUED
        task.error = None
        task.speed = 0.0
        task.eta = 0.0
        for seg in task.segments:
            if not seg.done:
                seg.speed = 0.0

        await self._emit("task_updated", task.to_dict())
        self._save_state()
        self._launch(task)

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

    # ─────────────────────────────────────────────
    # Internal
    # ─────────────────────────────────────────────

    def _launch(self, task: DownloadTask):
        """
        Create an asyncio.Task for one download and register it in
        _active_tasks so resume_download can check whether it's still alive.
        """
        log.info(f"[{task.id}] Launching download coroutine")
        t = asyncio.create_task(self._run_download(task))
        self._active_tasks[task.id] = t

        # Auto-remove from _active_tasks when done (keeps the dict lean)
        def _on_done(fut):
            self._active_tasks.pop(task.id, None)

        t.add_done_callback(_on_done)

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
            log.error(f"_save_state failed: {e}", exc_info=True)

    def _load_state(self):
        if not STATE_FILE.exists():
            return
        try:
            data = json.loads(STATE_FILE.read_text())
            for tid, td in data.items():
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