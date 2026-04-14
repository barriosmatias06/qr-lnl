"""
Script para crear usuarios administradores iniciales.
Ejecutar: python -m app.seed_admins
"""

import asyncio
import sys
from pathlib import Path

# Agregar el root del proyecto al path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select
from app.database import async_engine, async_session
from app.models import AdminUser

ADMINS = [
    # Super admins (acceso completo al panel)
    {"username": "4dm1n01", "password": "dominic2024!", "role": "super_admin"},
    {"username": "4dm1n02", "password": "dominic2024!", "role": "super_admin"},
    # Scanner only (solo pueden escanear QR)
    {"username": "4dm1n03", "password": "dominic2024!", "role": "scanner_only"},
    {"username": "4dm1n04", "password": "dominic2024!", "role": "scanner_only"},
    {"username": "4dm1n05", "password": "dominic2024!", "role": "scanner_only"},
]


def _hash_password(plain: str) -> str:
    import bcrypt
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


async def seed_admins():
    from app.database import Base
    # Crear tablas si no existen
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with async_session() as session:
        for admin_data in ADMINS:
            # Verificar si ya existe
            result = await session.execute(
                select(AdminUser).where(AdminUser.username == admin_data["username"])
            )
            existing = result.scalar_one_or_none()
            if existing:
                print(f"  ⏭  {admin_data['username']} ya existe")
                continue

            user = AdminUser(
                username=admin_data["username"],
                password_hash=_hash_password(admin_data["password"]),
                role=admin_data["role"],
                activo=True,
            )
            session.add(user)
            print(f"  ✅ {admin_data['username']} ({admin_data['role']})")

        await session.commit()

    print("\n✅ Usuarios admin creados correctamente")


if __name__ == "__main__":
    print("🌱 Creando usuarios administradores...")
    asyncio.run(seed_admins())
