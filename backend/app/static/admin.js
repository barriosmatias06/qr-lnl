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
    var count = parseInt($('#gen-count').value) || 1;
    if (count < 1) count = 1;
    if (count > 100) count = 100;

    fetch('/admin/api/invitations/generate?count=' + count, { method: 'POST' })
      .then(function(r) { return r.json(); })
      .then(function(json) {
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

        // Bind copy buttons
        $$('.btn-copy-gen').forEach(function(btn) {
          btn.addEventListener('click', function() { copyCode(btn.getAttribute('data-code')); });
        });
      })
      .catch(function() {
        showToast('Error al generar códigos', 'error');
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
    if (btnOpen) btnOpen.addEventListener('click', openGenerateModal);

    var btnClose = $('#btn-close-generate');
    if (btnClose) btnClose.addEventListener('click', closeGenerateModal);

    var btnConfirm = $('#btn-confirm-generate');
    if (btnConfirm) btnConfirm.addEventListener('click', doGenerate);

    var btnCopyAll = $('#btn-copy-all');
    if (btnCopyAll) btnCopyAll.addEventListener('click', copyAllCodes);

    var btnWA = $('#btn-whatsapp');
    if (btnWA) btnWA.addEventListener('click', shareAllWhatsApp);

    console.log('Admin dashboard initialized');

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
