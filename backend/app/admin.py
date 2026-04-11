"""
Admin dashboard routes.
"""

import io
import base64
import random
import string
from datetime import datetime

import qrcode
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from PIL import Image, ImageDraw, ImageFont
from sqlalchemy import select, func, desc

from app.database import async_session
from app.models import Attendee, InvitationCode
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


def _generate_invitation_code() -> str:
    """Genera un código de invitación tipo INV-XXXXX."""
    chars = string.ascii_uppercase + string.digits
    random_part = ''.join(random.choices(chars, k=8))
    return f"INV-{random_part}"


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
    .tabs{display:flex;gap:0;background:var(--card);border-bottom:1px solid var(--border)}
    .tab{padding:12px 24px;cursor:pointer;font-size:.9rem;font-weight:600;color:var(--muted);
         border-bottom:2px solid transparent;transition:color .15s,border-color .15s}
    .tab:hover{color:var(--text)}
    .tab.active{color:var(--blue);border-bottom-color:var(--blue)}
    .container{max-width:1200px;margin:0 auto;padding:24px}
    .tab-content{display:none}
    .tab-content.active{display:block}
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
    .status.used{background:rgba(239,68,68,.15);color:var(--red)}
    .status.pending{background:rgba(249,115,22,.15);color:var(--orange)}
    .status.unused{background:rgba(34,197,94,.15);color:var(--green)}
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
    .inv-toolbar{display:flex;gap:12px;margin-bottom:20px;align-items:center;flex-wrap:wrap}
    .btn{background:var(--blue);color:#fff;border:none;border-radius:10px;padding:10px 18px;
         font-size:.9rem;font-weight:600;cursor:pointer;transition:opacity .15s}
    .btn:hover{opacity:.9}
    .btn-sm{padding:6px 14px;font-size:.8rem;border-radius:8px}
    .btn-danger{background:var(--red)}
    .btn-ghost{background:transparent;color:var(--text);border:1px solid var(--border)}
    .btn-ghost:hover{border-color:var(--blue)}
    .code-text{font-family:monospace;font-size:1.05rem;font-weight:700;letter-spacing:.05em}
    .inv-stats{display:flex;gap:20px;margin-bottom:20px}
    .inv-stat{display:flex;align-items:center;gap:6px;font-size:.9rem}
    .inv-stat-num{font-weight:700;font-size:1.1rem}
    .inv-stat-label{color:var(--muted);font-size:.8rem}
    .copy-btn{cursor:pointer;opacity:.7;transition:opacity .15s}
    .copy-btn:hover{opacity:1}
    .toast{position:fixed;bottom:20px;right:20px;background:var(--green);color:#fff;
           padding:12px 20px;border-radius:10px;font-size:.9rem;font-weight:600;
           opacity:0;transition:opacity .2s;z-index:200;pointer-events:none}
    .toast.show{opacity:1}
  </style>
