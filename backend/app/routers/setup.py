"""First-run and post-install setup: what is installed, and installing more.

Always registered, in both modes -- a user whose setup is incomplete needs these
endpoints precisely when the rest of the app is not yet usable.
"""

import json
import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.services.components import (
    component_status,
    get_component,
    install_component,
    remove_component,
)
from app.services.startup_status import get_startup_status

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/setup", tags=["setup"])


@router.get("/components")
async def list_components() -> dict:
    return {"components": await component_status()}


@router.post("/components/{component_id}/install")
async def install(component_id: str) -> StreamingResponse:
    comp = get_component(component_id)
    if comp is None:
        raise HTTPException(status_code=404, detail=f"unknown component: {component_id}")

    async def _stream():
        status = get_startup_status()
        try:
            async for event in install_component(component_id):
                # Mirror model installs into the startup registry so the setup
                # screen and the boot progress show one consistent picture.
                if component_id == "chat_model":
                    if event["state"] == "downloading":
                        status.set_progress(
                            "chat_model",
                            event.get("completed_bytes", 0),
                            event.get("total_bytes", 0),
                            event.get("detail", ""),
                        )
                    else:
                        status.set_state("chat_model", event["state"], event.get("detail", ""))
                yield f"data: {json.dumps(event)}\n\n"
        except Exception as exc:
            logger.exception("component install failed: %s", component_id)
            yield f"data: {json.dumps({'state': 'failed', 'detail': str(exc)})}\n\n"

    return StreamingResponse(_stream(), media_type="text/event-stream")


@router.delete("/components/{component_id}")
async def uninstall(component_id: str) -> dict:
    if get_component(component_id) is None:
        raise HTTPException(status_code=404, detail=f"unknown component: {component_id}")
    try:
        await remove_component(component_id)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"removed": component_id}
