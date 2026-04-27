"""
MiDM - WebSocket Server
Real-time bridge between the Python download engine and the React/Tauri UI.
All UI interactions go through this JSON-RPC-over-WebSocket protocol.
"""

import asyncio
import json
import logging
import ssl
import sys
from pathlib import Path

import aiohttp
from aiohttp import web, WSMsgType

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent))
from core.manager import DownloadManager

# Ensure the directory exists BEFORE FileHandler tries to open the log file
(Path.home() / ".midm").mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(Path.home() / ".midm" / "server.log", encoding="utf-8"),
    ],
)
log = logging.getLogger("MiDM.server")

WS_PORT = 7475


# ── CORS middleware ───────────────────────────────────────────────

@web.middleware
async def cors_middleware(request, handler):
    if request.method == "OPTIONS":
        return web.Response(headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type",
        })
    response = await handler(request)
    response.headers["Access-Control-Allow-Origin"] = "*"
    return response


def _make_ssl_context() -> ssl.SSLContext:
    """
    FIX: HTTPS downloads were silently failing because aiohttp uses the
    default SSL context which may lack system CA certificates in some
    environments (especially packaged apps / Windows).

    Build an explicit SSL context that:
      1. Uses the system trust store (certifi as fallback).
      2. Enforces certificate verification (never disable it in production).
    """
    try:
        import certifi
        ctx = ssl.create_default_context(cafile=certifi.where())
        log.debug(f"SSL context built using certifi: {certifi.where()}")
    except ImportError:
        ctx = ssl.create_default_context()
        log.debug("SSL context built using system CA store (certifi not installed)")
    return ctx


