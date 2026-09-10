"""First-run and post-install setup: what is installed, and installing more.

Always registered, in both modes -- a user whose setup is incomplete needs these
endpoints precisely when the rest of the app is not yet usable.
"""

import json
import logging

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import StreamingResponse

from app.services.components import (
    capabilities,
    component_status,
    get_component,
    install_component,
    remove_component,
)
from app.services.diagnostics import environment_report
from app.services.enrichment_worker import requeue_skipped_jobs
from app.services.lifecycle import request_shutdown
from app.services.startup_status import get_startup_status
from app.services.warmup import retry_failed

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/setup", tags=["setup"])


@router.get("/components")
async def list_components() -> dict:
    return {"components": await component_status()}


@router.get("/report")
async def environment_report_endpoint() -> dict:
    """The environment block for a bug report, scrubbed of the account name."""
    return {"environment": await environment_report()}


@router.get("/host-support")
async def host_support() -> dict:
    """Whether this machine can run local models at a speed worth offering.

    Separate from `/capabilities`, which answers what this *build* can do. This
    answers what this *host* can do, and it is the only place the support policy
    is stated -- the native installers refuse macOS x86_64 before they get this
    far, so the case this endpoint exists for is the container.
    """
    from app.host_support import local_inference_support  # noqa: PLC0415

    verdict = local_inference_support()
    return {
        "supported": verdict.supported,
        "reason": verdict.reason,
        "host": verdict.detail,
        "message": verdict.message,
    }


@router.get("/capabilities")
async def list_capabilities() -> dict:
    """What the UI may offer. Keeps it from advertising what this build cannot do."""
    return await capabilities()


@router.post("/shutdown", status_code=202)
async def shutdown(
    token: str | None = Header(default=None, alias="X-Luminary-Shutdown-Token"),
) -> dict:
    """Stop this process the way a SIGTERM would, for a host that has no SIGTERM.

    Here rather than in a router of its own because `setup` is already the
    non-surface router for this process's own environment, and one lifecycle
    endpoint does not earn a surface-manifest entry.

    202, not 204: the work is scheduled, not done. The response has to reach the
    shell before the signal does, or the shell reads a dropped connection and
    cannot tell a graceful stop from a crash.
    """
    request_shutdown(token)
    return {"status": "shutting_down"}


@router.post("/retry")
async def retry() -> dict:
    """Re-run whatever failed during startup.

    Without this a transient network problem on first run left the install
    permanently degraded, recoverable only by quitting and relaunching.
    """
    retried = await retry_failed()
    return {"retried": retried}


@router.post("/components/{component_id}/install")
async def install(component_id: str) -> StreamingResponse:
    comp = get_component(component_id)
    if comp is None:
        raise HTTPException(status_code=404, detail=f"unknown component: {component_id}")

    async def _stream():
        status = get_startup_status()
        # Mirror installs into the startup registry so the setup screen and the
        # boot progress agree. Keyed off the phase registry, so a new component
        # reports progress without another branch here.
        phase = component_id if status.has_phase(component_id) else None
        try:
            async for event in install_component(component_id):
                if phase is not None:
                    if event["state"] == "downloading":
                        status.set_progress(
                            phase,
                            event.get("completed_bytes", 0),
                            event.get("total_bytes", 0),
                            event.get("detail", ""),
                        )
                    else:
                        status.set_state(phase, event["state"], event.get("detail", ""))
                if event["state"] == "ready":
                    # Work that was skipped for want of this component can run now.
                    await requeue_skipped_jobs()
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
