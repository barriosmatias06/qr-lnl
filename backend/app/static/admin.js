/**
 * Admin Dashboard JavaScript
 */

var ALL_DATA = [];
var INV_DATA = [];
var invPage = 1;
var lastGeneratedCodes = [];
var CAPACITY = 1800;

// ── Tabs ──────────────────────────────────────────────────────────────────
function switchTab(name) {
  document.querySelectorAll('.tab').forEach(function(t) { t.classList.remove('active'); });
  document.querySelectorAll('.tab-content').forEach(function(tc) { tc.classList.remove('active'); });
  var tabEl = document.querySelector('.tab[data-tab="' + name + '"]');
  if (tabEl) tabEl.classList.add('active');
  var contentEl = document.getElementById('tab-' + name);
  if (contentEl) contentEl.classList.add('active');
  if (name === 'invitations') { invPage = 1; loadInvitations(); }
}

// ── Attendees ─────────────────────────────────────────────────────────────
function loadData() {
  fetch('/api/admin/data')
    .then(function(r) { return r.json(); })
    .then(function(json) {
      ALL_DATA = json.attendees || [];
      renderStats(json);
      renderTable(ALL_DATA);
      var el = document.getElementById('last-update');
      if (el) el.textContent = 'Actualizado: ' + new Date().toLocaleTimeString();
    })
    .catch(function() {});
}

function renderStats(json) {
  var total = json.total || 0;
  var ingresaron = json.ingresaron || 0;
  setText('s-total', total);
  setText('s-ingresaron', ingresaron);
  setText('s-pendientes', total - ingresaron);
  setText('s-lugares', Math.max(0, CAPACITY - ingresaron));
}

function renderTable(data) {
  var tbody = document.getElementById('tbody');
  var table = document.getElementById('table');
  var loading = document.getElementById('loading');
  var noData = document.getElementById('no-data');
  if (!loading || !table || !noData || !tbody) return;

  loading.style.display = 'none';

  if (!data || !data.length) {
    noData.style.display = 'block';
    table.style.display = 'none';
    return;
  }
  noData.style.display = 'none';
  table.style.display = 'table';

  var rows = [];
  for (var i = 0; i < data.length; i++) {
    var a = data[i];
    var statusHtml = a.estado_ingreso
      ? '<span class="status in">✓ Ingresó</span>'
      : '<span class="status pending">Pendiente</span>';
    var fecha = a.fecha_ingreso || '—';
    var invCode = a.invitation_code || '—';
    var fullName = (a.nombre || '') + ' ' + (a.apellido || '');
    var qrToken = a.qr_token || a.hash_unique || '';

    rows.push('<tr>' +
      '<td><span class="qr-mini" onclick="showQR(\'' + esc(qrToken) + '\',\'' + esc(fullName) + '\')">📱</span></td>' +
      '<td>' + esc(a.nombre) + '</td>' +
      '<td>' + esc(a.apellido || '—') + '</td>' +
      '<td>' + esc(a.nro_documento || '—') + '</td>' +
      '<td><span class="inv-code">' + esc(invCode) + '</span></td>' +
      '<td>' + esc(a.invitado_por || '—') + '</td>' +
      '<td>' + statusHtml + '</td>' +
      '<td>' + fecha + '</td>' +
      '</tr>');
  }
  tbody.innerHTML = rows.join('');
}

function showQR(hash, name) {
  fetch('/admin/qr/' + encodeURIComponent(hash))
    .then(function(r) { return r.blob(); })
    .then(function(blob) {
      var img = document.getElementById('modal-qr-img');
      var nameEl = document.getElementById('modal-name');
      if (img) img.src = URL.createObjectURL(blob);
      if (nameEl) nameEl.textContent = name;
      var modal = document.getElementById('qr-modal');
      if (modal) modal.classList.add('open');
    });
}

// ── Search & Filter ───────────────────────────────────────────────────────
function applyFilters() {
  var q = (document.getElementById('search').value || '').toLowerCase();
  var f = document.getElementById('filter-status').value;
  var data = ALL_DATA.slice();

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
  renderTable(data);
}