</head>
<body>
  <div class="topbar">
    <h1>🎫 Panel de Administración</h1>
    <span class="badge" id="last-update">—</span>
  </div>
  <div class="tabs">
    <div class="tab active" data-tab="attendees" onclick="switchTab('attendees')">👥 Asistentes</div>
    <div class="tab" data-tab="invitations" onclick="switchTab('invitations')">🎟️ Códigos Invitación</div>
  </div>

  <!-- TAB: Asistentes -->
  <div class="tab-content active" id="tab-attendees">
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
        <input type="text" id="search" placeholder="Buscar por nombre, apellido o documento..." autocomplete="off">
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
              <th>Apellido</th>
              <th>Documento</th>
              <th>Invitado por</th>
              <th>Estado</th>
              <th>Ingreso</th>
            </tr>
          </thead>
          <tbody id="tbody"></tbody>
        </table>
        <div class="no-data" id="no-data" style="display:none">No se encontraron resultados</div>
      </div>
    </div>
  </div>

  <!-- TAB: Invitaciones -->
  <div class="tab-content" id="tab-invitations">
    <div class="container">
      <div class="inv-stats">
        <div class="inv-stat">
          <span class="inv-stat-num" id="inv-total">0</span>
          <span class="inv-stat-label">Total</span>
        </div>
        <div class="inv-stat">
          <span class="inv-stat-num" style="color:var(--green)" id="inv-unused">0</span>
          <span class="inv-stat-label">Disponibles</span>
        </div>
        <div class="inv-stat">
          <span class="inv-stat-num" style="color:var(--red)" id="inv-used">0</span>
          <span class="inv-stat-label">Usados</span>
        </div>
      </div>

      <div class="inv-toolbar">
        <button class="btn" onclick="generateCodes()">🎟️ Generar Códigos</button>
        <select id="inv-filter" onchange="loadInvitations(1)" style="background:var(--card);border:1px solid var(--border);border-radius:10px;color:var(--text);padding:10px;font-size:.9rem">
          <option value="all">Todos</option>
          <option value="unused">Disponibles</option>
          <option value="used">Usados</option>
        </select>
      </div>

      <div id="inv-table-wrap">
        <table id="inv-table">
          <thead>
            <tr>
              <th>Código</th>
              <th>Estado</th>
              <th>Creado</th>
              <th>Usado en</th>
              <th>Acciones</th>
            </tr>
          </thead>
          <tbody id="inv-tbody"></tbody>
        </table>
      </div>

      <div id="inv-pagination" style="display:flex;justify-content:center;gap:8px;margin-top:20px"></div>
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

  <!-- Generate Codes Modal -->
  <div class="modal" id="gen-modal" onclick="closeGenModal(event)">
    <div class="modal-content" style="max-width:400px">
      <p style="font-size:1.1rem;font-weight:700;margin-bottom:16px">Generar Códigos de Invitación</p>
      <label style="display:block;font-size:.85rem;color:var(--muted);margin-bottom:6px;text-align:left">Cantidad (1-100)</label>
      <input type="number" id="gen-count" value="10" min="1" max="100"
        style="width:100%;background:#0f172a;border:1px solid #475569;border-radius:10px;color:var(--text);padding:12px;font-size:1rem;margin-bottom:20px;text-align:center">
      <div style="display:flex;gap:10px">
        <button class="btn" style="flex:1" onclick="doGenerate()">Generar</button>
        <button class="btn btn-ghost" style="flex:1" onclick="closeGenModal()">Cancelar</button>
      </div>
      <div id="gen-result" style="margin-top:16px;max-height:200px;overflow-y:auto;text-align:left;display:none">
        <p style="font-size:.85rem;color:var(--muted);margin-bottom:8px">Códigos generados:</p>
        <div id="gen-codes-list"></div>
      </div>
    </div>
  </div>

  <!-- Toast -->
  <div class="toast" id="toast"></div>

