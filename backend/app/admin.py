"""
Admin dashboard routes.
"""

import io
import base64
import random
import string
from datetime import datetime, timezone
from pathlib import Path

import qrcode
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from PIL import Image
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
    chars = string.ascii_uppercase + string.digits
    return f"INV-{''.join(random.choices(chars, k=8))}"


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


# ── Static file serving ──────────────────────────────────────────────────────

STATIC_DIR = Path(__file__).parent / "static"


@router.get("/static/admin.js")
async def serve_admin_js():
    js_path = STATIC_DIR / "admin.js"
    if not js_path.is_file():
        return Response(content="Not found", status_code=404)
    content = js_path.read_text(encoding="utf-8")
    return Response(content=content, media_type="application/javascript")


# ── Admin Dashboard HTML ─────────────────────────────────────────────────────

ADMIN_HTML = """<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta name="theme-color" content="#0f172a">
  <title>Admin — Control de Acceso</title>
  <style>
    :root {
      --bg:#0f172a; --card:#1e293b; --border:#334155; --muted:#64748b;
      --text:#f1f5f9; --green:#22c55e; --orange:#f97316; --red:#ef4444;
      --blue:#3b82f6; --yellow:#eab308; --radius:12px;
    }
    *,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
    body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
         background:var(--bg);color:var(--text);min-height:100dvh}

    /* Topbar */
    .topbar{background:var(--card);border-bottom:1px solid var(--border);
            padding:14px 24px;display:flex;align-items:center;justify-content:space-between}
    .topbar h1{font-size:1.1rem;font-weight:700;display:flex;align-items:center;gap:8px}
    .topbar .badge{background:var(--blue);color:#fff;padding:4px 12px;border-radius:20px;font-size:.7rem;font-weight:600}

    /* Container */
    .container{max-width:1200px;margin:0 auto;padding:20px}

    /* Tabs */
    .tabs{display:flex;gap:2px;margin-bottom:24px;border-bottom:1px solid var(--border);padding-bottom:0}
    .tab{padding:10px 20px;cursor:pointer;font-size:.85rem;font-weight:600;color:var(--muted);
         border-bottom:2px solid transparent;margin-bottom:-1px;transition:all .15s}
    .tab:hover{color:var(--text)}
    .tab.active{color:var(--blue);border-bottom-color:var(--blue)}
    .tab-content{display:none}
    .tab-content.active{display:block}

    /* Stats cards */
    .stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;margin-bottom:24px}
    .stat{background:var(--card);border:1px solid var(--border);border-radius:var(--radius);padding:16px;text-align:center}
    .stat-num{font-size:2rem;font-weight:800;line-height:1}
    .stat-label{font-size:.65rem;text-transform:uppercase;letter-spacing:.08em;color:var(--muted);margin-top:4px}
    .s-total .stat-num{color:var(--blue)}
    .s-ingresaron .stat-num{color:var(--green)}
    .s-pendientes .stat-num{color:var(--orange)}
    .s-lugares .stat-num{color:var(--yellow)}
    .s-inv-used .stat-num{color:var(--green)}
    .s-inv-unused .stat-num{color:var(--yellow)}

    /* Search bar */
    .search-bar{margin-bottom:20px;display:flex;gap:10px}
    .search-bar input{flex:1;background:var(--card);border:1px solid var(--border);
                      border-radius:10px;color:var(--text);padding:10px 14px;font-size:.9rem}
    .search-bar input:focus{outline:none;border-color:var(--blue)}
    .search-bar select{background:var(--card);border:1px solid var(--border);border-radius:10px;
                       color:var(--text);padding:10px;font-size:.85rem}

    /* Tables */
    table{width:100%;border-collapse:collapse;background:var(--card);border-radius:var(--radius);overflow:hidden}
    th{background:var(--card);color:var(--muted);font-size:.65rem;text-transform:uppercase;letter-spacing:.06em;
       padding:10px 14px;text-align:left;border-bottom:1px solid var(--border);font-weight:600}
    td{padding:10px 14px;border-bottom:1px solid var(--border);font-size:.82rem;vertical-align:middle}
    tr:last-child td{border-bottom:none}
    tr:hover td{background:rgba(59,130,246,.05)}
    code{background:rgba(59,130,246,.1);padding:2px 8px;border-radius:6px;font-size:.8rem;font-family:'SF Mono',Monaco,monospace}

    /* Status badges */
    .status-badge{padding:3px 10px;border-radius:20px;font-size:.7rem;font-weight:600;display:inline-block}
    .status-in{background:rgba(34,197,94,.15);color:var(--green)}
    .status-pending{background:rgba(249,115,22,.15);color:var(--orange)}
    .status-used{background:rgba(239,68,68,.15);color:var(--red)}
    .status-unused{background:rgba(34,197,94,.15);color:var(--green)}

    /* Buttons */
    .btn{background:var(--blue);color:#fff;border:none;border-radius:10px;padding:10px 18px;
         font-size:.82rem;font-weight:600;cursor:pointer;transition:opacity .15s}
    .btn:hover{opacity:.85}
    .btn:disabled{opacity:.4;cursor:not-allowed}
    .btn-sm{padding:6px 12px;font-size:.72rem;border-radius:8px}
    .btn-danger{background:var(--red)}
    .btn-warning{background:var(--orange)}
    .btn-success{background:var(--green)}
    .btn-icon{background:none;border:none;cursor:pointer;font-size:1rem;padding:4px;opacity:.6;transition:opacity .15s}
    .btn-icon:hover{opacity:1}

    /* Toolbar */
    .inv-toolbar{display:flex;gap:10px;margin-bottom:20px;align-items:center;flex-wrap:wrap}
    .inv-toolbar select{background:var(--card);border:1px solid var(--border);border-radius:10px;color:var(--text);padding:8px 12px;font-size:.82rem}
    .inv-actions{display:flex;gap:6px}

    /* Pagination */
    .pagination{display:flex;gap:8px;justify-content:center;margin-top:16px;align-items:center}
    .pagination span{color:var(--muted);font-size:.78rem}

    /* Loading / No data */
    .loading{text-align:center;padding:40px;color:var(--muted);font-size:.9rem}
    .no-data{text-align:center;padding:48px 20px;color:var(--muted)}

    /* QR mini */
    .qr-mini{cursor:pointer;font-size:1.2rem;transition:opacity .15s}
    .qr-mini:hover{opacity:.8}

    /* Modals */
    .modal{position:fixed;inset:0;background:rgba(0,0,0,.65);display:none;align-items:center;
           justify-content:center;z-index:100;backdrop-filter:blur(4px)}
    .modal.open{display:flex}
    .modal-content{background:var(--card);border:1px solid var(--border);border-radius:16px;padding:24px;
                   text-align:center;max-width:320px;width:90%}
    .modal-content img{border-radius:10px;margin-bottom:12px;max-width:100%}
    .modal-content p{margin-bottom:16px}

    /* Toast */
    .toast{position:fixed;bottom:20px;right:20px;padding:12px 20px;border-radius:10px;font-size:.85rem;
           font-weight:600;opacity:0;transition:opacity .25s;z-index:200;pointer-events:none}
    .toast.show{opacity:1}
    .toast-success{background:var(--green);color:#fff}
    .toast-error{background:var(--red);color:#fff}

    /* Generated codes box */
    .gen-codes-box{margin-top:14px;text-align:left;max-height:220px;overflow-y:auto;border:1px solid var(--border);border-radius:10px}
    .gen-code-item{display:flex;justify-content:space-between;align-items:center;padding:8px 14px;border-bottom:1px solid var(--border)}
    .gen-code-item:last-child{border-bottom:none}
    .attendee-link{color:var(--blue);font-size:.8rem}
    .text-muted{color:var(--muted);font-size:.75rem}

    /* Responsive */
    @media(max-width:768px){
      .stats{grid-template-columns:repeat(2,1fr)}
      .stat-num{font-size:1.5rem}
      table{font-size:.75rem}
      th,td{padding:8px 10px}
      .container{padding:12px}
    }
  </style>
</head>
<body>
  <!-- Topbar -->
  <div class="topbar">
    <h1>🎫 Panel de Administración</h1>
    <span class="badge" id="last-update">—</span>
  </div>

  <div class="container">
    <!-- Tabs -->
    <div class="tabs">
      <div class="tab active" data-tab="attendees">👥 Asistentes</div>
      <div class="tab" data-tab="invitations">🎟️ Invitaciones</div>
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
        <input type="text" id="search" placeholder="Buscar nombre, apellido, documento o código...">
        <select id="filter-status">
          <option value="all">Todos</option>
          <option value="in">Ingresaron</option>
          <option value="pending">Pendientes</option>
        </select>
      </div>
      <div class="loading" id="loading">Cargando datos...</div>
      <table id="table" style="display:none">
        <thead>
          <tr><th>QR</th><th>Nombre</th><th>Apellido</th><th>Documento</th><th>Código Inv.</th><th>Invitado por</th><th>Estado</th><th>Ingreso</th></tr>
        </thead>
        <tbody id="tbody"></tbody>
      </table>
      <div class="no-data" id="no-data" style="display:none">No hay asistentes registrados</div>
    </div>

    <!-- TAB: Invitaciones -->
    <div class="tab-content" id="tab-invitations">
      <div class="stats">
        <div class="stat s-total"><div class="stat-num" id="inv-total">—</div><div class="stat-label">Total</div></div>
        <div class="stat s-inv-used"><div class="stat-num" id="inv-used">—</div><div class="stat-label">Usados</div></div>
        <div class="stat s-inv-unused"><div class="stat-num" id="inv-unused">—</div><div class="stat-label">Disponibles</div></div>
      </div>
      <div class="inv-toolbar">
        <button class="btn btn-success" id="btn-generate">+ Crear Código</button>
        <select id="inv-filter">
          <option value="all">Todos</option>
          <option value="unused">Disponibles</option>
          <option value="used">Usados</option>
        </select>
      </div>
      <div class="loading" id="inv-loading">Cargando invitaciones...</div>
      <table id="inv-table" style="display:none">
        <thead>
          <tr><th>Código</th><th>Estado</th><th>Creado</th><th>Usado por</th><th>Acciones</th></tr>
        </thead>
        <tbody id="inv-tbody"></tbody>
      </table>
      <div class="no-data" id="inv-no-data" style="display:none">No hay códigos. Hacé clic en <strong>"+ Crear Código"</strong>.</div>
      <div class="pagination" id="inv-pagination"></div>
    </div>
  </div>

  <!-- QR Modal -->
  <div class="modal" id="qr-modal">
    <div class="modal-content">
      <img id="modal-qr-img" src="" alt="QR">
      <p id="modal-name" style="font-weight:600"></p>
      <button class="btn" onclick="this.closest('.modal').classList.remove('open')">Cerrar</button>
    </div>
  </div>

  <!-- Generate Codes Modal -->
  <div class="modal" id="generate-modal">
    <div class="modal-content">
      <p style="font-weight:700;font-size:1.05rem;margin-bottom:16px">🎟️ Crear Códigos</p>
      <div style="display:flex;gap:10px;align-items:center;justify-content:center;margin-bottom:18px">
        <label for="gen-count" style="font-size:.82rem;color:var(--muted)">Cantidad:</label>
        <input type="number" id="gen-count" value="10" min="1" max="100"
               style="width:70px;background:#0f172a;border:1px solid var(--border);border-radius:8px;
                      color:var(--text);padding:8px;text-align:center;font-size:.9rem">
      </div>
      <button class="btn" id="btn-confirm-generate" style="width:100%;margin-bottom:10px">Generar</button>
      <button class="btn" style="width:100%;background:transparent;border:1px solid var(--border)" id="btn-close-generate">Cerrar</button>
      <div id="generated-codes" style="display:none">
        <div class="gen-codes-box" id="gen-codes-list"></div>
        <div style="margin-top:10px;display:flex;gap:8px">
          <button class="btn btn-sm" style="flex:1" id="btn-copy-all">📋 Copiar</button>
          <button class="btn btn-sm btn-success" style="flex:1" id="btn-whatsapp">💬 WhatsApp</button>
        </div>
      </div>
    </div>
  </div>

  <!-- Toast -->
  <div class="toast" id="toast"></div>

  <script>
/**
 * Admin Dashboard - JavaScript Module
 * Control de Acceso - Panel de Administración
 */

(function() {
  'use strict';

  // ── State ─────────────────────────────────────────────────────────────────
  var state = {
    attendees: [],
    invitations: [],
    invPage: 1,
    lastGeneratedCodes: [],
    capacity: 1800
  };

  // ── Helpers ────────────────────────────────────────────────────────────────
  function $(sel) { return document.querySelector(sel); }
  function $$(sel) { return document.querySelectorAll(sel); }
  function setText(id, val) { var el = $(id); if (el) el.textContent = val; }
  function esc(s) { var d = document.createElement('div'); d.textContent = s || ''; return d.innerHTML; }

  function showToast(msg, type) {
    var t = $('#toast');
    if (!t) return;
    t.className = 'toast show toast-' + (type || 'success');
    t.textContent = msg;
    clearTimeout(t._timeout);
    t._timeout = setTimeout(function() { t.className = 'toast'; }, 3000);
  }

  // ── Tabs ───────────────────────────────────────────────────────────────────
  function switchTab(name) {
    $$('.tab').forEach(function(t) { t.classList.remove('active'); });
    $$('.tab-content').forEach(function(tc) { tc.classList.remove('active'); });
    var tabEl = document.querySelector('.tab[data-tab="' + name + '"]');
    var contentEl = $('#tab-' + name);
    if (tabEl) tabEl.classList.add('active');
    if (contentEl) contentEl.classList.add('active');
    if (name === 'invitations') { state.invPage = 1; loadInvitations(); }
  }

  // ── Attendees ──────────────────────────────────────────────────────────────
  function loadData() {
    fetch('/api/admin/data')
      .then(function(r) { return r.json(); })
      .then(function(json) {
        state.attendees = json.attendees || [];
        renderStats(json);
        renderAttendees(state.attendees);
        setText('last-update', 'Actualizado: ' + new Date().toLocaleTimeString());
      })
      .catch(function(err) {
        console.error('Error loading data:', err);
        $('#loading').style.display = 'none';
        $('#no-data').style.display = 'block';
        $('#no-data').textContent = 'Error al cargar datos. Reintentando...';
      });
  }

  function renderStats(json) {
    var total = json.total || 0;
    var ingresaron = json.ingresaron || 0;
    setText('s-total', total);
    setText('s-ingresaron', ingresaron);
    setText('s-pendientes', total - ingresaron);
    setText('s-lugares', Math.max(0, state.capacity - ingresaron));
  }

  function renderAttendees(data) {
    var tbody = $('#tbody');
    var table = $('#table');
    var loading = $('#loading');
    var noData = $('#no-data');
    if (!tbody || !table || !loading || !noData) return;

    loading.style.display = 'none';

    if (!data || !data.length) {
      noData.style.display = 'block';
      table.style.display = 'none';
      return;
    }

    noData.style.display = 'none';
    table.style.display = 'table';

    var html = [];
    for (var i = 0; i < data.length; i++) {
      var a = data[i];
      var statusCls = a.estado_ingreso ? 'status-in' : 'status-pending';
      var statusTxt = a.estado_ingreso ? '✓ Ingresó' : 'Pendiente';
      var fecha = a.fecha_ingreso || '—';
      var invCode = a.invitation_code || '—';
      var fullName = (a.nombre || '') + ' ' + (a.apellido || '');
      var qrToken = a.qr_token || a.hash_unique || '';

      html.push('<tr>');
      html.push('<td><span class="qr-mini" data-hash="' + esc(qrToken) + '" data-name="' + esc(fullName) + '">📱</span></td>');
      html.push('<td>' + esc(a.nombre) + '</td>');
      html.push('<td>' + esc(a.apellido || '—') + '</td>');
      html.push('<td><code>' + esc(a.nro_documento || '—') + '</code></td>');
      html.push('<td><code class="inv-code-cell">' + esc(invCode) + '</code></td>');
      html.push('<td>' + esc(a.invitado_por || '—') + '</td>');
      html.push('<td><span class="status-badge ' + statusCls + '">' + statusTxt + '</span></td>');
      html.push('<td>' + fecha + '</td>');
      html.push('</tr>');
    }
    tbody.innerHTML = html.join('');

    // Bind QR click events
    tbody.querySelectorAll('.qr-mini').forEach(function(el) {
      el.addEventListener('click', function() {
        showQR(el.getAttribute('data-hash'), el.getAttribute('data-name'));
      });
    });
  }

  function showQR(hash, name) {
    if (!hash) return;
    fetch('/admin/qr/' + encodeURIComponent(hash))
      .then(function(r) {
        if (!r.ok) throw new Error('QR not found');
        return r.blob();
      })
      .then(function(blob) {
        $('#modal-qr-img').src = URL.createObjectURL(blob);
        $('#modal-name').textContent = name || '';
        $('#qr-modal').classList.add('open');
      })
      .catch(function() {
        showToast('No se encontró el QR', 'error');
      });
  }

  function applyFilters() {
    var q = ($('#search').value || '').toLowerCase();
    var f = $('#filter-status').value;
    var data = state.attendees.slice();

    if (q) {
      data = data.filter(function(a) {
        return (a.nombre || '').toLowerCase().indexOf(q) >= 0 ||
               (a.apellido || '').toLowerCase().indexOf(q) >= 0 ||
               (a.nro_documento || '').toLowerCase().indexOf(q) >= 0 ||
               (a.invitation_code || '').toLowerCase().indexOf(q) >= 0;
      });
    }
    if (f === 'in') data = data.filter(function(a) { return a.estado_ingreso; });
    if (f === 'pending') data = data.filter(function(a) { return !a.estado_ingreso; });
    renderAttendees(data);
  }

  // ── Invitations ────────────────────────────────────────────────────────────
  function loadInvitations() {
    var loading = $('#inv-loading');
    var table = $('#inv-table');
    var noData = $('#inv-no-data');
    if (loading) loading.style.display = 'block';
    if (table) table.style.display = 'none';
    if (noData) noData.style.display = 'none';

    var filter = $('#inv-filter').value;
    var url = '/admin/api/invitations?page=' + state.invPage + '&status_filter=' + filter;

    fetch(url)
      .then(function(r) { return r.json(); })
      .then(function(json) {
        if (loading) loading.style.display = 'none';
        setText('inv-total', json.total);
        setText('inv-used', json.used);
        setText('inv-unused', json.unused);

        state.invitations = json.codes || [];

        if (!json.codes || !json.codes.length) {
          if (noData) noData.style.display = 'block';
          $('#inv-pagination').innerHTML = '';
          return;
        }

        if (table) table.style.display = 'table';
        var html = [];
        for (var i = 0; i < json.codes.length; i++) {
          var c = json.codes[i];
          var statusCls = c.used ? 'status-used' : 'status-unused';
          var statusTxt = c.used ? '✓ Usado' : 'Disponible';

          html.push('<tr>');
          html.push('<td><code class="inv-code">' + esc(c.code) + '</code> ' +
            '<button class="btn-icon btn-copy" data-code="' + esc(c.code) + '" title="Copiar">📋</button></td>');
          html.push('<td><span class="status-badge ' + statusCls + '">' + statusTxt + '</span></td>');
          html.push('<td>' + (c.creado_en || '—') + '</td>');
          html.push('<td>' + (c.attendee_name ? '<span class="attendee-link">' + esc(c.attendee_name) + '</span>' : '—') + '</td>');

          if (c.used) {
            html.push('<td><span class="text-muted">—</span></td>');
          } else {
            html.push('<td class="inv-actions">');
            html.push('<button class="btn btn-sm btn-danger btn-revoke" data-id="' + c.id + '" data-code="' + esc(c.code) + '">Revocar</button>');
            html.push('<button class="btn btn-sm btn-warning btn-delete" data-id="' + c.id + '" data-code="' + esc(c.code) + '">Eliminar</button>');
            html.push('</td>');
          }
          html.push('</tr>');
        }
        $('#inv-tbody').innerHTML = html.join('');

        // Bind events
        $$('#inv-tbody .btn-copy').forEach(function(btn) {
          btn.addEventListener('click', function() { copyCode(btn.getAttribute('data-code')); });
        });
        $$('#inv-tbody .btn-revoke').forEach(function(btn) {
          btn.addEventListener('click', function() {
            revokeCode(parseInt(btn.getAttribute('data-id')), btn.getAttribute('data-code'));
          });
        });
        $$('#inv-tbody .btn-delete').forEach(function(btn) {
          btn.addEventListener('click', function() {
            deleteCode(parseInt(btn.getAttribute('data-id')), btn.getAttribute('data-code'));
          });
        });

        // Pagination
        var totalPages = json.pages || 1;
        var pagHtml = '<button class="btn btn-sm" ' + (json.page <= 1 ? 'disabled' : '') + ' data-page="' + (json.page - 1) + '">← Anterior</button>';
        pagHtml += '<span>Pág ' + json.page + ' de ' + totalPages + '</span>';
        pagHtml += '<button class="btn btn-sm" ' + (json.page >= totalPages ? 'disabled' : '') + ' data-page="' + (json.page + 1) + '">Siguiente →</button>';
        $('#inv-pagination').innerHTML = pagHtml;

        $$('#inv-pagination button[data-page]').forEach(function(btn) {
          btn.addEventListener('click', function() {
            state.invPage = parseInt(btn.getAttribute('data-page'));
            loadInvitations();
          });
        });
      })
      .catch(function(err) {
        console.error('Error loading invitations:', err);
        if (loading) loading.style.display = 'none';
      });
  }

  function copyCode(code) {
    if (navigator.clipboard) {
      navigator.clipboard.writeText(code).then(function() {
        showToast('Código copiado: ' + code);
      });
    }
  }

  function revokeCode(id, code) {
    if (!confirm('¿Revocar el código ' + code + '?')) return;
    fetch('/admin/api/invitations/' + id + '/revoke', { method: 'POST' })
      .then(function(r) {
        if (r.ok) { loadInvitations(); showToast('Código ' + code + ' revocado'); }
        else { showToast('Error al revocar', 'error'); }
      });
  }

  function deleteCode(id, code) {
    if (!confirm('¿Eliminar el código ' + code + '?')) return;
    fetch('/admin/api/invitations/' + id, { method: 'DELETE' })
      .then(function(r) {
        if (r.ok) { loadInvitations(); showToast('Código ' + code + ' eliminado'); }
        else { showToast('Error al eliminar', 'error'); }
      });
  }

  // ── Generate Codes ─────────────────────────────────────────────────────────
  function openGenerateModal() {
    $('#generate-modal').classList.add('open');
    $('#generated-codes').style.display = 'none';
  }

  function closeGenerateModal() {
    $('#generate-modal').classList.remove('open');
  }

  function doGenerate() {
    console.log('[Generate] Button clicked');
    var count = parseInt($('#gen-count').value) || 1;
    if (count < 1) count = 1;
    if (count > 100) count = 100;
    console.log('[Generate] Count:', count);

    fetch('/admin/api/invitations/generate?count=' + count, { method: 'POST' })
      .then(function(r) {
        console.log('[Generate] Response status:', r.status);
        if (!r.ok) {
          return r.text().then(function(text) {
            throw new Error('HTTP ' + r.status + ': ' + text);
          });
        }
        return r.json();
      })
      .then(function(json) {
        console.log('[Generate] Success:', json);
        state.lastGeneratedCodes = json.codes || [];
        var html = [];
        for (var i = 0; i < state.lastGeneratedCodes.length; i++) {
          var code = state.lastGeneratedCodes[i];
          html.push('<div class="gen-code-item">' +
            '<code class="inv-code">' + esc(code) + '</code>' +
            '<button class="btn-icon btn-copy-gen" data-code="' + esc(code) + '">📋</button>' +
            '</div>');
        }
        $('#gen-codes-list').innerHTML = html.join('');
        $('#generated-codes').style.display = 'block';
        loadInvitations();
        showToast(json.count + ' códigos generados');

        $$('.btn-copy-gen').forEach(function(btn) {
          btn.addEventListener('click', function() { copyCode(btn.getAttribute('data-code')); });
        });
      })
      .catch(function(err) {
        console.error('[Generate] Error:', err);
        showToast('Error: ' + err.message, 'error');
      });
  }

  function copyAllCodes() {
    var text = state.lastGeneratedCodes.join('\n');
    if (navigator.clipboard) {
      navigator.clipboard.writeText(text).then(function() {
        showToast('Todos los códigos copiados');
      });
    }
  }

  function shareAllWhatsApp() {
    var text = '🎫 *Código de Invitación al Evento*\n\n';
    text += 'Usá este código para registrarte:\n\n';
    for (var i = 0; i < state.lastGeneratedCodes.length; i++) {
      text += '▸ ' + state.lastGeneratedCodes[i] + '\n';
    }
    text += '\nIngresá a ' + window.location.origin + '/register para completar tu registro.';
    window.open('https://wa.me/?text=' + encodeURIComponent(text), '_blank');
  }

  // ── Init ──────────────────────────────────────────────────────────────────
  function init() {
    // Tab switching
    $$('.tab[data-tab]').forEach(function(tab) {
      tab.addEventListener('click', function() {
        switchTab(tab.getAttribute('data-tab'));
      });
    });

    // Modal close on backdrop click
    $$('.modal').forEach(function(modal) {
      modal.addEventListener('click', function(e) {
        if (e.target === modal) modal.classList.remove('open');
      });
    });

    // Search & filter
    var searchEl = $('#search');
    if (searchEl) searchEl.addEventListener('input', applyFilters);

    var filterEl = $('#filter-status');
    if (filterEl) filterEl.addEventListener('change', applyFilters);

    var invFilterEl = $('#inv-filter');
    if (invFilterEl) {
      invFilterEl.addEventListener('change', function() {
        state.invPage = 1;
        loadInvitations();
      });
    }

    // Generate codes modal buttons
    var btnOpen = $('#btn-generate');
    var btnClose = $('#btn-close-generate');
    var btnConfirm = $('#btn-confirm-generate');
    var btnCopyAll = $('#btn-copy-all');
    var btnWA = $('#btn-whatsapp');

    console.log('[Init] Buttons found:', {
      open: !!btnOpen,
      close: !!btnClose,
      confirm: !!btnConfirm,
      copyAll: !!btnCopyAll,
      whatsapp: !!btnWA
    });

    if (btnOpen) btnOpen.addEventListener('click', openGenerateModal);
    if (btnClose) btnClose.addEventListener('click', closeGenerateModal);
    if (btnConfirm) btnConfirm.addEventListener('click', doGenerate);
    if (btnCopyAll) btnCopyAll.addEventListener('click', copyAllCodes);
    if (btnWA) btnWA.addEventListener('click', shareAllWhatsApp);

    console.log('[Init] Admin dashboard initialized');

    // Load data
    loadData();
    setInterval(loadData, 30000);
  }

  // Start when DOM is ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

})();

  </script>
</body>
</html>"""


