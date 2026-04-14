"""FastAPI app factory, process lifespan, shared clients, and scheduler wiring."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from app.api.routes import router
from app.backends.registry import BackendRegistry
from app.core.config import load_gateway_config
from app.core.logging import log_gateway_event, setup_logging, shutdown_logging
from app.queue.admission_queue import AdmissionQueue
from app.scheduler.dispatcher import run_scheduler_loop

setup_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: config, registry, queue, httpx client, background scheduler. Shutdown: cancel + close."""
    cfg = load_gateway_config()
    registry = BackendRegistry(cfg)
    queue = AdmissionQueue(cfg.scheduler.queue_max_size)
    stop = asyncio.Event()
    client = httpx.AsyncClient(http2=False, limits=httpx.Limits(max_connections=1000, max_keepalive_connections=200))
    scheduler_task = asyncio.create_task(
        run_scheduler_loop(cfg, registry, queue, stop),
        name="gateway-scheduler",
    )
    app.state.cfg = cfg
    app.state.registry = registry
    app.state.queue = queue
    app.state.http = client
    log_gateway_event(
        logger,
        logging.INFO,
        "gateway_started",
        gateway_meta={
            "host": cfg.server.host,
            "port": cfg.server.port,
            "backends": [b.name for b in cfg.backends],
        },
    )
    yield
    stop.set()
    scheduler_task.cancel()
    try:
        await scheduler_task
    except asyncio.CancelledError:
        pass
    try:
        await client.aclose()
    finally:
        shutdown_logging()


app = FastAPI(title="layer-gateway-inference-v1", lifespan=lifespan)
app.include_router(router)


def main() -> None:
    """CLI entry: run uvicorn with host/port from config."""
    import uvicorn

    cfg = load_gateway_config()
    uvicorn.run(
        "app.main:app",
        host=cfg.server.host,
        port=cfg.server.port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
