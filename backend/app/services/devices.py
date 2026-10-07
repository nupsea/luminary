"""Device pairing: a one-time code shown by the app, exchanged for a named, revocable token.

One mechanism for every consumer that is not the app's own origin on loopback: the
self-hosted server, the phone and the capture extension (roadmap, 0.16.0). The token is
returned once and only its SHA-256 is stored; a 256-bit random secret needs no slow hash.
"""

from __future__ import annotations

import hashlib
import secrets
import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.exceptions import Forbidden, InvalidInput
from app.models import DeviceModel
from app.repos.device_repo import DeviceRepo
from app.types import Principal

# Unambiguous when read off a screen: no 0/O, 1/I/L.
_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
_CODE_LENGTH = 8
_CODE_TTL_S = 300
# Five wrong guesses kill the code: a 31^8 space then admits 5 in ~8.5e11 per code
# the user chose to show, and a typo or two still pairs.
_MAX_FAILED_ATTEMPTS = 5
_TOKEN_PREFIX = "lum_"  # noqa: S105 - a public marker that makes a leaked token greppable
# A request per device would otherwise be a write per request.
_TOUCH_INTERVAL = timedelta(seconds=60)


@dataclass
class _PairingCode:
    code_hash: str
    expires_at: float
    failed_attempts: int = 0


# Process memory: one worker serves every request, and a restart only voids a
# code that lives five minutes anyway. Issuing a code replaces the previous one.
_active_code: _PairingCode | None = None


def hash_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def _normalise_code(code: str) -> str:
    return "".join(ch for ch in code.upper() if ch.isalnum())


def issue_pairing_code() -> tuple[str, datetime]:
    global _active_code
    code = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(_CODE_LENGTH))
    _active_code = _PairingCode(hash_secret(code), time.monotonic() + _CODE_TTL_S)
    expires_at = datetime.now(UTC) + timedelta(seconds=_CODE_TTL_S)
    return f"{code[:4]}-{code[4:]}", expires_at


def _consume_code(code: str) -> None:
    """Spend the active code, or count a failure against it.

    One message for wrong, expired, used and absent: the caller is unpaired, and which
    of those it was would only help it guess.
    """
    global _active_code
    refused = Forbidden("That pairing code is not valid. Show a new one in Luminary.")
    active = _active_code
    if active is None or time.monotonic() > active.expires_at:
        _active_code = None
        raise refused
    if not secrets.compare_digest(hash_secret(_normalise_code(code)), active.code_hash):
        active.failed_attempts += 1
        if active.failed_attempts >= _MAX_FAILED_ATTEMPTS:
            _active_code = None
        raise refused
    _active_code = None


async def pair(repo: DeviceRepo, code: str, name: str) -> tuple[DeviceModel, str]:
    name = name.strip()
    if not name:
        raise InvalidInput("A device needs a name, so it can be told apart when revoking.")
    _consume_code(code)
    token = _TOKEN_PREFIX + secrets.token_urlsafe(32)
    device = await repo.create(name=name, token_hash=hash_secret(token))
    return device, token


async def resolve_token(repo: DeviceRepo, token: str) -> Principal | None:
    """The principal a bearer token stands for, or None if it is unknown or revoked."""
    device = await repo.by_token_hash(hash_secret(token))
    if device is None or device.revoked_at is not None:
        return None
    now = datetime.now(UTC)
    seen = device.last_seen_at
    if seen is not None and seen.tzinfo is None:
        seen = seen.replace(tzinfo=UTC)
    if seen is None or now - seen > _TOUCH_INTERVAL:
        await repo.touch(device, now)
    return Principal(kind="device", device_id=device.id)


async def list_devices(repo: DeviceRepo) -> Sequence[DeviceModel]:
    return await repo.list()


async def revoke(repo: DeviceRepo, device_id: str) -> DeviceModel:
    return await repo.revoke(device_id)