// ── Invitations ───────────────────────────────────────────────────────────
function loadInvitations() {
  var loading = document.getElementById('inv-loading');
  var table = document.getElementById('inv-table');
  var noData = document.getElementById('inv-no-data');
  if (loading) loading.style.display = 'block';
  if (table) table.style.display = 'none';
  if (noData) noData.style.display = 'none';

  var filter = document.getElementById('inv-filter').value;
  fetch('/admin/api/invitations?page=' + invPage + '&status_filter=' + filter)
    .then(function(r) { return r.json(); })
    .then(function(json) {
      if (loading) loading.style.display = 'none';

      setText('inv-total', json.total);
      setText('inv-used', json.used);
      setText('inv-unused', json.unused);

      INV_DATA = json.codes || [];

      if (!json.codes || !json.codes.length) {
        if (noData) noData.style.display = 'block';
        document.getElementById('inv-pagination').innerHTML = '';
        return;
      }

      if (table) table.style.display = 'table';
      var rows = [];
      for (var i = 0; i < json.codes.length; i++) {
        var c = json.codes[i];
        var st = c.used
          ? '<span class="status used">✓ Usado</span>'
          : '<span class="status unused">Disponible</span>';

        var actions = '';
        if (c.used) {
          actions = '<span style="color:var(--muted);font-size:.75rem">—</span>';
        } else {
          actions = '<div class="inv-actions">' +
            '<button class="btn btn-sm btn-danger" onclick="revokeCode(' + c.id + ',\'' + esc(c.code) + '\')">Revocar</button>' +
            '<button class="btn btn-sm" style="background:var(--orange)" onclick="deleteCode(' + c.id + ',\'' + esc(c.code) + '\')">Eliminar</button>' +
            '</div>';
        }

        var usedBy = c.attendee_name
          ? '<span style="color:var(--blue);font-size:.8rem">' + esc(c.attendee_name) + '</span>'
          : '—';

        rows.push('<tr>' +
          '<td><span class="inv-code">' + esc(c.code) + '</span>' +
            '<span class="copy-btn" onclick="copyCode(\'' + esc(c.code) + '\')" title="Copiar">📋</span></td>' +
          '<td>' + st + '</td>' +
          '<td>' + (c.creado_en || '—') + '</td>' +
          '<td>' + usedBy + '</td>' +
          '<td>' + actions + '</td>' +
          '</tr>');
      }
      document.getElementById('inv-tbody').innerHTML = rows.join('');

      // Pagination
      var totalPages = json.pages || 1;
      var pagHtml = '';
      pagHtml += '<button onclick="invPage=' + (json.page - 1) + ';loadInvitations()" ' +
        (json.page <= 1 ? 'disabled' : '') + '>← Anterior</button>';
      pagHtml += '<span>Pág ' + json.page + ' de ' + totalPages + '</span>';
      pagHtml += '<button onclick="invPage=' + (json.page + 1) + ';loadInvitations()" ' +
        (json.page >= totalPages ? 'disabled' : '') + '>Siguiente →</button>';
      document.getElementById('inv-pagination').innerHTML = pagHtml;
    })
    .catch(function() {
      if (loading) loading.style.display = 'none';
    });
}

function copyCode(code) {
  navigator.clipboard.writeText(code).then(function() {
    showToast('Código copiado: ' + code);
  });
}

function revokeCode(id, code) {
  if (!confirm('¿Revocar el código ' + code + '?')) return;
  fetch('/admin/api/invitations/' + id + '/revoke', { method: 'POST' })
    .then(function(r) {
      if (r.ok) { loadInvitations(); showToast('Código ' + code + ' revocado'); }
      else { alert('Error al revocar'); }
    });
}

function deleteCode(id, code) {
  if (!confirm('¿Eliminar el código ' + code + '?')) return;
  fetch('/admin/api/invitations/' + id, { method: 'DELETE' })
    .then(function(r) {
      if (r.ok) { loadInvitations(); showToast('Código ' + code + ' eliminado'); }
      else { alert('Error al eliminar'); }
    });
}

// ── Generate Codes ────────────────────────────────────────────────────────
function openGenerateModal() {
  var modal = document.getElementById('generate-modal');
  if (modal) modal.classList.add('open');
  var generated = document.getElementById('generated-codes');
  if (generated) generated.style.display = 'none';
}

function closeGenerateModal() {
  var modal = document.getElementById('generate-modal');
  if (modal) modal.classList.remove('open');
}

function doGenerate() {
  var count = parseInt(document.getElementById('gen-count').value) || 1;
  if (count < 1) count = 1;
  if (count > 100) count = 100;

  fetch('/admin/api/invitations/generate?count=' + count, { method: 'POST' })
    .then(function(r) { return r.json(); })
    .then(function(json) {
      lastGeneratedCodes = json.codes || [];
      var html = '';
      for (var i = 0; i < lastGeneratedCodes.length; i++) {
        var code = lastGeneratedCodes[i];
        html += '<div class="gen-code-item">' +
          '<span class="inv-code">' + esc(code) + '</span>' +
          '<span class="copy-btn" onclick="copyCode(\'' + esc(code) + '\')">📋</span>' +
          '</div>';
      }
      var listEl = document.getElementById('gen-codes-list');
      if (listEl) listEl.innerHTML = html;
      var genEl = document.getElementById('generated-codes');
      if (genEl) genEl.style.display = 'block';
      loadInvitations();
      showToast(json.count + ' códigos generados');
    });
}

function copyAllCodes() {
  var text = lastGeneratedCodes.join('\n');
  navigator.clipboard.writeText(text).then(function() {
    showToast('Todos los códigos copiados');
  });
}

function shareAllWhatsApp() {
  var text = '🎫 *Código de Invitación al Evento*\n\n';
  text += 'Usá este código para registrarte:\n\n';
  for (var i = 0; i < lastGeneratedCodes.length; i++) {
    text += '▸ ' + lastGeneratedCodes[i] + '\n';
  }
  text += '\nIngresá a ' + window.location.origin + '/register para completar tu registro.';
  window.open('https://wa.me/?text=' + encodeURIComponent(text), '_blank');
}

// ── Toast ─────────────────────────────────────────────────────────────────
function showToast(msg) {
  var t = document.getElementById('toast');
  if (!t) return;
  t.textContent = msg;
  t.classList.add('show');
  setTimeout(function() { t.classList.remove('show'); }, 2500);
}

// ── Helpers ───────────────────────────────────────────────────────────────
function esc(s) {
  var d = document.createElement('div');
  d.textContent = s;
  return d.innerHTML;
}

function setText(id, val) {
  var el = document.getElementById(id);
  if (el) el.textContent = val;
}

// ── Init ──────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', function() {
  loadData();
  setInterval(loadData, 30000);

  var searchEl = document.getElementById('search');
  if (searchEl) searchEl.addEventListener('input', applyFilters);

  var filterEl = document.getElementById('filter-status');
  if (filterEl) filterEl.addEventListener('change', applyFilters);

  var invFilterEl = document.getElementById('inv-filter');
  if (invFilterEl) invFilterEl.addEventListener('change', function() { invPage = 1; loadInvitations(); });
});
