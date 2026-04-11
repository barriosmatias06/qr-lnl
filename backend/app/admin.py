"""
Admin dashboard routes.
"""

import io
import base64
import random
import string
from datetime import datetime, timezone

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


# ── Admin Dashboard HTML ──────────────────────────────────────────────────

ADMIN_HTML = """<!DOCTYPE html>
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
    .tabs{display:flex;gap:4px;margin-bottom:24px}
    .tab{padding:10px 20px;border-radius:10px 10px 0 0;background:var(--card);
         border:1px solid var(--border);border-bottom:none;color:var(--muted);
         cursor:pointer;font-weight:600;font-size:.85rem;transition:color .15s}
    .tab.active{color:var(--blue);border-color:var(--blue);background:var(--bg)}
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
    .s-inv-used .stat-num{color:var(--green)}
    .s-inv-unused .stat-num{color:var(--yellow)}
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
    .status.used{background:rgba(239,68,68,.15);color:var(--red)}
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
    .btn{background:var(--blue);color:#fff;border:none;border-radius:10px;padding:10px 18px;
         font-size:.85rem;font-weight:600;cursor:pointer;transition:opacity .15s}
    .btn:hover{opacity:.9}
    .btn:active{opacity:.8}
    .btn-danger{background:var(--red)}
    .btn-sm{padding:6px 12px;font-size:.75rem;border-radius:8px}
    .btn-success{background:var(--green)}
    .inv-toolbar{display:flex;gap:12px;margin-bottom:20px;align-items:center;flex-wrap:wrap}
    .inv-toolbar select{background:var(--card);border:1px solid var(--border);border-radius:10px;
                        color:var(--text);padding:10px;font-size:.85rem}
    .inv-code{font-family:monospace;font-weight:700;letter-spacing:.05em;font-size:.95rem}
    .inv-actions{display:flex;gap:6px}
    .pagination{display:flex;gap:8px;justify-content:center;margin-top:20px;align-items:center}
    .pagination button{background:var(--card);border:1px solid var(--border);border-radius:8px;
                       color:var(--text);padding:8px 14px;font-size:.8rem;cursor:pointer}
    .pagination button:disabled{opacity:.4;cursor:default}
    .pagination button:hover:not(:disabled){border-color:var(--blue)}
    .pagination span{color:var(--muted);font-size:.8rem}
    .copy-btn{cursor:pointer;opacity:.5;transition:opacity .15s;margin-left:6px;font-size:1rem}
    .copy-btn:hover{opacity:1}
    .toast{position:fixed;bottom:20px;right:20px;background:var(--green);color:#fff;
           padding:12px 20px;border-radius:10px;font-size:.9rem;font-weight:600;
           opacity:0;transition:opacity .2s;z-index:200;pointer-events:none}
    .toast.show{opacity:1}
    .whatsapp-btn{background:#25D366;color:#fff}
    .whatsapp-btn:hover{opacity:.9}
    .gen-codes-box{margin-top:16px;text-align:left;max-height:250px;overflow-y:auto}
    .gen-code-item{display:flex;justify-content:space-between;align-items:center;
                   padding:8px 12px;border-bottom:1px solid var(--border);gap:8px}
    .gen-code-item:last-child{border-bottom:none}
  </style>
</head>
<body>
  <div class="topbar">
    <h1>🎫 Panel de Administración</h1>
    <span class="badge" id="last-update">—</span>
  </div>
  <div class="container">
    <!-- Tabs -->
    <div class="tabs">
      <div class="tab active" data-tab="attendees" onclick="switchTab('attendees')">👥 Asistentes</div>
      <div class="tab" data-tab="invitations" onclick="switchTab('invitations')">🎟️ Invitaciones</div>
    </div>

    <!-- TAB: Asistentes -->
    <div class="tab-content active" id="tab-attendees">
      <div class="stats">
        <div class="stat s-total"><div class="stat-num" id="s-total">—</div><div class="stat-label">Registrados</div></div>
        <div class="stat s-ingresaron"><div class="stat-num" id="s-ingresaron">—</div><div class="stat-label">Ingresaron</div></div>
        <div class="stat s-pendientes"><div class="stat-num" id="s-pendientes">—</div><div class="stat-label">Pendientes</div></div>
        <div class="stat s-lugares"><div class="stat-num" id="s-lugares">—</div><div class="stat-label">Lugares libres</div></div>
      </div>
      <div class="search-bar">
        <input type="text" id="search" placeholder="Buscar por nombre, apellido, documento o código..." autocomplete="off">
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
              <th>Código Inv.</th>
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

    <!-- TAB: Invitaciones -->
    <div class="tab-content" id="tab-invitations">
      <div class="stats">
        <div class="stat s-total"><div class="stat-num" id="inv-total">—</div><div class="stat-label">Total</div></div>
        <div class="stat s-inv-used"><div class="stat-num" id="inv-used">—</div><div class="stat-label">Usados</div></div>
        <div class="stat s-inv-unused"><div class="stat-num" id="inv-unused">—</div><div class="stat-label">Disponibles</div></div>
      </div>
      <div class="inv-toolbar">
        <button class="btn btn-success" onclick="openGenerateModal()">+ Crear Código</button>
        <select id="inv-filter" onchange="invPage=1;loadInvitations()">
          <option value="all">Todos</option>
          <option value="unused">Disponibles</option>
          <option value="used">Usados</option>
        </select>
      </div>
      <div id="inv-table-wrap">
        <div class="loading" id="inv-loading">Cargando invitaciones...</div>
        <table id="inv-table" style="display:none">
          <thead>
            <tr>
              <th>Código</th>
              <th>Estado</th>
              <th>Creado</th>
              <th>Usado por</th>
              <th>Acciones</th>
            </tr>
          </thead>
          <tbody id="inv-tbody"></tbody>
        </table>
        <div class="no-data" id="inv-no-data" style="display:none">No hay códigos de invitación.<br>Hacé clic en <strong>"+ Crear Código"</strong> para generar.</div>
        <div class="pagination" id="inv-pagination"></div>
      </div>
    </div>
  </div>

  <!-- QR Modal -->
  <div class="modal" id="qr-modal" onclick="if(event.target===this)this.classList.remove('open')">
    <div class="modal-content">
      <img id="modal-qr-img" src="" alt="QR" style="max-width:220px">
      <p id="modal-name" style="font-weight:600;margin-bottom:12px"></p>
      <button onclick="document.getElementById('qr-modal').classList.remove('open')">Cerrar</button>
    </div>
  </div>

  <!-- Generate Codes Modal -->
  <div class="modal" id="generate-modal" onclick="if(event.target===this)this.classList.remove('open')">
    <div class="modal-content" style="max-width:400px">
      <p style="font-weight:600;margin-bottom:16px;font-size:1.1rem">🎟️ Crear Códigos de Invitación</p>
      <div style="display:flex;gap:10px;align-items:center;justify-content:center;margin-bottom:20px">
        <label for="gen-count" style="font-size:.85rem;color:var(--muted)">Cantidad:</label>
        <input type="number" id="gen-count" value="10" min="1" max="100"
               style="width:80px;background:#0f172a;border:1px solid var(--border);border-radius:8px;
                      color:var(--text);padding:8px;text-align:center;font-size:.9rem">
      </div>
      <button class="btn" onclick="doGenerate()" style="width:100%;margin-bottom:12px">Generar Códigos</button>
      <button class="btn" style="width:100%;background:transparent;border:1px solid var(--border)" onclick="document.getElementById('generate-modal').classList.remove('open')">Cerrar</button>
      <div id="generated-codes" style="display:none">
        <div class="gen-codes-box" id="gen-codes-list"></div>
        <div style="margin-top:12px;display:flex;gap:8px">
          <button class="btn btn-sm" style="flex:1" onclick="copyAllCodes()">📋 Copiar Todos</button>
          <button class="btn btn-sm whatsapp-btn" style="flex:1" onclick="shareAllWhatsApp()">💬 WhatsApp</button>
        </div>
      </div>
    </div>
  </div>

  <!-- Toast -->
  <div class="toast" id="toast"></div>

<script>
  var ALL_DATA = [];
  var invPage = 1;
  var lastGeneratedCodes = [];
  var CAPACITY = 1800;

  function switchTab(name) {
    document.querySelectorAll('.tab').forEach(function(t) { t.classList.remove('active'); });
    document.querySelectorAll('.tab-content').forEach(function(tc) { tc.classList.remove('active'); });
    document.querySelector('.tab[data-tab="' + name + '"]').classList.add('active');
    document.getElementById('tab-' + name).classList.add('active');
    if (name === 'invitations') { invPage = 1; loadInvitations(); }
  }

  // ── Attendees ─────────────────────────────────────────────────────────
  function loadData() {
    fetch('/api/admin/data').then(function(r) { return r.json(); }).then(function(json) {
      ALL_DATA = json.attendees;
      renderStats(json);
      renderTable(ALL_DATA);
      document.getElementById('last-update').textContent = 'Actualizado: ' + new Date().toLocaleTimeString();
    }).catch(function() {});
  }

  function renderStats(json) {
    var total = json.total;
    var ingresaron = json.ingresaron;
    document.getElementById('s-total').textContent = total;
    document.getElementById('s-ingresaron').textContent = ingresaron;
    document.getElementById('s-pendientes').textContent = total - ingresaron;
    document.getElementById('s-lugares').textContent = Math.max(0, CAPACITY - ingresaron);
  }

  function renderTable(data) {
    var tbody = document.getElementById('tbody');
    var table = document.getElementById('table');
    var loading = document.getElementById('loading');
    var noData = document.getElementById('no-data');
    loading.style.display = 'none';

    if (!data.length) { noData.style.display = 'block'; table.style.display = 'none'; return; }
    noData.style.display = 'none';
    table.style.display = 'table';

    var html = '';
    for (var i = 0; i < data.length; i++) {
      var a = data[i];
      var status = a.estado_ingreso
        ? '<span class="status in">✓ Ingresó</span>'
        : '<span class="status pending">Pendiente</span>';
      var fecha = a.fecha_ingreso || '—';
      var invCode = a.invitation_code || '—';
      var fullName = (a.nombre || '') + ' ' + (a.apellido || '');
      var qrToken = a.qr_token || a.hash_unique || '';

      html += '<tr>';
      html += '<td><span class="qr-mini" onclick="showQR(\\'' + qrToken + '\\',\\'' + esc(fullName) + '\\')">📱</span></td>';
      html += '<td>' + esc(a.nombre) + '</td>';
      html += '<td>' + esc(a.apellido || '—') + '</td>';
      html += '<td>' + esc(a.nro_documento || '—') + '</td>';
      html += '<td><span class="inv-code">' + esc(invCode) + '</span></td>';
      html += '<td>' + esc(a.invitado_por || '—') + '</td>';
      html += '<td>' + status + '</td>';
      html += '<td>' + fecha + '</td>';
      html += '</tr>';
    }
    tbody.innerHTML = html;
  }

  function showQR(hash, name) {
    fetch('/admin/qr/' + hash).then(function(r) { return r.blob(); }).then(function(blob) {
      document.getElementById('modal-qr-img').src = URL.createObjectURL(blob);
      document.getElementById('modal-name').textContent = name;
      document.getElementById('qr-modal').classList.add('open');
    });
  }

  function esc(s) { var d = document.createElement('div'); d.textContent = s; return d.innerHTML; }

  document.getElementById('search').addEventListener('input', applyFilters);
  document.getElementById('filter-status').addEventListener('change', applyFilters);

  function applyFilters() {
    var q = document.getElementById('search').value.toLowerCase();
    var f = document.getElementById('filter-status').value;
    var data = ALL_DATA;
    if (q) data = data.filter(function(a) {
      return (a.nombre || '').toLowerCase().indexOf(q) >= 0 ||
             (a.apellido || '').toLowerCase().indexOf(q) >= 0 ||
             (a.nro_documento || '').toLowerCase().indexOf(q) >= 0 ||
             (a.invitation_code || '').toLowerCase().indexOf(q) >= 0;
    });
    if (f === 'in') data = data.filter(function(a) { return a.estado_ingreso; });
    if (f === 'pending') data = data.filter(function(a) { return !a.estado_ingreso; });
    renderTable(data);
  }

  // ── Invitations ───────────────────────────────────────────────────────
  function loadInvitations() {
    document.getElementById('inv-loading').style.display = 'block';
    document.getElementById('inv-table').style.display = 'none';
    document.getElementById('inv-no-data').style.display = 'none';
    var filter = document.getElementById('inv-filter').value;
    fetch('/admin/api/invitations?page=' + invPage + '&status_filter=' + filter)
      .then(function(r) { return r.json(); }).then(function(json) {
        document.getElementById('inv-loading').style.display = 'none';
        document.getElementById('inv-total').textContent = json.total;
        document.getElementById('inv-used').textContent = json.used;
        document.getElementById('inv-unused').textContent = json.unused;

        if (!json.codes.length) {
          document.getElementById('inv-no-data').style.display = 'block';
          document.getElementById('inv-pagination').innerHTML = '';
          return;
        }

        document.getElementById('inv-table').style.display = 'table';
        var html = '';
        for (var i = 0; i < json.codes.length; i++) {
          var c = json.codes[i];
          var st = c.used
            ? '<span class="status used">✓ Usado</span>'
            : '<span class="status unused">Disponible</span>';
          var actions;
          if (c.used) {
            actions = '<span style="color:var(--muted);font-size:.75rem">—</span>';
          } else {
            actions = '<div class="inv-actions">';
            actions += '<button class="btn btn-sm btn-danger" onclick="revokeCode(' + c.id + ',\\'' + esc(c.code) + '\\')">Revocar</button>';
            actions += '<button class="btn btn-sm" style="background:var(--orange)" onclick="deleteCode(' + c.id + ',\\'' + esc(c.code) + '\\')">Eliminar</button>';
            actions += '</div>';
          }
          var usedBy = c.attendee_name
            ? '<span style="color:var(--blue);font-size:.8rem">' + esc(c.attendee_name) + '</span>'
            : '—';
          html += '<tr>';
          html += '<td><span class="inv-code">' + esc(c.code) + '</span><span class="copy-btn" onclick="copyCode(\\'' + esc(c.code) + '\\')" title="Copiar">📋</span></td>';
          html += '<td>' + st + '</td>';
          html += '<td>' + (c.creado_en || '—') + '</td>';
          html += '<td>' + usedBy + '</td>';
          html += '<td>' + actions + '</td>';
          html += '</tr>';
        }
        document.getElementById('inv-tbody').innerHTML = html;

        // Pagination
        var pagHtml = '<button onclick="invPage=' + (json.page - 1) + ';loadInvitations()" ' + (json.page <= 1 ? 'disabled' : '') + '>← Anterior</button>';
        pagHtml += '<span>Pág ' + json.page + ' de ' + (json.pages || 1) + '</span>';
        pagHtml += '<button onclick="invPage=' + (json.page + 1) + ';loadInvitations()" ' + (json.page >= json.pages ? 'disabled' : '') + '>Siguiente →</button>';
        document.getElementById('inv-pagination').innerHTML = pagHtml;
      }).catch(function() {
        document.getElementById('inv-loading').style.display = 'none';
      });
  }

  function copyCode(code) {
    navigator.clipboard.writeText(code).then(function() {
      showToast('Código copiado: ' + code);
    });
  }

  function revokeCode(id, code) {
    if (!confirm('¿Revocar el código ' + code + '?')) return;
    fetch('/admin/api/invitations/' + id + '/revoke', { method: 'POST' }).then(function(r) {
      if (r.ok) { loadInvitations(); showToast('Código ' + code + ' revocado'); }
      else { alert('Error al revocar'); }
    });
  }

  function deleteCode(id, code) {
    if (!confirm('¿Eliminar el código ' + code + '?')) return;
    fetch('/admin/api/invitations/' + id, { method: 'DELETE' }).then(function(r) {
      if (r.ok) { loadInvitations(); showToast('Código ' + code + ' eliminado'); }
      else { alert('Error al eliminar'); }
    });
  }

  // ── Generate Codes ────────────────────────────────────────────────────
  function openGenerateModal() {
    document.getElementById('generate-modal').classList.add('open');
    document.getElementById('generated-codes').style.display = 'none';
  }

  function doGenerate() {
    var count = parseInt(document.getElementById('gen-count').value) || 1;
    fetch('/admin/api/invitations/generate?count=' + count, { method: 'POST' })
      .then(function(r) { return r.json(); }).then(function(json) {
        lastGeneratedCodes = json.codes;
        var html = '';
        for (var i = 0; i < json.codes.length; i++) {
          html += '<div class="gen-code-item">';
          html += '<span class="inv-code">' + esc(json.codes[i]) + '</span>';
          html += '<span class="copy-btn" onclick="copyCode(\\'' + esc(json.codes[i]) + '\\')">📋</span>';
          html += '</div>';
        }
        document.getElementById('gen-codes-list').innerHTML = html;
        document.getElementById('generated-codes').style.display = 'block';
        loadInvitations();
        showToast(json.count + ' códigos generados');
      });
  }

  function copyAllCodes() {
    var text = lastGeneratedCodes.join('\\n');
    navigator.clipboard.writeText(text).then(function() {
      showToast('Todos los códigos copiados');
    });
  }

  function shareAllWhatsApp() {
    var text = '🎫 *Código de Invitación al Evento*\\n\\n';
    text += 'Usá este código para registrarte:\\n\\n';
    for (var i = 0; i < lastGeneratedCodes.length; i++) {
      text += '▸ ' + lastGeneratedCodes[i] + '\\n';
    }
    text += '\\nIngresá a ' + window.location.origin + '/register para completar tu registro.';
    window.open('https://wa.me/?text=' + encodeURIComponent(text), '_blank');
  }

  // ── Toast ─────────────────────────────────────────────────────────────
  function showToast(msg) {
    var t = document.getElementById('toast');
    t.textContent = msg;
    t.classList.add('show');
    setTimeout(function() { t.classList.remove('show'); }, 2500);
  }

  // ── Init ──────────────────────────────────────────────────────────────
  loadData();
  setInterval(loadData, 30000);
</script>
</body>
</html>"""


