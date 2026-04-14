"""
Migración: agregar campos VIP a attendees (tipo_acceso, pago_confirmado, mp_preference_id, mp_payment_id, monto_abonar).
Ejecutar: python -m app.migrate_vip_fields
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from app.database import async_engine

COLUMNS = [
    ("tipo_acceso", "VARCHAR(20) NOT NULL DEFAULT 'GENERAL'"),
    ("pago_confirmado", "BOOLEAN NOT NULL DEFAULT FALSE"),
    ("mp_preference_id", "VARCHAR(255)"),
    ("mp_payment_id", "VARCHAR(255)"),
    ("monto_abonar", "FLOAT"),
]


async def migrate():
    async with async_engine.begin() as conn:
        for col_name, col_type in COLUMNS:
            result = await conn.execute(text("""
                SELECT column_name FROM information_schema.columns
                WHERE table_name = 'attendees' AND column_name = :col
            """), {"col": col_name})
            if result.scalar():
                print(f"  ⏭  Columna '{col_name}' ya existe en attendees")
                continue

            await conn.execute(text(f"""
                ALTER TABLE attendees
                ADD COLUMN {col_name} {col_type}
            """))
            print(f"  ✅ Columna '{col_name}' agregada a attendees")

    print("\n✅ Migración VIP completada")


if __name__ == "__main__":
    print("🔧 Migrando attendees: agregar campos VIP...")
    asyncio.run(migrate())
