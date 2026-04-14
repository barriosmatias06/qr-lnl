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

  // Check user role
  var currentUser = window.CURRENT_USER || {role: 'scanner_only'};
  var isSuperAdmin = currentUser.role === 'super_admin';

  // ── Helpers ────────────────────────────────────────────────────────────────
  function $(sel) { return document.querySelector(sel); }
  function $$(sel) { return document.querySelectorAll(sel); }
  function setText(id, val) {
    var el = document.getElementById(id);
    console.log('[setText]', id, '=', val, 'found:', !!el);
    if (el) el.textContent = val;
  }
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

  // Hide admin tabs for scanner_only users
  function applyRoleRestrictions() {
    if (!isSuperAdmin) {
      // Hide invitations tab
      var invTab = document.querySelector('.tab[data-tab="invitations"]');
      var invContent = $('#tab-invitations');
      if (invTab) invTab.style.display = 'none';
      if (invContent) invContent.style.display = 'none';

      // Hide generate button
      var btnGenerate = $('#btn-generate');
      if (btnGenerate) btnGenerate.style.display = 'none';

      // Hide revoke/delete buttons (handled in render)
    }
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
    console.log('[Stats] Total:', total, 'Ingresaron:', ingresaron);
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

      // VIP badge
      var tipoBadge = '';
      if (a.tipo_acceso === 'VIP') {
        var pagoCls = a.pago_confirmado ? 'status-in' : 'status-pending';
        var pagoTxt = a.pago_confirmado ? '✓ Pagado' : 'Pendiente';
        tipoBadge = '<span class="status-badge" style="background:rgba(234,179,8,.15);color:var(--yellow)">VIP</span> ' +
                    '<span class="status-badge ' + pagoCls + '">' + pagoTxt + '</span>';
      }

      html.push('<tr>');
      html.push('<td><span class="qr-mini" data-hash="' + esc(qrToken) + '" data-name="' + esc(fullName) + '">📱</span></td>');
      html.push('<td>' + esc(a.nombre) + '</td>');
      html.push('<td>' + esc(a.apellido || '—') + '</td>');
      html.push('<td><code>' + esc(a.nro_documento || '—') + '</code></td>');
      html.push('<td>' + tipoBadge + '</td>');
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
    console.log('[Invitations] Loading page:', state.invPage);
    var loading = $('#inv-loading');
    var table = $('#inv-table');
    var noData = $('#inv-no-data');
    if (loading) loading.style.display = 'block';
    if (table) table.style.display = 'none';
    if (noData) noData.style.display = 'none';

    var filter = $('#inv-filter').value;
    var url = '/admin/api/invitations?page=' + state.invPage + '&status_filter=' + filter;
    console.log('[Invitations] Fetching:', url);

    fetch(url)
      .then(function(r) {
        console.log('[Invitations] Response status:', r.status);
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return r.json();
      })
      .then(function(json) {
        console.log('[Invitations] Data:', json);
        if (loading) loading.style.display = 'none';

        var total = json.total || 0;
        var used = json.used || 0;
        var unused = json.unused || 0;
        console.log('[Invitations] Setting stats - total:', total, 'used:', used, 'unused:', unused);

        setText('inv-total', total);
        setText('inv-used', used);
        setText('inv-unused', unused);

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
          } else if (!isSuperAdmin) {
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

    // Get selected type
    var tipoAcceso = 'GENERAL';
    var vipRadio = document.querySelector('input[name="gen-type"][value="VIP"]');
    var generalRadio = document.querySelector('input[name="gen-type"][value="GENERAL"]');
    if (vipRadio && vipRadio.checked) tipoAcceso = 'VIP';
    else if (generalRadio && generalRadio.checked) tipoAcceso = 'GENERAL';

    console.log('[Generate] Count:', count, 'Type:', tipoAcceso);

    var url = '/admin/api/invitations/generate?count=' + count + '&tipo_acceso=' + tipoAcceso;

    fetch(url, { method: 'POST' })
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
        // Store codes - for VIP they have qr_token too
        state.lastGeneratedCodes = json.attendees && json.attendees.length ? json.attendees : json.codes;
        var html = [];
        var codesToDisplay = Array.isArray(state.lastGeneratedCodes) ? state.lastGeneratedCodes : [];
        for (var i = 0; i < codesToDisplay.length; i++) {
          var item = codesToDisplay[i];
          var code = typeof item === 'string' ? item : item.code;
          var qrToken = typeof item === 'object' ? item.qr_token : null;
          var displayHtml = qrToken
            ? '<code class="inv-code">' + esc(code) + '</code> <span class="text-muted">QR: ' + esc(qrToken.substring(0,8)) + '...</span>'
            : '<code class="inv-code">' + esc(code) + '</code>';
          html.push('<div class="gen-code-item">' +
            displayHtml +
            '<button class="btn-icon btn-copy-gen" data-code="' + esc(code) + '">📋</button>' +
            '</div>');
        }
        $('#gen-codes-list').innerHTML = html.join('');
        $('#generated-codes').style.display = 'block';
        loadInvitations();
        showToast(json.count + ' códigos generados' + (json.tipo_acceso === 'VIP' ? ' (VIP)' : ''));

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
    var text = '';
    // Check if VIP codes were generated
    if (state.lastGeneratedCodes.length > 0 && state.lastGeneratedCodes[0].qr_token) {
      // VIP codes - share QR tokens
      text = '🎫 *Entrada VIP al Evento*\n\n';
      text += 'Tu código QR para ingresar:\n\n';
      for (var i = 0; i < state.lastGeneratedCodes.length; i++) {
        var code = state.lastGeneratedCodes[i];
        var qrUrl = window.location.origin + '/?id=' + code.qr_token;
        text += '▸ ' + code.code + ' → ' + qrUrl + '\n';
      }
      text += '\n⚠️ *Importante:* Completá el pago al escanear tu QR para activar tu entrada.';
    } else {
      // General codes
      text = '🎫 *Código de Invitación al Evento*\n\n';
      text += 'Usá este código para registrarte:\n\n';
      for (var i = 0; i < state.lastGeneratedCodes.length; i++) {
        text += '▸ ' + state.lastGeneratedCodes[i] + '\n';
      }
      text += '\nIngresá a ' + window.location.origin + '/register para completar tu registro.';
    }
    window.open('https://wa.me/?text=' + encodeURIComponent(text), '_blank');
  }

  // ── Init ──────────────────────────────────────────────────────────────────
  function init() {
    // Apply role-based restrictions
    applyRoleRestrictions();

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
