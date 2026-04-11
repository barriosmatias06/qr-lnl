"""
Página de registro de asistentes.
GET  /register  → formulario
POST /register  → crea asistente + genera QR + muestra resultado
"""

import io
import os
import base64
import uuid
from html import escape as _html_escape

import qrcode
from fastapi import APIRouter, Form, Response
from fastapi.responses import HTMLResponse
from PIL import Image, ImageDraw, ImageFont
from sqlalchemy import select

from app.database import async_session
from app.models import Attendee

router = APIRouter()


def _base_url() -> str:
    domain = os.getenv("DOMAIN", "localhost")
    if domain.startswith("http"):
        return domain
    return f"https://{domain}"


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def _make_qr_with_name(url: str, name: str) -> bytes:
    qr = qrcode.QRCode(version=None, error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=10, border=4)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white").convert("RGB")

    w, h = img.size
    label_h = 32
    canvas = Image.new("RGB", (w, h + label_h), "white")
    canvas.paste(img, (0, 0))
    draw = ImageDraw.Draw(canvas)
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 16)
    except (OSError, IOError):
        font = ImageFont.load_default()
    bbox = draw.textbbox((0, 0), name, font=font)
    text_w = bbox[2] - bbox[0]
    x = max(0, (w - text_w) // 2)
    draw.text((x, h + 8), name, fill="black", font=font)

    buf = io.BytesIO()
    canvas.save(buf, format="PNG", optimize=True)
    buf.seek(0)
    return buf.read()


@router.get("/register", response_class=HTMLResponse)
async def register_page():
    """Formulario de registro para invitados."""
    return """
<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta name="theme-color" content="#0f172a">
  <title>Registro — Control de Acceso</title>
  <style>
    :root {
      --bg: #0f172a; --card: #1e293b; --border: #334155;
      --muted: #64748b; --text: #f1f5f9; --blue: #3b82f6;
      --green: #22c55e;
    }
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      background: var(--bg); color: var(--text);
      min-height: 100dvh; display: flex; align-items: flex-start; justify-content: center; padding: 20px;
    }
    .card {
      background: var(--card); border: 1px solid var(--border);
      border-radius: 16px; padding: 0; width: 100%; max-width: 420px; overflow: hidden;
    }
    .flyer {
      width: 100%;
      display: block;
      border-radius: 16px 16px 0 0;
    }
    .card-body { padding: 28px 32px 32px; }
    h1 { font-size: 1.3rem; text-align: center; margin-bottom: 4px; }
    .subtitle { text-align: center; color: var(--muted); margin-bottom: 24px; font-size: 0.85rem; }
    label { display: block; font-size: 0.85rem; color: #94a3b8; margin-bottom: 6px; font-weight: 500; }
    input {
      width: 100%; background: #0f172a; border: 1px solid #475569;
      border-radius: 10px; color: var(--text); padding: 12px 14px;
      font-size: 1rem; margin-bottom: 18px;
    }
    input:focus { outline: none; border-color: var(--blue); box-shadow: 0 0 0 3px rgba(59,130,246,0.2); }
    .btn {
      width: 100%; background: var(--blue); color: #fff;
      border: none; border-radius: 10px; padding: 14px;
      font-size: 1rem; font-weight: 700; cursor: pointer;
      transition: opacity 0.15s;
    }
    .btn:hover { opacity: 0.9; }
    .btn:active { opacity: 0.85; }
    .footer { text-align: center; margin-top: 16px; font-size: 0.75rem; color: var(--muted); }
  </style>
</head>
<body>
  <div class="card">
    <img class="flyer" src="/frontend/flyer.png" alt="Flyer del evento">
    <div class="card-body">
      <h1>Registro al Evento</h1>
      <p class="subtitle">Completá tus datos para recibir tu código QR de acceso</p>
      <form method="POST" action="/register">
        <label for="nombre">Nombre completo</label>
        <input type="text" id="nombre" name="nombre" required placeholder="Ej: Ana García" autocomplete="name">
        <label for="email">Email</label>
        <input type="email" id="email" name="email" required placeholder="Ej: ana@email.com" autocomplete="email">
        <button type="submit" class="btn">Obtener mi QR →</button>
      </form>
      <p class="footer">El QR es único y personal. No lo compartas.</p>
    </div>
  </div>
</body>
</html>
"""


@router.post("/register", response_class=HTMLResponse)
async def register_submit(
    nombre: str = Form(...),
    email: str = Form(...),
):
    """Crea asistente en DB y muestra su QR con datos."""
    hash_unique = uuid.uuid4().hex[:16].upper()

    async with async_session() as session:
        attendee = Attendee(
            nombre=nombre.strip(),
            email=email.strip().lower(),
            hash_unique=hash_unique,
            estado_ingreso=False,
            fecha_ingreso=None,
        )
        session.add(attendee)
        await session.commit()

    # Generar QR con nombre debajo
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=4,
    )
    qr.add_data(f"{_base_url()}/?id={hash_unique}")
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white").convert("RGB")

    # Agregar nombre debajo
    w, h = img.size
    label_h = 32
    canvas = Image.new("RGB", (w, h + label_h), "white")
    canvas.paste(img, (0, 0))
    draw = ImageDraw.Draw(canvas)

    # Intentar fuente grande, fallback a default
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 16)
    except (OSError, IOError):
        font = ImageFont.load_default()

    bbox = draw.textbbox((0, 0), nombre, font=font)
    text_w = bbox[2] - bbox[0]
    x = max(0, (w - text_w) // 2)
    draw.text((x, h + 8), nombre, fill="black", font=font)

    buf = io.BytesIO()
    canvas.save(buf, format="PNG", optimize=True)
    buf.seek(0)
    qr_bytes = buf.read()

    qr_url = f"{_base_url()}/?id={hash_unique}"

    return f"""
<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta name="theme-color" content="#0f172a">
  <title>Tu QR — Control de Acceso</title>
  <style>
    :root {{
      --bg: #0f172a; --card: #1e293b; --border: #334155;
      --muted: #64748b; --text: #f1f5f9; --green: #22c55e; --blue: #3b82f6;
    }}
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      background: var(--bg); color: var(--text);
      min-height: 100dvh; display: flex; align-items: center; justify-content: center; padding: 20px;
    }}
    .card {{
      background: var(--card); border: 1px solid var(--border);
      border-radius: 16px; padding: 32px; width: 100%; max-width: 420px; text-align: center;
    }}
    .check {{ font-size: 3rem; margin-bottom: 8px; }}
    h1 {{ font-size: 1.4rem; margin-bottom: 4px; color: var(--green); }}
    .name {{ font-size: 1.1rem; margin-bottom: 16px; color: var(--muted); }}
    .qr-img {{ max-width: 260px; border-radius: 12px; margin: 0 auto 20px; display: block; border: 3px solid var(--border); }}
    .actions {{ display: flex; gap: 10px; flex-wrap: wrap; justify-content: center; }}
    .btn {{
      flex: 1; min-width: 140px; padding: 12px 16px; border-radius: 10px;
      font-size: 0.9rem; font-weight: 600; text-decoration: none; cursor: pointer;
      border: none; display: inline-block; text-align: center;
    }}
    .btn-primary {{ background: var(--blue); color: #fff; }}
    .btn-secondary {{ background: transparent; color: var(--text); border: 1px solid var(--border); }}
    .note {{ margin-top: 20px; font-size: 0.8rem; color: var(--muted); line-height: 1.5; }}
    .hash {{ margin-top: 12px; font-size: 0.7rem; color: #475569; font-family: monospace; word-break: break-all; }}
  </style>
</head>
<body>
  <div class="card">
    <div class="check">✅</div>
    <h1>¡Registro exitoso!</h1>
    <p class="name">{_html_escape(nombre)}</p>
    <img class="qr-img" src="data:image/png;base64,{_b64(qr_bytes)}" alt="QR Code">
    <div class="actions">
      <a href="/qr-download/{hash_unique}" class="btn btn-primary">⬇ Descargar QR</a>
      <a href="/register" class="btn btn-secondary">Registrar otro</a>
    </div>
    <p class="note">
      Este QR es tu entrada al evento. <strong>No lo compartas.</strong><br>
      Podés descargarlo o hacer captura de pantalla.
    </p>
    <div class="hash">ID: {hash_unique}</div>
  </div>
</body>
</html>
"""


@router.get("/qr-download/{hash_id}")
async def download_qr(hash_id: str):
    """Descarga el QR de un asistente como archivo PNG."""
    async with async_session() as session:
        stmt = select(Attendee).where(Attendee.hash_unique == hash_id.upper())
        result = await session.execute(stmt)
        attendee = result.scalar_one_or_none()

    if not attendee:
        return Response(content="QR no encontrado", status_code=404, media_type="text/plain")

    qr = qrcode.QRCode(version=None, error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=10, border=4)
    qr.add_data(f"{_base_url()}/?id={hash_id}")
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white").convert("RGB")

    w, h = img.size
    label_h = 32
    canvas = Image.new("RGB", (w, h + label_h), "white")
    canvas.paste(img, (0, 0))
    draw = ImageDraw.Draw(canvas)
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 16)
    except (OSError, IOError):
        font = ImageFont.load_default()
    bbox = draw.textbbox((0, 0), attendee.nombre, font=font)
    text_w = bbox[2] - bbox[0]
    x = max(0, (w - text_w) // 2)
    draw.text((x, h + 8), attendee.nombre, fill="black", font=font)

    buf = io.BytesIO()
    canvas.save(buf, format="PNG", optimize=True)
    buf.seek(0)

    safe_name = attendee.nombre.replace(" ", "_").replace("/", "-")[:40]
    filename = f"{safe_name}_{hash_id}.png"

    return Response(
        content=buf.read(),
        media_type="image/png",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ── Helpers ──────────────────────────────────────────────────────────────

import base64
from html import escape as _html_escape


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def _base_url() -> str:
    """Base URL from env var or default."""
    domain = os.getenv("DOMAIN", "localhost")
    return f"https://{domain}"
