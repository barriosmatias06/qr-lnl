"""
Integración con Mercado Pago para pagos VIP.
Endpoints: crear preferencia de pago y recibir webhooks.
"""

import os
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import select

from app.database import async_session
from app.models import Attendee

router = APIRouter()

# ── Configuración ──────────────────────────────────────────────────────────

MP_ACCESS_TOKEN = os.getenv("MP_ACCESS_TOKEN", "")
MP_BACK_URL = os.getenv("MP_BACK_URL", "https://panel.dominic.com.ar/")
MP_VIP_AMOUNT = float(os.getenv("MP_VIP_AMOUNT", "5000"))  # Monto por defecto en ARS
MP_VIP_TITLE = os.getenv("MP_VIP_TITLE", "Entrada VIP - Evento Dominic")

MP_BASE = "https://api.mercadopago.com"


# ── Helpers ────────────────────────────────────────────────────────────────

async def mp_request(method: str, endpoint: str, json: dict | None = None):
    """Hacer request a la API de Mercado Pago."""
    headers = {
        "Authorization": f"Bearer {MP_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }
    url = f"{MP_BASE}{endpoint}"
    async with httpx.AsyncClient() as client:
        resp = await client.request(method, url, headers=headers, json=json, timeout=30)
        return resp


# ── Schemas ────────────────────────────────────────────────────────────────

class CreatePreferenceRequest(BaseModel):
    hash: str


# ── Routes ─────────────────────────────────────────────────────────────────

@router.post("/api/mp/create_preference")
async def create_payment_preference(body: CreatePreferenceRequest):
    """
    Crea una preferencia de pago en Mercado Pago para un asistente VIP.
    Retorna el init_point (URL de pago) y el preference_id.
    """
    hash_clean = body.hash.strip().upper()

    async with async_session() as session:
        stmt = select(Attendee).where(
            (Attendee.qr_token == hash_clean) | (Attendee.hash_unique == hash_clean)
        )
        result = await session.execute(stmt)
        attendee = result.scalar_one_or_none()

        if not attendee:
            raise HTTPException(status_code=404, detail="Asistente no encontrado")

        if attendee.tipo_acceso != "VIP":
            raise HTTPException(status_code=400, detail="Este asistente no requiere pago VIP")

        if attendee.pago_confirmado:
            raise HTTPException(status_code=400, detail="El pago ya fue confirmado")

        # Si ya tiene una preferencia creada, reutilizar
        if attendee.mp_preference_id:
            # Buscar la preferencia existente
            resp = await mp_request("GET", f"/checkout/preferences/{attendee.mp_preference_id}")
            if resp.status_code == 200:
                data = resp.json()
                return {
                    "preference_id": attendee.mp_preference_id,
                    "init_point": data.get("init_point"),
                    "amount": attendee.monto_abonar or MP_VIP_AMOUNT,
                    "already_exists": True,
                }

        # Crear nueva preferencia
        external_ref = f"VIP-{attendee.id}-{hash_clean}"
        preference_data = {
            "items": [
                {
                    "title": MP_VIP_TITLE,
                    "unit_price": float(attendee.monto_abonar or MP_VIP_AMOUNT),
                    "quantity": 1,
                    "currency_id": "ARS",
                    "description": f"Entrada VIP para {attendee.nombre} {attendee.apellido}",
                }
            ],
            "payer": {
                "name": attendee.nombre,
                "email": attendee.email or "",
            },
            "back_urls": {
                "success": MP_BACK_URL,
                "pending": MP_BACK_URL,
                "failure": MP_BACK_URL,
            },
            "external_reference": external_ref,
            "notification_url": f"{MP_BACK_URL.rstrip('/')}/api/mp/webhook",
            "auto_return": "approved",
        }

        resp = await mp_request("POST", "/checkout/preferences", json=preference_data)

        if resp.status_code != 201:
            error_text = resp.text
            raise HTTPException(status_code=502, detail=f"Error creando preferencia MP: {error_text}")

        pref_data = resp.json()
        preference_id = pref_data["id"]
        init_point = pref_data.get("init_point")

        # Guardar en la DB
        attendee.mp_preference_id = preference_id
        attendee.monto_abonar = attendee.monto_abonar or MP_VIP_AMOUNT
        await session.commit()

        return {
            "preference_id": preference_id,
            "init_point": init_point,
            "amount": attendee.monto_abonar,
            "already_exists": False,
        }


@router.post("/api/mp/webhook")
async def mp_webhook(request: Request):
    """
    Webhook de Mercado Pago.
    Recibe notificaciones de pago y confirma el pago_confirmado del asistente.
    """
    # Verificar que es un evento de payment
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(content={"status": "ignored"}, status_code=200)

    # Mercado Pago envía: {"action": "...", "data": {"id": <payment_id>}}
    # O también: {"type": "payment", "data": {"id": <payment_id>}}
    action = body.get("action", "")
    data = body.get("data", {})
    payment_id = data.get("id") if isinstance(data, dict) else None

    # Si viene como query param (formato alternativo)
    if not payment_id:
        payment_id = body.get("id")

    if not payment_id:
        return JSONResponse(content={"status": "ignored"}, status_code=200)

    # Fetch payment details from MP
    resp = await mp_request("GET", f"/v1/payments/{payment_id}")
    if resp.status_code != 200:
        return JSONResponse(content={"status": "error", "detail": "Payment not found"}, status_code=404)

    payment_data = resp.json()
    status = payment_data.get("status", "")
    external_ref = payment_data.get("external_reference", "")

    # Solo procesar pagos aprobados
    if status != "approved":
        return JSONResponse(content={"status": "ignored", "payment_status": status}, status_code=200)

    # Extraer attendee_id del external_reference (formato: VIP-{id}-{hash})
    if not external_ref.startswith("VIP-"):
        return JSONResponse(content={"status": "ignored"}, status_code=200)

    parts = external_ref.split("-", 2)
    if len(parts) < 2:
        return JSONResponse(content={"status": "ignored"}, status_code=200)

    try:
        attendee_id = int(parts[1])
    except ValueError:
        return JSONResponse(content={"status": "ignored"}, status_code=200)

    # Actualizar el asistente
    async with async_session() as session:
        stmt = select(Attendee).where(Attendee.id == attendee_id)
        result = await session.execute(stmt)
        attendee = result.scalar_one_or_none()

        if not attendee:
            return JSONResponse(content={"status": "error", "detail": "Attendee not found"}, status_code=404)

        attendee.pago_confirmado = True
        attendee.mp_payment_id = str(payment_id)
        await session.commit()

    return JSONResponse(content={"status": "ok", "attendee_id": attendee_id})


@router.get("/api/mp/payment_status")
async def get_payment_status(hash: str = Query(..., min_length=8, max_length=64)):
    """Consulta el estado de pago de un asistente VIP."""
    hash_clean = hash.strip().upper()

    async with async_session() as session:
        stmt = select(Attendee).where(
            (Attendee.qr_token == hash_clean) | (Attendee.hash_unique == hash_clean)
        )
        result = await session.execute(stmt)
        attendee = result.scalar_one_or_none()

        if not attendee:
            raise HTTPException(status_code=404, detail="Asistente no encontrado")

        return {
            "tipo_acceso": attendee.tipo_acceso,
            "pago_confirmado": attendee.pago_confirmado,
            "mp_preference_id": attendee.mp_preference_id,
            "mp_payment_id": attendee.mp_payment_id,
            "monto_abonar": attendee.monto_abonar,
        }
