"""
Migración: agregar columna role a admin_users.
Ejecutar: python -m app.migrate_add_role
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from app.database import async_engine


async def migrate():
    async with async_engine.begin() as conn:
        # Verificar si la columna ya existe
        result = await conn.execute(text("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'admin_users' AND column_name = 'role'
        """))
        if result.scalar():
            print("  ⏭  Columna 'role' ya existe en admin_users")
            return

        # Agregar columna con default
        await conn.execute(text("""
            ALTER TABLE admin_users
            ADD COLUMN role VARCHAR(20) NOT NULL DEFAULT 'scanner_only'
        """))
        print("  ✅ Columna 'role' agregada a admin_users")

        # Actualizar usuarios existentes a super_admin
        await conn.execute(text("""
            UPDATE admin_users SET role = 'super_admin'
        """))
        print("  ✅ Usuarios existentes actualizados a super_admin")

    print("\n✅ Migración completada")


if __name__ == "__main__":
    print("🔧 Migrando admin_users: agregar columna role...")
    asyncio.run(migrate())
