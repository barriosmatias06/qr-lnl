"""
Autenticación para el panel de administración.
Usa JWT con python-jose y bcrypt con passlib.
"""

import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
from fastapi import APIRouter, Depends, HTTPException, Request, Cookie
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from jose import jwt, JWTError
from pydantic import BaseModel
from sqlalchemy import select

from app.database import async_session
from app.models import AdminUser

router = APIRouter()

# ── Configuración ──────────────────────────────────────────────────────────

SECRET_KEY = os.getenv("ADMIN_JWT_SECRET", "change-me-to-a-random-secret-key")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 8  # 8 horas


# ── Helpers ────────────────────────────────────────────────────────────────

def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


async def get_current_user(request: Request) -> Optional[AdminUser]:
    """Obtener usuario desde la cookie JWT."""
    token = request.cookies.get("admin_token")
    if not token:
        return None
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            return None
    except JWTError:
        return None

    async with async_session() as session:
        result = await session.execute(select(AdminUser).where(AdminUser.username == username))
        user = result.scalar_one_or_none()
        if user and user.activo:
            return user
    return None


async def require_user(request: Request) -> AdminUser:
    """Dependency: requiere autenticación."""
    user = await get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="No autenticado")
    return user


async def require_super_admin(request: Request) -> AdminUser:
    """Dependency: requiere usuario con rol super_admin."""
    user = await get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="No autenticado")
    if user.role != "super_admin":
        raise HTTPException(status_code=403, detail="Acceso denegado: se requiere rol de administrador")
    return user


# ── Schemas ────────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    username: str
    password: str


# ── Routes ─────────────────────────────────────────────────────────────────

@router.get("/admin/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """Página de login."""
    user = await get_current_user(request)
    if user:
        return RedirectResponse(url="/admin", status_code=302)

    return """<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta name="theme-color" content="#0f172a">
  <title>Login Admin — Control de Acceso</title>
  <style>
    :root{--bg:#0f172a;--card:#1e293b;--border:#334155;--muted:#64748b;
          --text:#f1f5f9;--blue:#3b82f6;--red:#ef4444}
    *,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
    body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
         background:var(--bg);color:var(--text);min-height:100dvh;
         display:flex;align-items:center;justify-content:center;padding:20px}
    .card{background:var(--card);border:1px solid var(--border);border-radius:16px;
          padding:40px;width:100%;max-width:400px}
    h1{font-size:1.5rem;font-weight:800;margin-bottom:8px;text-align:center}
    .subtitle{color:var(--muted);text-align:center;margin-bottom:32px;font-size:.9rem}
    label{display:block;font-size:.8rem;font-weight:600;color:var(--muted);margin-bottom:6px}
    input{width:100%;background:#0f172a;border:1px solid var(--border);border-radius:10px;
          color:var(--text);padding:12px 16px;font-size:.95rem;margin-bottom:16px}
    input:focus{outline:none;border-color:var(--blue)}
    .btn{width:100%;background:var(--blue);color:#fff;border:none;border-radius:10px;
         padding:14px;font-size:1rem;font-weight:700;cursor:pointer;margin-top:8px;
         transition:opacity .15s}
    .btn:active{opacity:.8}
    .error{color:var(--red);font-size:.85rem;text-align:center;margin-top:12px;display:none}
    .lock-icon{font-size:3rem;text-align:center;margin-bottom:16px}
  </style>
</head>
<body>
  <div class="card">
    <div class="lock-icon">🔒</div>
    <h1>Panel de Administración</h1>
    <p class="subtitle">Ingresá tus credenciales para continuar</p>
    <form id="login-form" onsubmit="doLogin(event)">
      <label for="username">Usuario</label>
      <input type="text" id="username" name="username" required autocomplete="username" placeholder="4dm1n01">
      <label for="password">Contraseña</label>
      <input type="password" id="password" name="password" required autocomplete="current-password" placeholder="••••••••">
      <button class="btn" type="submit">Ingresar</button>
      <div class="error" id="error-msg">Usuario o contraseña incorrectos</div>
    </form>
  </div>
<script>
  async function doLogin(e) {
    e.preventDefault();
    const btn = document.querySelector('.btn');
    const err = document.getElementById('error-msg');
    btn.textContent = 'Verificando...';
    btn.disabled = true;
    err.style.display = 'none';

    const body = {
      username: document.getElementById('username').value,
      password: document.getElementById('password').value
    };

    try {
      const res = await fetch('/admin/api/login', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(body)
      });
      if (res.ok) {
        window.location.href = '/admin';
      } else {
        const d = await res.json();
        err.textContent = d.detail || 'Error de autenticación';
        err.style.display = 'block';
      }
    } catch(e) {
      err.textContent = 'Error de conexión';
      err.style.display = 'block';
    }
    btn.textContent = 'Ingresar';
    btn.disabled = false;
  }
</script>
</body>
</html>"""


@router.post("/admin/api/login")
async def api_login(body: LoginRequest):
    """Endpoint para autenticar y devolver JWT en cookie."""
    async with async_session() as session:
        result = await session.execute(select(AdminUser).where(AdminUser.username == body.username))
        user = result.scalar_one_or_none()

    if not user or not user.activo or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Usuario o contraseña incorrectos")

    token = create_access_token(data={"sub": user.username, "role": user.role})
    response = JSONResponse(content={"success": True})
    response.set_cookie(
        key="admin_token",
        value=token,
        httponly=True,
        samesite="lax",
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        path="/",
    )
    return response


@router.post("/admin/api/logout")
async def api_logout():
    """Cerrar sesión: borrar cookie."""
    response = JSONResponse(content={"success": True})
    response.delete_cookie(key="admin_token", path="/")
    return response


@router.get("/admin/api/me")
async def api_me(user: AdminUser = Depends(require_user)):
    """Devuelve info del usuario logueado."""
    return {"username": user.username, "role": user.role, "activo": user.activo}
