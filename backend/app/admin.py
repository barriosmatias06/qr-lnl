"""
Admin dashboard routes.
"""

import io
import base64
from datetime import datetime

import qrcode
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from PIL import Image, ImageDraw, ImageFont
from sqlalchemy import select, func, desc

from app.database import async_session
from app.models import Attendee
from app.auth import require_user, get_current_user, AdminUser

router = APIRouter()


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def _base_url() -> str:
    import os
    domain = os.getenv("DOMAIN", "localhost")
    if domain.startswith("http"):
        return domain
    return f"https://{domain}"


def _make_qr(hash_id: str) -> bytes:
    url = f"{_base_url()}/?id={hash_id}"
    qr = qrcode.QRCode(version=None, error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=10, border=4)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    buf.seek(0)
    return buf.read()


@router.get("/admin", response_class=HTMLResponse)
async def admin_dashboard(request: Request):
    """Panel de administración con estadísticas y listado."""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/admin/login", status_code=302)
    return """<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta name="theme-color" content="#0f172a">
  <title>Admin — Control de Acceso</title>
  <style>
    :root { --bg:#0f172a;--card:#1e293b;--border:#334155;--muted:#64748b;
            --text:#f1f5f9;--green:#22c55e;--orange:#f97316;--red:#ef4444;
            --blue:#3b82f6;--yellow:#eab308; }
    *,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
    body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
         background:var(--bg);color:var(--text);min-height:100dvh}
    .topbar{background:var(--card);border-bottom:1px solid var(--border);
            padding:16px 24px;display:flex;align-items:center;justify-content:space-between}
    .topbar h1{font-size:1.2rem;font-weight:700}
    .topbar .badge{background:var(--blue);color:#fff;padding:4px 12px;border-radius:20px;font-size:.75rem}
    .container{max-width:1200px;margin:0 auto;padding:24px}
    .stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:16px;margin-bottom:28px}
    .stat{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:20px;text-align:center}
    .stat-num{font-size:2.2rem;font-weight:800;line-height:1}
    .stat-label{font-size:.75rem;text-transform:uppercase;letter-spacing:.08em;color:var(--muted);margin-top:6px}
    .s-total .stat-num{color:var(--blue)}
    .s-ingresaron .stat-num{color:var(--green)}
    .s-pendientes .stat-num{color:var(--orange)}
    .s-lugares .stat-num{color:var(--yellow)}
    .search-bar{margin-bottom:20px;display:flex;gap:12px}
    .search-bar input{flex:1;background:var(--card);border:1px solid var(--border);
                      border-radius:10px;color:var(--text);padding:12px 16px;font-size:.95rem}
    .search-bar input:focus{outline:none;border-color:var(--blue)}
    .search-bar select{background:var(--card);border:1px solid var(--border);border-radius:10px;
                       color:var(--text);padding:12px;font-size:.9rem}
    table{width:100%;border-collapse:collapse;background:var(--card);border-radius:12px;overflow:hidden}
    th{background:#1e293b;color:var(--muted);font-size:.7rem;text-transform:uppercase;letter-spacing:.08em;
       padding:12px 16px;text-align:left;border-bottom:1px solid var(--border)}
    td{padding:12px 16px;border-bottom:1px solid var(--border);font-size:.85rem}
    tr:last-child td{border-bottom:none}
    tr:hover td{background:#1e293b}
    .status{padding:4px 10px;border-radius:20px;font-size:.75rem;font-weight:600}
    .status.in{background:rgba(34,197,94,.15);color:var(--green)}
    .status.pending{background:rgba(249,115,22,.15);color:var(--orange)}
    .qr-mini{cursor:pointer;opacity:.6;transition:opacity .15s}
    .qr-mini:hover{opacity:1}
    .loading{text-align:center;padding:40px;color:var(--muted)}
    .modal{position:fixed;inset:0;background:rgba(0,0,0,.7);display:none;align-items:center;
           justify-content:center;z-index:100}
    .modal.open{display:flex}
    .modal-content{background:var(--card);border-radius:16px;padding:24px;text-align:center;max-width:300px}
    .modal-content img{border-radius:8px;margin-bottom:12px}
    .modal-content button{background:var(--blue);color:#fff;border:none;border-radius:8px;
                          padding:10px 20px;font-weight:600;cursor:pointer}
    .no-data{text-align:center;padding:60px 20px;color:var(--muted)}
  </style>
</head>
<body>
  <div class="topbar">
    <h1>🎫 Panel de Administración</h1>
    <span class="badge" id="last-update">—</span>
  </div>
  <div class="container">
    <div class="stats">
      <div class="stat s-total">
        <div class="stat-num" id="s-total">—</div>
        <div class="stat-label">Registrados</div>
      </div>
      <div class="stat s-ingresaron">
        <div class="stat-num" id="s-ingresaron">—</div>
        <div class="stat-label">Ingresaron</div>
      </div>
      <div class="stat s-pendientes">
        <div class="stat-num" id="s-pendientes">—</div>
        <div class="stat-label">Pendientes</div>
      </div>
      <div class="stat s-lugares">
        <div class="stat-num" id="s-lugares">—</div>
        <div class="stat-label">Lugares libres</div>
      </div>
    </div>

    <div class="search-bar">
      <input type="text" id="search" placeholder="Buscar por nombre o email..." autocomplete="off">
      <select id="filter-status">
        <option value="all">Todos</option>
        <option value="in">Ingresaron</option>
        <option value="pending">Pendientes</option>
      </select>
    </div>

    <div id="table-wrap">
      <div class="loading" id="loading">Cargando datos...</div>
      <table id="table" style="display:none">
        <thead>
          <tr>
            <th>QR</th>
            <th>Nombre</th>
            <th>Email</th>
            <th>Estado</th>
            <th>Ingreso</th>
          </tr>
        </thead>
        <tbody id="tbody"></tbody>
      </table>
      <div class="no-data" id="no-data" style="display:none">No se encontraron resultados</div>
    </div>
  </div>

  <!-- QR Modal -->
  <div class="modal" id="qr-modal" onclick="closeModal(event)">
    <div class="modal-content">
      <img id="modal-qr-img" src="" alt="QR" style="max-width:220px">
      <p id="modal-name" style="font-weight:600;margin-bottom:12px"></p>
      <button onclick="document.getElementById('qr-modal').classList.remove('open')">Cerrar</button>
    </div>
  </div>

<script>
  let ALL_DATA = [];
  const CAPACITY = 1800;

  async function loadData() {
    const res = await fetch('/api/admin/data');
    const json = await res.json();
    ALL_DATA = json.attendees;
    renderStats(json);
    renderTable(ALL_DATA);
    document.getElementById('last-update').textContent = 'Actualizado: ' + new Date().toLocaleTimeString();
  }

  function renderStats(json) {
    const total = json.total;
    const ingresaron = json.ingresaron;
    document.getElementById('s-total').textContent = total;
    document.getElementById('s-ingresaron').textContent = ingresaron;
    document.getElementById('s-pendientes').textContent = total - ingresaron;
    document.getElementById('s-lugares').textContent = Math.max(0, CAPACITY - ingresaron);
  }

  function renderTable(data) {
    const tbody = document.getElementById('tbody');
    const table = document.getElementById('table');
    const loading = document.getElementById('loading');
    const noData = document.getElementById('no-data');
    loading.style.display = 'none';

    if (!data.length) { noData.style.display = 'block'; table.style.display = 'none'; return; }
    noData.style.display = 'none';
    table.style.display = 'table';

    tbody.innerHTML = data.map(a => {
      const status = a.estado_ingreso
        ? '<span class="status in">✓ Ingresó</span>'
        : '<span class="status pending">Pendiente</span>';
      const fecha = a.fecha_ingreso || '—';
      return `<tr>
        <td><span class="qr-mini" onclick="showQR('${a.hash_unique}','${a.nombre.replace(/'/g,"\\'")}')">📱</span></td>
        <td>${esc(a.nombre)}</td>
        <td>${esc(a.email)}</td>
        <td>${status}</td>
        <td>${fecha}</td>
      </tr>`;
    }).join('');
  }

  function showQR(hash, name) {
    fetch(`/admin/qr/${hash}`)
      .then(r => r.blob())
      .then(blob => {
        document.getElementById('modal-qr-img').src = URL.createObjectURL(blob);
        document.getElementById('modal-name').textContent = name;
        document.getElementById('qr-modal').classList.add('open');
      });
  }

  function closeModal(e) { if (e.target === document.getElementById('qr-modal')) document.getElementById('qr-modal').classList.remove('open'); }

  function esc(s) { const d = document.createElement('div'); d.textContent = s; return d.innerHTML; }

  // Search + filter
  document.getElementById('search').addEventListener('input', applyFilters);
  document.getElementById('filter-status').addEventListener('change', applyFilters);

  function applyFilters() {
    const q = document.getElementById('search').value.toLowerCase();
    const f = document.getElementById('filter-status').value;
    let data = ALL_DATA;
    if (q) data = data.filter(a => a.nombre.toLowerCase().includes(q) || a.email.toLowerCase().includes(q));
    if (f === 'in') data = data.filter(a => a.estado_ingreso);
    if (f === 'pending') data = data.filter(a => !a.estado_ingreso);
    renderTable(data);
  }

  // Auto refresh cada 30s
  loadData();
  setInterval(loadData, 30000);
</script>
</body>
</html>"""