@router.get("/admin", response_class=HTMLResponse)
async def admin_dashboard(request: Request):
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/admin/login", status_code=302)
    return ADMIN_HTML


# ── API Endpoints ──────────────────────────────────────────────────────────

@router.get("/api/admin/data")
async def admin_data(user: AdminUser = Depends(require_user)):
    async with async_session() as session:
        total = (await session.execute(select(func.count(Attendee.id)))).scalar() or 0
        ingresaron = (await session.execute(
            select(func.count(Attendee.id)).where(Attendee.estado_ingreso.is_(True))
        )).scalar() or 0

        stmt = select(Attendee).order_by(desc(Attendee.id))
        result = await session.execute(stmt)
        attendees = result.scalars().all()

        # Lookup invitation codes
        attendee_codes = {}
        for a in attendees:
            if a.invitation_code_id:
                cs = select(InvitationCode).where(InvitationCode.id == a.invitation_code_id)
                cr = await session.execute(cs)
                c = cr.scalar_one_or_none()
                if c:
                    attendee_codes[a.id] = c.code

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
                "invitado_por": a.invitado_por,
                "qr_token": a.qr_token,
                "hash_unique": a.hash_unique,
                "estado_ingreso": a.estado_ingreso,
                "fecha_ingreso": a.fecha_ingreso.strftime("%d/%m/%Y %H:%M") if a.fecha_ingreso else None,
                "invitation_code": attendee_codes.get(a.id, ""),
            }
            for a in attendees
        ],
    }


