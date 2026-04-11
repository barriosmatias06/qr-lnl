// ============================================================
// Code.gs — Backend de Control de Acceso para Evento
// Google Apps Script + Google Sheets
//
// Expone dos modos:
//   1. ?action=check&hash=XXX  → JSON  { status, nombre, fecha_ingreso }
//   2. ?action=stats            → JSON  { total, ingresaron, pendientes }
//   3. (sin action)             → sirve el HTML (Index.html)
//
// El frontend puede vivir en cualquier host (GitHub Pages, Netlify, etc.)
// y llama a este script via fetch(). CORS está habilitado por GAS
// automáticamente en respuestas de ContentService.
// ============================================================

const CONFIG = {
  SHEET_ID:   '1cHgLtGSs2mjKfzvnic7NTOp3YZJIs8F33pNgrjNaUSs',
  SHEET_NAME: 'Asistentes',
  COL: {
    ID:      1,  // A
    NOMBRE:  2,  // B
    EMAIL:   3,  // C
    HASH:    4,  // D
    ESTADO:  5,  // E
    FECHA:   6,  // F
  },
};

// ── Punto de entrada HTTP ──────────────────────────────────────────────────

function doGet(e) {
  const p      = (e && e.parameter) ? e.parameter : {};
  const action = p.action   || null;
  const cb     = p.callback || null;   // JSONP callback

  let data;

  if (action === 'check') {
    data = checkAttendee((p.hash || '').trim().toUpperCase());
  } else if (action === 'stats') {
    data = getStats();
  } else {
    // Sin action: servir HTML para testing rápido
    return HtmlService
      .createHtmlOutputFromFile('Index')
      .setTitle('Control de Acceso — Evento')
      .setXFrameOptionsMode(HtmlService.XFrameOptionsMode.ALLOWALL)
      .addMetaTag('viewport', 'width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no');
  }

  const json = JSON.stringify(data);

  // JSONP: si viene ?callback=fn, envolver en fn(...) para evitar CORS
  if (cb && /^[a-zA-Z_$][a-zA-Z0-9_$]*$/.test(cb)) {
    return ContentService
      .createTextOutput(`${cb}(${json})`)
      .setMimeType(ContentService.MimeType.JAVASCRIPT);
  }

  return ContentService
    .createTextOutput(json)
    .setMimeType(ContentService.MimeType.JSON);
}

// ── API ────────────────────────────────────────────────────────────────────

/**
 * Valida el hash de un asistente y registra su primer ingreso.
 * Usa LockService para evitar condiciones de carrera.
 */
function checkAttendee(hash) {
  if (!hash || hash.length < 8) {
    return { status: 'INVALID', message: 'Hash vacío o inválido' };
  }

  const lock = LockService.getScriptLock();
  const acquired = lock.tryLock(8000);
  if (!acquired) {
    return { status: 'ERROR', message: 'Sistema ocupado. Reintente.' };
  }

  try {
    const sheet = SpreadsheetApp
      .openById(CONFIG.SHEET_ID)
      .getSheetByName(CONFIG.SHEET_NAME);

    if (!sheet) throw new Error(`Pestaña "${CONFIG.SHEET_NAME}" no encontrada`);

    const lastRow = sheet.getLastRow();
    if (lastRow < 2) return { status: 'INVALID', message: 'Sin asistentes registrados' };

    // Un solo getValues() para toda la búsqueda
    const data = sheet.getRange(2, CONFIG.COL.HASH, lastRow - 1, 3).getValues();

    for (let i = 0; i < data.length; i++) {
      if (String(data[i][0]).trim().toUpperCase() !== hash) continue;

      const rowNum = i + 2;
      const estado = data[i][1];
      const fecha  = data[i][2];
      const nombre = String(sheet.getRange(rowNum, CONFIG.COL.NOMBRE).getValue());
      const yaIngreso = (estado === true || estado === 1 || estado === 'TRUE');

      if (yaIngreso) {
        return { status: 'ALREADY_USED', nombre, fecha_ingreso: String(fecha) };
      }

      const fechaFmt = Utilities.formatDate(
        new Date(), Session.getScriptTimeZone(), 'dd/MM/yyyy HH:mm:ss'
      );
      sheet.getRange(rowNum, CONFIG.COL.ESTADO).setValue(true);
      sheet.getRange(rowNum, CONFIG.COL.FECHA).setValue(fechaFmt);
      SpreadsheetApp.flush();

      return { status: 'WELCOME', nombre, fecha_ingreso: fechaFmt };
    }

    return { status: 'INVALID', message: 'Código no encontrado' };

  } catch (err) {
    console.error('checkAttendee error:', err.message);
    return { status: 'ERROR', message: err.message };
  } finally {
    lock.releaseLock();
  }
}

/**
 * Estadísticas de asistencia.
 */
function getStats() {
  try {
    const sheet = SpreadsheetApp
      .openById(CONFIG.SHEET_ID)
      .getSheetByName(CONFIG.SHEET_NAME);

    const lastRow = sheet.getLastRow();
    if (lastRow < 2) return { total: 0, ingresaron: 0, pendientes: 0 };

    const estados = sheet.getRange(2, CONFIG.COL.ESTADO, lastRow - 1, 1).getValues().flat();
    const ingresaron = estados.filter(v => v === true || v === 1 || v === 'TRUE').length;
    const total = lastRow - 1;

    return { total, ingresaron, pendientes: total - ingresaron };
  } catch (err) {
    return { status: 'ERROR', message: err.message };
  }
}

/**
 * Setup inicial — ejecutar una sola vez desde el editor de GAS.
 */
function setupSheet() {
  const ss = SpreadsheetApp.openById(CONFIG.SHEET_ID);
  let sheet = ss.getSheetByName(CONFIG.SHEET_NAME);
  if (!sheet) sheet = ss.insertSheet(CONFIG.SHEET_NAME);
  if (sheet.getLastRow() > 0) { console.log('Ya tiene datos.'); return; }

  const headers = ['ID', 'Nombre', 'Email', 'Hash_Unico', 'Estado_Ingreso', 'Fecha_Ingreso'];
  sheet.getRange(1, 1, 1, headers.length).setValues([headers]);
  sheet.setFrozenRows(1);
  sheet.getRange(1, 1, 1, headers.length)
    .setBackground('#1e293b').setFontColor('#f1f5f9').setFontWeight('bold');
  sheet.getRange('E2:E1801').insertCheckboxes();
  console.log('setupSheet() completado.');
}