@router.get("/api/admin/data")
async def admin_data(user: AdminUser = Depends(require_user)):
    """JSON con todos los asistentes y estadísticas."""
    async with async_session() as session:
        total = (await session.execute(select(func.count(Attendee.id)))).scalar() or 0
        ingresaron = (await session.execute(
            select(func.count(Attendee.id)).where(Attendee.estado_ingreso.is_(True))
        )).scalar() or 0

        stmt = select(Attendee).order_by(desc(Attendee.id))
        result = await session.execute(stmt)
        attendees = result.scalars().all()

    return {
        "total": total,
        "ingresaron": ingresaron,
        "pendientes": total - ingresaron,
        "attendees": [
            {
                "id": a.id,
                "nombre": a.nombre,
                "email": a.email,
                "hash_unique": a.hash_unique,
                "estado_ingreso": a.estado_ingreso,
                "fecha_ingreso": a.fecha_ingreso.strftime("%d/%m/%Y %H:%M:%S") if a.fecha_ingreso else None,
            }
            for a in attendees
        ],
    }


@router.get("/admin/qr/{hash_id}")
async def admin_qr(hash_id: str, user: AdminUser = Depends(require_user)):
    """Genera QR para vista previa en admin."""
    async with async_session() as session:
        stmt = select(Attendee).where(Attendee.hash_unique == hash_id.upper())
        result = await session.execute(stmt)
        attendee = result.scalar_one_or_none()

    if not attendee:
        return Response(content="No encontrado", status_code=404, media_type="text/plain")

    qr_bytes = _make_qr(hash_id)
    return Response(content=qr_bytes, media_type="image/png")
