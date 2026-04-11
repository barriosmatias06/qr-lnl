"""
Configuración de base de datos async con SQLAlchemy + PostgreSQL.
"""

import os

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase

# ── Configuración ──────────────────────────────────────────────────────────

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://evento:evento_pass@db:5432/evento_db",
)

# Para migraciones sincrónicas (alembic / seed inicial)
SYNC_DATABASE_URL = DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")

async_engine = create_async_engine(DATABASE_URL, echo=False, pool_size=10, max_overflow=20)
async_session: async_sessionmaker[AsyncSession] = async_sessionmaker(async_engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def init_db():
    """Crear tablas si no existen (idempotente)."""
    async with async_engine.begin() as conn:
        # Importar modelos para que se registren en Base.metadata
        from app.models import Attendee  # noqa: F401
        await conn.run_sync(Base.metadata.create_all)
