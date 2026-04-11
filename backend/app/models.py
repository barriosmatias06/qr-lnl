"""
Modelos SQLAlchemy para la base de datos del evento.
"""

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Attendee(Base):
    """Asistente al evento."""

    __tablename__ = "attendees"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    nombre: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    hash_unique: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    estado_ingreso: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    fecha_ingreso: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def __repr__(self):
        return f"<Attendee id={self.id} nombre={self.nombre} hash={self.hash_unique[:8]}...>"
