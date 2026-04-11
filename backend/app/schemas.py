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


class CheckResponse(BaseModel):
    status: StatusType
    nombre: str | None = None
    fecha_ingreso: str | None = None
    message: str | None = None


class StatsResponse(BaseModel):
    total: int
    ingresaron: int
    pendientes: int
