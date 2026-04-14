"""
Pydantic schemas para request/response validation.
"""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class StatusType(str, Enum):
    WELCOME = "WELCOME"
    ALREADY_USED = "ALREADY_USED"
    INVALID = "INVALID"
    ERROR = "ERROR"
    PAYMENT_REQUIRED = "PAYMENT_REQUIRED"  # VIP que no pagó


class CheckResponse(BaseModel):
    status: StatusType
    nombre: str | None = None
    fecha_ingreso: str | None = None
    message: str | None = None
    # Campos para VIP
    tipo_acceso: str | None = None
    pago_confirmado: bool | None = None
    mp_preference_id: str | None = None
    mp_init_point: str | None = None


class StatsResponse(BaseModel):
    total: int
    ingresaron: int
    pendientes: int