@router.get("/admin/qr/{hash_id}")
async def admin_qr(hash_id: str, user: AdminUser = Depends(require_user)):
    async with async_session() as session:
        stmt = select(Attendee).where(
            (Attendee.qr_token == hash_id.upper()) | (Attendee.hash_unique == hash_id.upper())
        )
        result = await session.execute(stmt)
        attendee = result.scalar_one_or_none()
    if not attendee:
        return Response(content="No encontrado", status_code=404)
    return Response(content=_make_qr(attendee.qr_token), media_type="image/png")


# ── Invitation Code Management ──────────────────────────────────────────

@router.post("/admin/api/invitations/generate")
async def generate_invitation_codes(count: int = Query(1, ge=1, le=100), user: AdminUser = Depends(require_user)):
    codes = []
    async with async_session() as session:
        for _ in range(count):
            code_str = _generate_invitation_code()
            session.add(InvitationCode(code=code_str))
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
    async with async_session() as session:
        total = (await session.execute(select(func.count(InvitationCode.id)))).scalar() or 0
        used_count = (await session.execute(
            select(func.count(InvitationCode.id)).where(InvitationCode.used.is_(True))
        )).scalar() or 0
        unused_count = total - used_count

        stmt = select(InvitationCode).order_by(desc(InvitationCode.creado_en))
        if status_filter == "used":
            stmt = stmt.where(InvitationCode.used.is_(True))
        elif status_filter == "unused":
            stmt = stmt.where(InvitationCode.used.is_(False))

        offset = (page - 1) * per_page
        stmt = stmt.offset(offset).limit(per_page)
        result = await session.execute(stmt)
        codes = result.scalars().all()

        # Resolve attendee names
        attendee_names = {}
        for c in codes:
            if c.attendee_id:
                att_s = select(Attendee).where(Attendee.id == c.attendee_id)
                att_r = await session.execute(att_s)
                att = att_r.scalar_one_or_none()
                if att:
                    attendee_names[c.id] = att.nombre + (" " + att.apellido if att.apellido else "")

        total_pages = max(1, (total + per_page - 1) // per_page)

        return {
            "total": total, "used": used_count, "unused": unused_count,
            "page": page, "per_page": per_page, "pages": total_pages,
            "codes": [
                {
                    "id": c.id, "code": c.code, "used": c.used,
                    "creado_en": c.creado_en.strftime("%d/%m/%Y %H:%M") if c.creado_en else None,
                    "usado_en": c.usado_en.strftime("%d/%m/%Y %H:%M") if c.usado_en else None,
                    "attendee_name": attendee_names.get(c.id, ""),
                }
                for c in codes
            ],
        }


@router.post("/admin/api/invitations/{code_id}/revoke")
async def revoke_invitation_code(code_id: int, user: AdminUser = Depends(require_user)):
    async with async_session() as session:
        stmt = select(InvitationCode).where(InvitationCode.id == code_id)
        result = await session.execute(stmt)
        invitation = result.scalar_one_or_none()
        if not invitation:
            return Response(content="No encontrado", status_code=404)
        if invitation.used:
            return Response(content="Ya utilizado", status_code=409)
        invitation.used = True
        invitation.usado_en = datetime.now(timezone.utc)
        await session.commit()
    return {"success": True}


@router.delete("/admin/api/invitations/{code_id}")
async def delete_invitation_code(code_id: int, user: AdminUser = Depends(require_user)):
    async with async_session() as session:
        stmt = select(InvitationCode).where(InvitationCode.id == code_id)
        result = await session.execute(stmt)
        invitation = result.scalar_one_or_none()
        if not invitation:
            return Response(content="No encontrado", status_code=404)
        if invitation.used:
            return Response(content="Ya utilizado", status_code=409)
        await session.delete(invitation)
        await session.commit()
    return {"success": True}
