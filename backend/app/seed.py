"""
Script de seed/importación de asistentes desde CSV.
"""

import csv
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Attendee


CSV_PATH = Path(os.getenv("SEED_CSV_PATH", "/app/data/asistentes_import.csv"))


def gen_unique_hashes(n: int) -> list[str]:
    """Genera N strings hex únicos de 16 caracteres."""
    hashes: set[str] = set()
    while len(hashes) < n:
        hashes.add(uuid.uuid4().hex[:16].upper())
    return list(hashes)


async def seed_from_csv(session: AsyncSession, csv_path: Optional[Path] = None) -> int:
    """
    Lee el CSV de asistentes, genera hashes únicos, y los inserta en la DB.
    Retorna la cantidad de asistentes insertados.
    """
    path = csv_path or CSV_PATH

    if not path.is_file():
        raise FileNotFoundError(f"CSV no encontrado: {path}")

    attendees = []
    with open(path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            nombre = (
                row.get("Nombre") or row.get("nombre") or
                row.get("Name") or row.get("name") or ""
            ).strip()
            email = (
                row.get("Email") or row.get("email") or
                row.get("EMAIL") or ""
            ).strip()
            if nombre:
                attendees.append({"nombre": nombre, "email": email})

    if not attendees:
        raise ValueError("CSV vacío o sin datos válidos")

    # Generar hashes
    hashes = gen_unique_hashes(len(attendees))

    # Crear objetos Attendee
    records = []
    for i, att in enumerate(attendees):
        records.append(Attendee(
            id=i + 1,
            nombre=att["nombre"],
            email=att["email"],
            hash_unique=hashes[i],
            estado_ingreso=False,
            fecha_ingreso=None,
        ))

    session.add_all(records)
    await session.commit()

    return len(records)