@router.get("/admin", response_class=HTMLResponse)
async def admin_dashboard(request: Request):
    """Panel de administración con estadísticas y listado."""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/admin/login", status_code=302)
    return ADMIN_HTML


# ── API Endpoints ──────────────────────────────────────────────────────────

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

        # Build lookup for invitation codes
        attendee_codes = {}
        attendee_names = {}
        for a in attendees:
            if a.invitation_code_id:
                code_stmt = select(InvitationCode).where(InvitationCode.id == a.invitation_code_id)
                code_result = await session.execute(code_stmt)
                code = code_result.scalar_one_or_none()
                if code:
                    attendee_codes[a.id] = code.code

        # Build reverse lookup: for each invitation code, find who used it
        code_attendee = {}
        for a in attendees:
            if a.invitation_code_id:
                full_name = a.nombre
                if a.apellido:
                    full_name += " " + a.apellido
                code_attendee[a.invitation_code_id] = full_name

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
                "invitation_code": attendee_codes.get(a.id, ""),
            }
            for a in attendees
        ],
        "_code_attendee": code_attendee,
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

        # Get attendee names for used codes
        attendee_names = {}
        for c in codes:
            if c.attendee_id:
                att_stmt = select(Attendee).where(Attendee.id == c.attendee_id)
                att_result = await session.execute(att_stmt)
                att = att_result.scalar_one_or_none()
                if att:
                    name = att.nombre
                    if att.apellido:
                        name += " " + att.apellido
                    attendee_names[c.id] = name

        return {
            "total": total,
            "used": used_count,
            "unused": unused_count,
            "page": page,
            "per_page": per_page,
            "pages": (total + per_page - 1) // per_page if per_page > 0 else 1,
            "codes": [
                {
                    "id": c.id,
                    "code": c.code,
                    "used": c.used,
                    "creado_en": c.creado_en.strftime("%d/%m/%Y %H:%M") if c.creado_en else None,
                    "usado_en": c.usado_en.strftime("%d/%m/%Y %H:%M") if c.usado_en else None,
                    "attendee_id": c.attendee_id,
                    "attendee_name": attendee_names.get(c.id, ""),
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
        invitation.usado_en = datetime.now(timezone.utc)
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
