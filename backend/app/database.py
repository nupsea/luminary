import logging
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    pass


def _get_db_url() -> str:
    settings = get_settings()
    data_dir = Path(settings.DATA_DIR).expanduser()
    data_dir.mkdir(parents=True, exist_ok=True)
    return f"sqlite+aiosqlite:///{data_dir}/luminary.db"


def make_engine(db_url: str | None = None):
    url = db_url or _get_db_url()
    return create_async_engine(url, echo=False)


_engine = None
_session_factory = None


def get_engine():
    global _engine
    if _engine is None:
        _engine = make_engine()
    return _engine


def get_session_factory():
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _session_factory


async def get_db() -> AsyncSession:  # type: ignore[return]
    async with get_session_factory()() as session:
        yield session
