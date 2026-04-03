"""HTTP + SSE server wrapping the GameSession orchestrator."""

from __future__ import annotations

import argparse
import json

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Route

from lorekit.orchestrator import GameSession
from lorekit.providers.base import GameEvent

# Module-level session — set by serve() or main().
_session: GameSession | None = None


async def message_endpoint(request: Request) -> StreamingResponse:
    """POST /message — stream GameEvents as SSE."""
    if _session is None:
        return JSONResponse({"error": "Server not ready"}, status_code=503)
    body = await request.json()
    text = body.get("text")
    if not text:
        return JSONResponse({"error": "text is required"}, status_code=400)
    verbose = body.get("verbose", False)

    async def event_stream():
        async for event in _session.send(text, verbose=verbose):
            yield f"data: {json.dumps({'type': event.type, 'content': event.content})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def command_endpoint(request: Request) -> JSONResponse:
    """POST /command — execute a direct command, return JSON."""
    if _session is None:
        return JSONResponse({"error": "Server not ready"}, status_code=503)
    body = await request.json()
    cmd = body.pop("cmd", None)
    if not cmd:
        return JSONResponse({"error": "cmd is required"}, status_code=400)
    result = await _session.command(cmd, **body)
    return JSONResponse({"result": result})


async def events_endpoint(request: Request) -> StreamingResponse:
    """GET /events — persistent SSE stream for server lifecycle events."""
    if _session is None:
        return JSONResponse({"error": "Server not ready"}, status_code=503)

    queue = _session.subscribe()

    async def event_stream():
        try:
            while True:
                event = await queue.get()
                if event is None:
                    break
                yield f"data: {json.dumps({'type': event.type, 'content': event.content})}\n\n"
        finally:
            _session.unsubscribe(queue)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


app = Starlette(
    routes=[
        Route("/message", message_endpoint, methods=["POST"]),
        Route("/command", command_endpoint, methods=["POST"]),
        Route("/events", events_endpoint, methods=["GET"]),
    ],
)


async def serve(campaign_dir, provider=None, model=None, port=8765):
    """Start the HTTP server programmatically."""
    import asyncio

    import uvicorn

    global _session
    _session = GameSession(campaign_dir=campaign_dir, provider=provider, model=model)

    config = uvicorn.Config(app, host="127.0.0.1", port=port)
    server = uvicorn.Server(config)

    # Run GameSession.start() in background once the server is accepting connections.
    # The 2s delay gives clients time to connect to GET /events before lifecycle
    # events are emitted.
    async def _delayed_start():
        try:
            await asyncio.sleep(2)
            await _session.start()
        except Exception as e:
            import traceback

            traceback.print_exc()
            _session._emit(GameEvent(type="error", content=f"Server startup failed: {e}"))

    start_task = asyncio.create_task(_delayed_start())
    try:
        await server.serve()
    finally:
        start_task.cancel()
        await _session.stop()


def main():
    """CLI entry point: lorekit serve --campaign-dir /path."""
    import asyncio

    parser = argparse.ArgumentParser(prog="lorekit")
    sub = parser.add_subparsers(dest="command")
    serve_cmd = sub.add_parser("serve", help="Start the HTTP server")
    serve_cmd.add_argument("--campaign-dir", help="Path to campaign directory")
    serve_cmd.add_argument("--provider", help="Agent provider name")
    serve_cmd.add_argument("--model", help="Model name")
    serve_cmd.add_argument("--port", type=int, default=8765, help="HTTP server port")

    args = parser.parse_args()
    if args.command == "serve":
        from pathlib import Path

        campaign_dir = Path(args.campaign_dir) if args.campaign_dir else None
        asyncio.run(
            serve(
                campaign_dir=campaign_dir,
                provider=args.provider,
                model=args.model,
                port=args.port,
            )
        )
    else:
        parser.print_help()