class MiDMServer:
    """
    Async WebSocket + HTTP server.

    WebSocket (ws://localhost:7475/ws):
      - Receives commands from UI (JSON-RPC style)
      - Pushes real-time progress events to all connected UIs

    HTTP (http://localhost:7475):
      - GET  /status    -> server health
      - GET  /downloads -> all tasks
      - POST /add       -> add download via HTTP (for browser extension)
      - GET  /stats     -> aggregated stats
    """

    def __init__(self):
        self._clients: set[web.WebSocketResponse] = set()
        self._ssl_context = _make_ssl_context()
        self._manager = DownloadManager(
            on_event=self._broadcast_event,
            ssl_context=self._ssl_context,   # pass SSL context down to engine
        )

    # ─────────────────────────────────────────────
    # WebSocket handler
    # ─────────────────────────────────────────────

    async def ws_handler(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse(heartbeat=30)
        await ws.prepare(request)
        self._clients.add(ws)
        log.info(f"UI connected ({len(self._clients)} client(s))")

        # Send current state on connect
        await self._send(ws, "init", {
            "tasks": self._manager.get_all_tasks(),
            "stats": self._manager.get_stats(),
        })

        try:
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    await self._handle_command(ws, msg.data)
                elif msg.type == WSMsgType.ERROR:
                    log.warning(f"WS error: {ws.exception()}")
                    break
                elif msg.type == WSMsgType.CLOSED:
                    break
        except Exception as e:
            log.exception(f"ws_handler unexpected error: {e}")
        finally:
            self._clients.discard(ws)
            log.info(f"UI disconnected ({len(self._clients)} client(s))")

        return ws

    async def _handle_command(self, ws: web.WebSocketResponse, raw: str):
        """Parse and dispatch incoming UI commands."""
        req_id = None
        try:
            msg = json.loads(raw)
            cmd = msg.get("cmd")
            data = msg.get("data", {})
            req_id = msg.get("id")

            log.debug(f"Command received: cmd={cmd!r} id={req_id!r} data={data!r}")

            result = None
            error = None

            if cmd == "add_download":
                task = await self._manager.add_download(
                    url=data["url"],
                    save_dir=data.get("save_dir", ""),
                    filename=data.get("filename", ""),
                    num_connections=data.get("connections", 8),
                )
                result = task.to_dict()

            elif cmd == "pause":
                await self._manager.pause_download(data["id"])
                result = {"ok": True}

            elif cmd == "resume":
                await self._manager.resume_download(data["id"])
                result = {"ok": True}

            elif cmd == "cancel":
                await self._manager.cancel_download(data["id"])
                result = {"ok": True}

            elif cmd == "remove":
                await self._manager.remove_download(data["id"], data.get("delete_file", False))
                result = {"ok": True}

            elif cmd == "get_tasks":
                result = self._manager.get_all_tasks()

            elif cmd == "get_stats":
                result = self._manager.get_stats()

            elif cmd == "ping":
                result = {"pong": True}

            else:
                error = f"Unknown command: {cmd!r}"
                log.warning(error)

            reply = {"type": "reply", "id": req_id}
            if error:
                reply["error"] = error
            else:
                reply["result"] = result

            await self._send_raw(ws, reply)

        except KeyError as e:
            # Missing required field in data dict
            msg_out = f"Missing required field: {e}"
            log.error(f"_handle_command KeyError: {msg_out} (raw={raw!r})")
            await self._send_raw(ws, {"type": "error", "id": req_id, "message": msg_out})

        except json.JSONDecodeError as e:
            log.error(f"_handle_command bad JSON: {e} (raw={raw!r})")
            await self._send_raw(ws, {"type": "error", "id": req_id, "message": f"Invalid JSON: {e}"})

        except Exception as e:
            # FIX: was log.exception but only the message was forwarded to the UI,
            # making it impossible to debug from the frontend alone.
            log.exception(f"_handle_command unhandled error: {e}")
            await self._send_raw(ws, {"type": "error", "id": req_id, "message": str(e)})

    # ─────────────────────────────────────────────
    # HTTP API (for browser extension)
    # ─────────────────────────────────────────────

    async def http_status(self, request: web.Request) -> web.Response:
        return web.json_response({"status": "running", "version": "1.0.0"})

    async def http_downloads(self, request: web.Request) -> web.Response:
        return web.json_response(self._manager.get_all_tasks())

    async def http_stats(self, request: web.Request) -> web.Response:
        return web.json_response(self._manager.get_stats())

    async def http_add(self, request: web.Request) -> web.Response:
        try:
            body = await request.json()
            url = body.get("url", "").strip()
            if not url:
                return web.json_response({"error": "url required"}, status=400)

            log.info(f"HTTP /add: {url}")
            task = await self._manager.add_download(
                url=url,
                save_dir=body.get("save_dir", ""),
                filename=body.get("filename", ""),
                num_connections=body.get("connections", 8),
            )
            return web.json_response({"ok": True, "task": task.to_dict()})
        except Exception as e:
            log.exception(f"HTTP /add error: {e}")
            return web.json_response({"error": str(e)}, status=500)

    # ─────────────────────────────────────────────
    # Broadcasting
    # ─────────────────────────────────────────────

    async def _broadcast_event(self, event_type: str, data: dict):
        """Push a real-time event to all connected UI windows."""
        if not self._clients:
            return
        msg = json.dumps({"type": "event", "event": event_type, "data": data})
        dead = set()
        for ws in list(self._clients):   # FIX: iterate a copy so we can mutate safely
            try:
                await ws.send_str(msg)
            except Exception as e:
                log.warning(f"_broadcast_event: client send failed ({e}), removing client")
                dead.add(ws)
        self._clients -= dead

    async def _send(self, ws: web.WebSocketResponse, event: str, data: dict):
        await self._send_raw(ws, {"type": "event", "event": event, "data": data})

    async def _send_raw(self, ws: web.WebSocketResponse, obj: dict):
        try:
            await ws.send_str(json.dumps(obj))
        except Exception as e:
            # FIX: was silently swallowed — now logged so you can see dropped messages
            log.warning(f"_send_raw failed: {e}")

    # ─────────────────────────────────────────────
    # App startup
    # ─────────────────────────────────────────────

    def build_app(self) -> web.Application:
        app = web.Application(middlewares=[cors_middleware])

        app.router.add_get("/ws", self.ws_handler)
        app.router.add_get("/status", self.http_status)
        app.router.add_get("/downloads", self.http_downloads)
        app.router.add_get("/stats", self.http_stats)
        app.router.add_post("/add", self.http_add)

        app.on_startup.append(self._on_startup)
        app.on_shutdown.append(self._on_shutdown)
        return app

    async def _on_startup(self, app):
        await self._manager.start()
        log.info("MiDM Engine started")

    async def _on_shutdown(self, app):
        await self._manager.stop()
        # Close all open WebSocket connections gracefully
        for ws in list(self._clients):
            try:
                await ws.close()
            except Exception:
                pass
        log.info("MiDM Engine stopped")


def main():
    server = MiDMServer()
    app = server.build_app()

    log.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    log.info("  MiDM Backend  v1.0.0")
    log.info(f"  WS  → ws://localhost:{WS_PORT}/ws")
    log.info(f"  API → http://localhost:{WS_PORT}")
    log.info(f"  Log → {Path.home() / '.midm' / 'server.log'}")
    log.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    web.run_app(app, host="127.0.0.1", port=WS_PORT, access_log=log)


if __name__ == "__main__":
    main()