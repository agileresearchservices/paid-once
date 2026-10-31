"""The show server: starts every service, drives the scenes, and streams the scoreboard to the UI."""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from raccoon import agent, audit, config
from raccoon.lane2.client import ensure_setup
from raccoon.show.engine import SCENES, Engine
from raccoon.show.procs import ProcessManager

UI_DIST = config.ROOT / "ui" / "dist"
state: dict = {}


@asynccontextmanager
async def lifespan(_: FastAPI):
    if not agent.have_api_key():
        raise RuntimeError("Set ANTHROPIC_API_KEY: both lanes call a real Anthropic model.")
    config.ensure_data_dir()
    audit.init()
    procs = ProcessManager()
    note = await asyncio.to_thread(procs.ensure_temporal)
    setup_notes = await asyncio.to_thread(ensure_setup)
    engine = Engine(procs)
    state.update(procs=procs, engine=engine)
    procs.start_all()
    ready = await asyncio.to_thread(procs.wait_ready)
    await asyncio.sleep(2.0)  # let the workers register their pollers
    await engine.reset()  # a demo starts from zero, not from the last session's scoreboard
    engine.emit("boot", note)
    for line in setup_notes:
        engine.emit("boot", line)
    engine.emit("boot", "services ready" if ready else "services are slow to start")

    async def refresher() -> None:
        while True:
            await engine.refresh_views()
            await asyncio.sleep(1.0)

    task = asyncio.create_task(refresher())
    try:
        yield
    finally:
        task.cancel()
        procs.stop_all()


app = FastAPI(title="Paid Once", lifespan=lifespan)


@app.get("/api/state")
def get_state() -> dict:
    return state["engine"].snapshot()


@app.get("/api/stream")
async def stream() -> StreamingResponse:
    async def gen():
        while True:
            yield f"data: {json.dumps(state['engine'].snapshot())}\n\n"
            await asyncio.sleep(0.7)

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@app.post("/api/scenes/{scene_id}/run")
async def run_scene(scene_id: str) -> dict:
    if scene_id not in {s.id for s in SCENES}:
        raise HTTPException(404, "unknown scene")
    started = await state["engine"].run_scene(scene_id)
    if not started:
        raise HTTPException(409, "a scene is already running")
    return {"started": scene_id}


@app.post("/api/reset")
async def reset() -> dict:
    await state["engine"].reset()
    return {"ok": True}


@app.post("/api/raccoon/kill/{proc}")
async def kill(proc: str) -> dict:
    procs: ProcessManager = state["procs"]
    if proc not in procs.procs:
        raise HTTPException(404, "unknown process")
    return {"killed": procs.kill(proc, 4.0)}


if UI_DIST.exists():
    app.mount("/assets", StaticFiles(directory=UI_DIST / "assets"), name="assets")

    @app.get("/{path:path}")
    def spa(path: str):
        candidate = UI_DIST / path
        return FileResponse(candidate if path and candidate.is_file() else UI_DIST / "index.html")


def main() -> None:
    import uvicorn

    uvicorn.run(
        app,
        host="127.0.0.1",
        port=config.SHOW_PORT,
        log_level="warning",
        timeout_graceful_shutdown=2,  # an open SSE tab must not keep the services alive after Ctrl-C
    )


if __name__ == "__main__":
    main()
