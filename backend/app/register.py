"""
Página de registro de asistentes con código de invitación.
GET  /register  → formulario
POST /register  → valida código, crea asistente + genera QR + muestra resultado
"""

import io
import os
import base64
import uuid
from datetime import datetime, timezone
from html import escape as _html_escape

import qrcode
from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse
from PIL import Image, ImageDraw, ImageFont
from sqlalchemy import select

from app.database import async_session
from app.models import Attendee, InvitationCode

router = APIRouter()


def _base_url() -> str:
    domain = os.getenv("DOMAIN", "localhost")
    if domain.startswith("http"):
        return domain
    return f"https://{domain}"


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def _make_qr_with_name(url: str, name: str) -> bytes:
    """Genera QR con nombre debajo."""
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
    """Formulario de registro para invitados con código de invitación."""
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
      --green: #22c55e; --red: #ef4444;
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
    .error-msg { color: var(--red); font-size: 0.85rem; text-align: center; margin-top: 12px; display: none; }
    .step { display: none; }
    .step.active { display: block; }
    .code-input { font-family: monospace; font-size: 1.1rem; letter-spacing: 0.1em; text-transform: uppercase; text-align: center; }
  </style>
</head>
<body>
  <div class="card">
    <img class="flyer" src="/frontend/flyer.png" alt="Flyer del evento">
    <div class="card-body">
      <h1>Registro al Evento</h1>
      <p class="subtitle">Ingresá tu código de invitación para registrarte</p>

      <!-- Step 1: Invitation Code -->
      <div class="step active" id="step-code">
        <form onsubmit="validateCode(event)">
          <label for="invitation_code">Código de Invitación</label>
          <input type="text" id="invitation_code" name="invitation_code" required
                 class="code-input" placeholder="INV-XXXXXXXX" autocomplete="off" spellcheck="false">
          <button type="submit" class="btn" id="btn-validate">Validar Código →</button>
        </form>
        <div class="error-msg" id="error-code"></div>
      </div>

      <!-- Step 2: Personal Data -->
      <div class="step" id="step-data">
        <form method="POST" action="/register" onsubmit="submitForm(event)">
          <input type="hidden" id="invitation_code_hidden" name="invitation_code">
          <label for="nombre">Nombre</label>
          <input type="text" id="nombre" name="nombre" required placeholder="Ej: Ana">
          <label for="apellido">Apellido</label>
          <input type="text" id="apellido" name="apellido" required placeholder="Ej: García">
          <label for="nro_documento">N° Documento</label>
          <input type="text" id="nro_documento" name="nro_documento" required placeholder="Ej: 30123456">
          <label for="invitado_por">Nombre de quien te invitó</label>
          <input type="text" id="invitado_por" name="invitado_por" required placeholder="Ej: Carlos López">
          <button type="submit" class="btn" id="btn-submit">Obtener mi QR →</button>
        </form>
        <div class="error-msg" id="error-data"></div>
      </div>
    </div>
  </div>

<script>
  async function validateCode(e) {
    e.preventDefault();
    const code = document.getElementById('invitation_code').value.trim().toUpperCase();
    const errDiv = document.getElementById('error-code');
    const btn = document.getElementById('btn-validate');

    if (!code) {
      errDiv.textContent = 'Ingresá un código de invitación';
      errDiv.style.display = 'block';
      return;
    }

    btn.textContent = 'Validando...';
    btn.disabled = true;
    errDiv.style.display = 'none';

    try {
      const res = await fetch('/api/register/validate-code?code=' + encodeURIComponent(code));
      const json = await res.json();

      if (!res.ok || !json.valid) {
        errDiv.textContent = json.message || 'Código inválido o ya utilizado';
        errDiv.style.display = 'block';
        btn.textContent = 'Validar Código →';
        btn.disabled = false;
        return;
      }

      // Code valid - show step 2
      document.getElementById('step-code').classList.remove('active');
      document.getElementById('step-data').classList.add('active');
      document.getElementById('invitation_code_hidden').value = code;
      document.querySelector('h1').textContent = 'Completá tus datos';
      document.querySelector('.subtitle').textContent = '';
    } catch (err) {
      errDiv.textContent = 'Error de conexión. Intentá de nuevo.';
      errDiv.style.display = 'block';
      btn.textContent = 'Validar Código →';
      btn.disabled = false;
    }
  }

  async function submitForm(e) {
    e.preventDefault();
    const btn = document.getElementById('btn-submit');
    const errDiv = document.getElementById('error-data');
    btn.textContent = 'Registrando...';
    btn.disabled = true;
    errDiv.style.display = 'none';

    const formData = new FormData(e.target);

    try {
      const res = await fetch('/register', {
        method: 'POST',
        body: formData,
      });

      if (!res.ok) {
        const json = await res.json().catch(() => ({message: 'Error en el registro'}));
        errDiv.textContent = json.message || 'Error en el registro';
        errDiv.style.display = 'block';
        btn.textContent = 'Obtener mi QR →';
        btn.disabled = false;
        return;
      }

      // Success - show QR page
      const html = await res.text();
      document.open();
      document.write(html);
      document.close();
    } catch (err) {
      errDiv.textContent = 'Error de conexión. Intentá de nuevo.';
      errDiv.style.display = 'block';
      btn.textContent = 'Obtener mi QR →';
      btn.disabled = false;
    }
  }
