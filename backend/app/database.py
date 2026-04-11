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
        from app.models import Attendee, AdminUser  # noqa: F401
        await conn.run_sync(Base.metadata.create_all)
        # Seed de usuarios admin si no existen
        await conn.run_sync(_seed_admin_users)


def _seed_admin_users(connection):
    """Crear usuarios admin si la tabla está vacía (ejecutado sincrónicamente)."""
    import bcrypt
    from sqlalchemy import text

    # Contraseñas seguras para los 8 usuarios admin
    ADMIN_PASSWORDS = {
        "4dm1n01": "0xFVrXh%Rs%mt*rr",
        "4dm1n02": "ktKK673d6ZdrlH!z",
        "4dm1n03": "X%p^G@bLjAuwOh%W",
        "4dm1n04": "!&n2!*%Wa5New@P*",
        "4dm1n05": "3w0rqYjjEi6zSR%L",
        "4dm1n06": "C6B^BSw9@*@svJRc",
        "4dm1n07": "6eo^S6I$h55P^Fh%",
        "4dm1n08": "Y!W#5X#YtWgFlW&V",
    }

    result = connection.execute(text("SELECT COUNT(*) FROM admin_users"))
    count = result.scalar()
    if count > 0:
        return  # Ya existen usuarios admin

    for username, password in ADMIN_PASSWORDS.items():
        hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
        connection.execute(
            text("INSERT INTO admin_users (username, password_hash, activo, creado_en) VALUES (:u, :p, TRUE, NOW())"),
            {"u": username, "p": hashed},
        )
