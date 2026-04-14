"""
Modelos SQLAlchemy para la base de datos del evento.
"""

from datetime import datetime, timezone

from sqlalchemy import BigInteger, Boolean, DateTime, String, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class InvitationCode(Base):
    """Código de invitación para registro controlado."""

    __tablename__ = "invitation_codes"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(32), nullable=False, unique=True, index=True)
    used: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    usado_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relación con el attendee que usó este código
    attendee_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("attendees.id"), nullable=True)

    def __repr__(self):
        return f"<InvitationCode code={self.code} used={self.used}>"


class Attendee(Base):
    """Asistente al evento."""

    __tablename__ = "attendees"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    nombre: Mapped[str] = mapped_column(String(255), nullable=False)
    apellido: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    nro_documento: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    email: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    invitado_por: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    qr_token: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    hash_unique: Mapped[str] = mapped_column(String(64), nullable=False, default="", index=True)
    estado_ingreso: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    fecha_ingreso: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relación con el código de invitación usado
    invitation_code_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("invitation_codes.id"), nullable=True)

    def __repr__(self):
        return f"<Attendee id={self.id} nombre={self.nombre} {self.apellido} qr_token={self.qr_token[:8]}...>"


class AdminUser(Base):
    """Usuario administrador del panel."""

    __tablename__ = "admin_users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="scanner_only")  # "super_admin" | "scanner_only"
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    def __repr__(self):
        return f"<AdminUser id={self.id} username={self.username} role={self.role}>"
