"""The show server: starts every service, drives the scenes, and streams the scoreboard to the UI."""

from __future__ import annotations

import asyncio
import json
import os
import signal
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from paidonce import agent, audit, config, tls
from paidonce.lane2.client import ensure_setup
from paidonce.show.engine import SCENES, Engine
from paidonce.show.procs import ProcessManager, port_open

UI_DIST = config.ROOT / "ui" / "dist"
SCENARIO_HEADER = "x-paidonce-scenario"
state: dict = {}


def guard(request: Request) -> None:
    """While `make scenario` owns this server, only its runner may change the show."""
    if config.SCENARIO_TOKEN and request.headers.get(SCENARIO_HEADER) != config.SCENARIO_TOKEN:
        raise HTTPException(423, "make scenario is running on this server; the controls are locked until it ends")


def snapshot() -> dict:
    return {**state["engine"].snapshot(), "locked": "make scenario" if config.SCENARIO_TOKEN else None}


@asynccontextmanager
async def lifespan(_: FastAPI):
    if not agent.have_api_key():
        raise RuntimeError("Set ANTHROPIC_API_KEY: both lanes call a real Anthropic model.")
    config.ensure_data_dir()
    audit.init()
    procs = ProcessManager()
    task: asyncio.Task | None = None
    try:  # from here on, a failed startup must still stop whatever has already started
        note = await asyncio.to_thread(procs.ensure_temporal)
        setup_notes = await asyncio.to_thread(ensure_setup)
        engine = Engine(procs)
        state.update(procs=procs, engine=engine)
        if config.PAYMENTS_TLS or config.LANE1_TLS:
            await asyncio.to_thread(
                tls.ensure_certs
            )  # before any process starts, so every caller finds the certificate
        procs.start_all()
        ready = await asyncio.to_thread(procs.wait_ready)
        await asyncio.sleep(2.0)  # let the workers register their pollers
        await engine.reset()  # a demo starts from zero, not from the last session's scoreboard
        engine.emit("boot", note)
        for line in setup_notes:
            engine.emit("boot", line)
        engine.emit("boot", "services ready" if ready else "services are slow to start")
        task = asyncio.create_task(_refresh_forever(engine))
        yield
    finally:
        if task:
            task.cancel()
        procs.stop_all()


async def _refresh_forever(engine: Engine) -> None:
    """Keep the live views fresh. One failed refresh (a Temporal blip, say) must not freeze the page for good."""
    last_error = ""
    while True:
        try:
            await engine.refresh_views()
            last_error = ""
        except Exception as exc:
            if repr(exc) != last_error:  # say it once, not every second
                last_error = repr(exc)
                engine.emit("error", f"refreshing the live views failed: {last_error[:120]}")
        await asyncio.sleep(1.0)


app = FastAPI(title="Paid Once", lifespan=lifespan)


@app.get("/api/state")
def get_state() -> dict:
    return snapshot()


@app.get("/api/stream")
async def stream() -> StreamingResponse:
    async def gen():
        while True:
            yield f"data: {json.dumps(snapshot())}\n\n"
            await asyncio.sleep(0.7)

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@app.post("/api/scenes/{scene_id}/run")
async def run_scene(scene_id: str, request: Request) -> dict:
    guard(request)
    if scene_id not in {s.id for s in SCENES}:
        raise HTTPException(404, "unknown scene")
    started = await state["engine"].run_scene(scene_id)
    if not started:
        raise HTTPException(409, "a scene is already running")
    return {"started": scene_id}


@app.post("/api/reset")
async def reset(request: Request) -> dict:
    guard(request)
    await state["engine"].reset()
    return {"ok": True}


@app.post("/api/faults/kill/{proc}")
async def kill(proc: str, request: Request) -> dict:
    guard(request)
    procs: ProcessManager = state["procs"]
    if proc not in procs.procs:
        raise HTTPException(404, "unknown process")
    return {"killed": procs.kill(proc, 4.0)}


def spa_response(root: Path, path: str) -> FileResponse:
    """A file under `root`, else the app's index.html for the in-page router.

    Never a file outside `root` (a `..` in the path), and never index.html for an API path or a missing asset:
    those are a 404, so a typo doesn't look like a working endpoint.
    """
    if path.startswith("api/"):
        raise HTTPException(404, "no such endpoint")
    root = root.resolve()
    candidate = (root / path).resolve()
    if path and candidate.is_relative_to(root) and candidate.is_file():
        return FileResponse(candidate)
    if path.startswith("brand/"):  # the optional, gitignored logo and favicon
        raise HTTPException(404, "not found")
    return FileResponse(root / "index.html")


if UI_DIST.exists():
    app.mount("/assets", StaticFiles(directory=UI_DIST / "assets"), name="assets")

    @app.get("/{path:path}")
    def spa(path: str) -> FileResponse:
        return spa_response(UI_DIST, path)


def main() -> None:
    import uvicorn

    # A second instance runs its whole startup before the bind fails: it spawns duplicate workers and its
    # boot-time reset wipes the running show's ledger. Refuse before any of that.
    if port_open(config.SHOW_PORT):
        raise SystemExit(
            f"Port {config.SHOW_PORT} is already serving (a show server or `make scenario`?). Not starting a "
            f"second one: its startup would reset the running show. See: lsof -nP -iTCP:{config.SHOW_PORT} -sTCP:LISTEN"
        )
    # Closing the terminal sends SIGHUP, which uvicorn doesn't handle: the show died without stop_all(), and the
    # services, each in its own session, kept their ports. Shut down as for Ctrl-C instead.
    signal.signal(signal.SIGHUP, lambda *_: os.kill(os.getpid(), signal.SIGTERM))
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=config.SHOW_PORT,
        log_level="warning",
        timeout_graceful_shutdown=2,  # an open SSE tab must not keep the services alive after Ctrl-C
    )


if __name__ == "__main__":
    main()
