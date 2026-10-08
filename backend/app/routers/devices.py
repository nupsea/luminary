"""Device pairing and revocation.

Routes: POST /devices/pairing-code, POST /devices/pair, GET /devices, DELETE /devices/{id}

Always registered: pairing is how any caller other than the app gets in, in both modes.
Only `/devices/pair` is reachable unpaired (`runtime/request_auth.py`); managing devices
is the app's own, so a paired device cannot mint codes or revoke its peers.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field

from app.exceptions import Forbidden
from app.models import DeviceModel
from app.repos.device_repo import DeviceRepo, get_device_repo
from app.services import devices as device_service

router = APIRouter(prefix="/devices", tags=["devices"])


def require_local(request: Request) -> None:
    principal = getattr(request.state, "principal", None)
    if principal is None or principal.kind != "local":
        raise Forbidden("Devices are managed from Luminary itself.")


class PairingCodeResponse(BaseModel):
    code: str
    expires_at: datetime


class PairRequest(BaseModel):
    code: str = Field(..., min_length=1, max_length=32)
    name: str = Field(..., min_length=1, max_length=80)


class PairResponse(BaseModel):
    device_id: str
    name: str
    # Shown once; only its hash is kept.
    token: str


class DeviceResponse(BaseModel):
    id: str
    name: str
    created_at: datetime
    last_seen_at: datetime | None
    revoked_at: datetime | None


def _to_response(device: DeviceModel) -> DeviceResponse:
    return DeviceResponse(
        id=device.id,
        name=device.name,
        created_at=device.created_at,
        last_seen_at=device.last_seen_at,
        revoked_at=device.revoked_at,
    )


@router.post(
    "/pairing-code", response_model=PairingCodeResponse, dependencies=[Depends(require_local)]
)
async def create_pairing_code() -> PairingCodeResponse:
    code, expires_at = device_service.issue_pairing_code()
    return PairingCodeResponse(code=code, expires_at=expires_at)


@router.post("/pair", response_model=PairResponse, status_code=201)
async def pair_device(
    req: PairRequest, repo: DeviceRepo = Depends(get_device_repo)
) -> PairResponse:
    device, token = await device_service.pair(repo, req.code, req.name)
    return PairResponse(device_id=device.id, name=device.name, token=token)


@router.get("", response_model=list[DeviceResponse], dependencies=[Depends(require_local)])
async def list_devices(repo: DeviceRepo = Depends(get_device_repo)) -> list[DeviceResponse]:
    return [_to_response(d) for d in await device_service.list_devices(repo)]


@router.delete("/{device_id}", status_code=204, dependencies=[Depends(require_local)])
async def revoke_device(device_id: str, repo: DeviceRepo = Depends(get_device_repo)) -> Response:
    await device_service.revoke(repo, device_id)
    return Response(status_code=204)