<script>
  let ALL_DATA = [];
  let INV_PAGE = 1;
  const CAPACITY = 1800;

  function switchTab(tab) {
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
    document.querySelector(\`.tab[data-tab="\${tab}"]\`).classList.add('active');
    document.getElementById('tab-' + tab).classList.add('active');
    if (tab === 'invitations') loadInvitations(1);
  }

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
      return \`<tr>
        <td><span class="qr-mini" onclick="showQR('\${a.hash_unique}','\${(a.nombre + ' ' + a.apellido).replace(/'/g,"\\\\'")}')">📱</span></td>
        <td>\${esc(a.nombre)}</td>
        <td>\${esc(a.apellido || '—')}</td>
        <td class="code-text">\${esc(a.nro_documento || '—')}</td>
        <td>\${esc(a.invitado_por || '—')}</td>
        <td>\${status}</td>
        <td>\${fecha}</td>
      </tr>\`;
    }).join('');
  }

  // ── Invitations ───────────────────────────────────────────────
  async function loadInvitations(page) {
    INV_PAGE = page;
    const filter = document.getElementById('inv-filter').value;
    const res = await fetch(\`/admin/api/invitations?page=\${page}&per_page=50&status_filter=\${filter}\`);
    const data = await res.json();

    document.getElementById('inv-total').textContent = data.total;
    document.getElementById('inv-unused').textContent = data.unused;
    document.getElementById('inv-used').textContent = data.used;

    const tbody = document.getElementById('inv-tbody');
    tbody.innerHTML = data.codes.map(c => {
      const status = c.used
        ? '<span class="status used">✓ Usado</span>'
        : '<span class="status unused">Disponible</span>';
      const actions = c.used
        ? '<span style="color:var(--muted);font-size:.8rem">—</span>'
        : \`<button class="btn btn-sm btn-danger" onclick="revokeCode(\${c.id},'\${c.code}')">Revocar</button>\`;
      return \`<tr>
        <td class="code-text">\${esc(c.code)} <span class="copy-btn" onclick="copyCode('\${c.code}')" title="Copiar">📋</span></td>
        <td>\${status}</td>
        <td>\${c.creado_en || '—'}</td>
        <td>\${c.usado_en || '—'}</td>
        <td>\${actions}</td>
      </tr>\`;
    }).join('');

    renderPagination(data.pages, page);
  }

  function renderPagination(pages, current) {
    const container = document.getElementById('inv-pagination');
    if (pages <= 1) { container.innerHTML = ''; return; }
    let html = '';
    for (let i = 1; i <= pages; i++) {
      const active = i === current ? 'background:var(--blue);color:#fff' : '';
      html += \`<button onclick="loadInvitations(\${i})" style="padding:6px 12px;border:1px solid var(--border);border-radius:8px;background:var(--card);color:var(--text);cursor:pointer;\${active}">\${i}</button>\`;
    }
    container.innerHTML = html;
  }

  function generateCodes() { document.getElementById('gen-modal').classList.add('open'); }
  function closeGenModal(e) { if (!e || e.target === document.getElementById('gen-modal')) document.getElementById('gen-modal').classList.remove('open'); }

  async function doGenerate() {
    const count = parseInt(document.getElementById('gen-count').value) || 1;
    const res = await fetch(\`/admin/api/invitations/generate?count=\${count}\`, { method: 'POST' });
    const data = await res.json();
    const list = document.getElementById('gen-codes-list');
    list.innerHTML = data.codes.map(c =>
      \`<div style="display:flex;justify-content:space-between;align-items:center;padding:6px 0;border-bottom:1px solid var(--border)">
        <span class="code-text">\${esc(c)}</span>
        <span class="copy-btn" onclick="copyCode('\${c}')">📋</span>
      </div>\`
    ).join('');
    document.getElementById('gen-result').style.display = 'block';
    loadInvitations(INV_PAGE);
    showToast(\`\${data.count} códigos generados\`);
  }

  async function revokeCode(id, code) {
    if (!confirm(\`¿Revocar el código \${code}?\`)) return;
    await fetch(\`/admin/api/invitations/\${id}/revoke\`, { method: 'POST' });
    loadInvitations(INV_PAGE);
    showToast(\`Código \${code} revocado\`);
  }

  function copyCode(code) {
    navigator.clipboard.writeText(code);
    showToast('Código copiado: ' + code);
  }

  function showToast(msg) {
    const t = document.getElementById('toast');
    t.textContent = msg;
    t.classList.add('show');
    setTimeout(() => t.classList.remove('show'), 2500);
  }

  function showQR(hash, name) {
    fetch(\`/admin/qr/\${hash}\`)
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
  document.getElementById('inv-filter').addEventListener('change', () => loadInvitations(1));

  function applyFilters() {
    const q = document.getElementById('search').value.toLowerCase();
    const f = document.getElementById('filter-status').value;
    let data = ALL_DATA;
    if (q) data = data.filter(a =>
      (a.nombre || '').toLowerCase().includes(q) ||
      (a.apellido || '').toLowerCase().includes(q) ||
      (a.nro_documento || '').toLowerCase().includes(q)
    );
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
                "apellido": a.apellido,
                "nro_documento": a.nro_documento,
                "email": a.email,
                "invitado_por": a.invitado_por,
                "qr_token": a.qr_token,
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
        stmt = select(Attendee).where(
            (Attendee.qr_token == hash_id.upper()) | (Attendee.hash_unique == hash_id.upper())
        )
        result = await session.execute(stmt)
        attendee = result.scalar_one_or_none()

    if not attendee:
        return Response(content="No encontrado", status_code=404, media_type="text/plain")

    qr_bytes = _make_qr(attendee.qr_token)
    return Response(content=qr_bytes, media_type="image/png")


# ── Invitation Code Management ──────────────────────────────────────────

@router.post("/admin/api/invitations/generate")
async def generate_invitation_codes(count: int = Query(1, ge=1, le=100), user: AdminUser = Depends(require_user)):
    """Genera códigos de invitación nuevos."""
    codes = []
    async with async_session() as session:
        for _ in range(count):
            code_str = _generate_invitation_code()
            invitation = InvitationCode(code=code_str)
            session.add(invitation)
            codes.append(code_str)
        await session.commit()
    return {"codes": codes, "count": len(codes)}


@router.get("/admin/api/invitations")
async def list_invitation_codes(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    status_filter: str = Query("all"),
    user: AdminUser = Depends(require_user),
):
    """Lista todos los códigos de invitación con paginación."""
    async with async_session() as session:
        # Stats
        total_stmt = select(func.count(InvitationCode.id))
        used_stmt = select(func.count(InvitationCode.id)).where(InvitationCode.used.is_(True))
        unused_stmt = select(func.count(InvitationCode.id)).where(InvitationCode.used.is_(False))

        total = (await session.execute(total_stmt)).scalar() or 0
        used_count = (await session.execute(used_stmt)).scalar() or 0
        unused_count = (await session.execute(unused_stmt)).scalar() or 0

        # Query with filters
        stmt = select(InvitationCode).order_by(desc(InvitationCode.creado_en))
        if status_filter == "used":
            stmt = stmt.where(InvitationCode.used.is_(True))
        elif status_filter == "unused":
            stmt = stmt.where(InvitationCode.used.is_(False))

        # Pagination
        offset = (page - 1) * per_page
        stmt = stmt.offset(offset).limit(per_page)
        result = await session.execute(stmt)
        codes = result.scalars().all()

        return {
            "total": total,
            "used": used_count,
            "unused": unused_count,
            "page": page,
            "per_page": per_page,
            "pages": (total + per_page - 1) // per_page,
            "codes": [
                {
                    "id": c.id,
                    "code": c.code,
                    "used": c.used,
                    "creado_en": c.creado_en.strftime("%d/%m/%Y %H:%M") if c.creado_en else None,
                    "usado_en": c.usado_en.strftime("%d/%m/%Y %H:%M") if c.usado_en else None,
                    "attendee_id": c.attendee_id,
                }
                for c in codes
            ],
        }


@router.post("/admin/api/invitations/{code_id}/revoke")
async def revoke_invitation_code(code_id: int, user: AdminUser = Depends(require_user)):
    """Revoca un código de invitación (solo si no fue usado)."""
    async with async_session() as session:
        stmt = select(InvitationCode).where(InvitationCode.id == code_id)
        result = await session.execute(stmt)
        invitation = result.scalar_one_or_none()

        if not invitation:
            return Response(content="Código no encontrado", status_code=404, media_type="text/plain")

        if invitation.used:
            return Response(content="No se puede revocar un código ya utilizado", status_code=409, media_type="text/plain")

        invitation.used = True
        invitation.usado_en = datetime.now(datetime.timezone.utc)
        await session.commit()

    return {"success": True, "message": f"Código {invitation.code} revocado"}


@router.delete("/admin/api/invitations/{code_id}")
async def delete_invitation_code(code_id: int, user: AdminUser = Depends(require_user)):
    """Elimina un código de invitación no usado."""
    async with async_session() as session:
        stmt = select(InvitationCode).where(InvitationCode.id == code_id)
        result = await session.execute(stmt)
        invitation = result.scalar_one_or_none()

        if not invitation:
            return Response(content="Código no encontrado", status_code=404, media_type="text/plain")

        if invitation.used:
            return Response(content="No se puede eliminar un código ya utilizado", status_code=409, media_type="text/plain")

        await session.delete(invitation)
        await session.commit()

    return {"success": True, "message": f"Código {invitation.code} eliminado"}