</script>
</body>
</html>
"""


@router.get("/api/register/validate-code")
async def validate_invitation_code(code: str):
    """Valida que un código de invitación exista y no haya sido usado."""
    code_clean = code.strip().upper()

    async with async_session() as session:
        stmt = select(InvitationCode).where(
            (InvitationCode.code == code_clean) & (InvitationCode.used.is_(False))
        )
        result = await session.execute(stmt)
        invitation = result.scalar_one_or_none()

        if not invitation:
            return {"valid": False, "message": "Código inválido o ya utilizado"}

    return {"valid": True, "message": "Código válido"}


@router.post("/register", response_class=HTMLResponse)
async def register_submit(
    invitation_code: str = Form(...),
    nombre: str = Form(...),
    apellido: str = Form(...),
    nro_documento: str = Form(...),
    invitado_por: str = Form(...),
):
    """Valida código, crea asistente en DB y muestra su QR."""
    code_clean = invitation_code.strip().upper()

    async with async_session() as session:
        # Validate invitation code
        stmt = select(InvitationCode).where(
            (InvitationCode.code == code_clean) & (InvitationCode.used.is_(False))
        )
        result = await session.execute(stmt)
        invitation = result.scalar_one_or_none()

        if not invitation:
            return _error_page("Código de invitación inválido o ya utilizado")

        # Generate secure qr_token
        qr_token = f"QR-{uuid.uuid4().hex[:24].upper()}"

        # Create attendee
        attendee = Attendee(
            nombre=nombre.strip(),
            apellido=apellido.strip(),
            nro_documento=nro_documento.strip(),
            email="",
            invitado_por=invitado_por.strip(),
            qr_token=qr_token,
            hash_unique=qr_token,  # Keep for backwards compatibility
            estado_ingreso=False,
            fecha_ingreso=None,
        )
        session.add(attendee)
        await session.flush()  # Get attendee.id

        # Mark invitation as used
        invitation.used = True
        invitation.usado_en = datetime.now(timezone.utc)
        invitation.attendee_id = attendee.id
        await session.commit()

    # Generate QR with name
    full_name = f"{nombre} {apellido}"
    qr_bytes = _make_qr_with_name(f"{_base_url()}/?id={qr_token}", full_name)

    qr_url = f"{_base_url()}/?id={qr_token}"

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
    <p class="name">{_html_escape(full_name)}</p>
    <img class="qr-img" src="data:image/png;base64,{_b64(qr_bytes)}" alt="QR Code">
    <div class="actions">
      <a href="/qr-download/{qr_token}" class="btn btn-primary">⬇ Descargar QR</a>
      <a href="/register" class="btn btn-secondary">Registrar otro</a>
    </div>
    <p class="note">
      Este QR es tu entrada al evento. <strong>No lo compartas.</strong><br>
      Podés descargarlo o hacer captura de pantalla.
    </p>
    <div class="hash">Token: {qr_token}</div>
  </div>
</body>
</html>
"""


@router.get("/qr-download/{token_id}")
async def download_qr(token_id: str):
    """Descarga el QR de un asistente como archivo PNG."""
    async with async_session() as session:
        stmt = select(Attendee).where(
            (Attendee.qr_token == token_id.upper()) | (Attendee.hash_unique == token_id.upper())
        )
        result = await session.execute(stmt)
        attendee = result.scalar_one_or_none()

    if not attendee:
        return _error_response("QR no encontrado", 404)

    full_name = f"{attendee.nombre} {attendee.apellido}".strip()
    qr_bytes = _make_qr_with_name(f"{_base_url()}/?id={attendee.qr_token}", full_name)

    safe_name = full_name.replace(" ", "_").replace("/", "-")[:40]
    filename = f"{safe_name}_{attendee.qr_token}.png"

    from fastapi.responses import Response
    return Response(
        content=qr_bytes,
        media_type="image/png",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ── Helpers ──────────────────────────────────────────────────────────────

def _error_page(message: str) -> str:
    """Muestra página de error."""
    return f"""
<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta name="theme-color" content="#0f172a">
  <title>Error — Control de Acceso</title>
  <style>
    :root {{
      --bg: #0f172a; --card: #1e293b; --border: #334155;
      --muted: #64748b; --text: #f1f5f9; --red: #ef4444; --blue: #3b82f6;
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
    .icon {{ font-size: 3rem; margin-bottom: 8px; }}
    h1 {{ font-size: 1.4rem; margin-bottom: 12px; color: var(--red); }}
    .msg {{ color: var(--muted); margin-bottom: 24px; }}
    .btn {{
      background: var(--blue); color: #fff; border: none; border-radius: 10px; padding: 14px 24px;
      font-size: 1rem; font-weight: 600; cursor: pointer; text-decoration: none; display: inline-block;
    }}
  </style>
</head>
<body>
  <div class="card">
    <div class="icon">⚠️</div>
    <h1>Error en el Registro</h1>
    <p class="msg">{_html_escape(message)}</p>
    <a href="/register" class="btn">Volver al Registro</a>
  </div>
</body>
</html>
"""


def _error_response(message: str, status_code: int = 400):
    """Retorna Response de error."""
    from fastapi.responses import Response
    return Response(content=_error_page(message), status_code=status_code, media_type="text/html")
