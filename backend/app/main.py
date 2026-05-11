import asyncio
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .abandoned_dialogs import process_abandoned_dialogs
from .api_router import router

logger = logging.getLogger(__name__)

app = FastAPI(title="Support Bot", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


async def _abandoned_dialogs_loop() -> None:
    while True:
        try:
            await asyncio.to_thread(process_abandoned_dialogs)
        except Exception:
            logger.exception("Abandoned dialogs sweep failed")
        await asyncio.sleep(60)


@app.on_event("startup")
async def start_abandoned_dialogs_loop() -> None:
    app.state.abandoned_dialogs_task = asyncio.create_task(_abandoned_dialogs_loop())


@app.on_event("shutdown")
async def stop_abandoned_dialogs_loop() -> None:
    task = getattr(app.state, "abandoned_dialogs_task", None)
    if not task:
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
