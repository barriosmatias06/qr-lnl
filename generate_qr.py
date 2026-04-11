#!/usr/bin/env python3
"""
Generador masivo de QR codes para control de acceso a eventos.

Genera:
  - N hashes UUID únicos (1 por asistente)
  - Imágenes PNG del código QR (en paralelo)
  - CSV listo para importar al Google Sheet

Uso básico — datos de muestra (1800 asistentes):
    python generate_qr.py

Con datos reales desde CSV (columnas Nombre, Email):
    python generate_qr.py --input mis_asistentes.csv

Con subida directa al Google Sheet:
    python generate_qr.py --input mis_asistentes.csv \\
        --upload-sheet TU_SHEET_ID \\
        --creds service_account.json

Con subida de imágenes a Google Drive:
    python generate_qr.py --upload-drive TU_FOLDER_ID \\
        --creds service_account.json

Todas las opciones:
    python generate_qr.py --help
"""

import os
import csv
import uuid
import argparse
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

# ── Dependencias opcionales ────────────────────────────────────────────────

try:
    import qrcode
    from PIL import Image, ImageDraw
except ImportError:
    print("ERROR: Faltan dependencias. Ejecutar: pip install -r requirements.txt")
    raise SystemExit(1)

try:
    from tqdm import tqdm
except ImportError:
    def tqdm(iterable, **kwargs):          # noqa: fallback mínimo sin barra
        total = kwargs.get('total', '?')
        desc  = kwargs.get('desc', '')
        print(f"{desc}: procesando {total} items...")
        return iterable

# ── Configuración ──────────────────────────────────────────────────────────

# URL base del backend (actualizar después de desplegar)
# Ejemplo: "https://evento.midominio.com"
WEBAPP_URL   = "https://tu-dominio.com"

NUM_DEFAULT  = 1800
QR_DIR       = Path("qr_codes")
CSV_OUTPUT   = Path("asistentes_import.csv")
CSV_HEADERS  = ["ID", "Nombre", "Email", "Hash_Unico", "Estado_Ingreso", "Fecha_Ingreso"]

# ── Generación de hashes ───────────────────────────────────────────────────

def gen_unique_hashes(n: int) -> list[str]:
    """Genera N strings hex únicos de 16 caracteres (UUID4-based, ~3×10^19 combinaciones)."""
    hashes: set[str] = set()
    while len(hashes) < n:
        hashes.add(uuid.uuid4().hex[:16].upper())
    return list(hashes)

# ── Generación de imágenes QR ──────────────────────────────────────────────

def make_qr(url: str, out_path: Path, label: str = "") -> None:
    """
    Genera una imagen QR PNG.
    Si se provee `label`, se imprime el nombre del asistente debajo del código
    (útil para identificar visualmente las impresiones).
    """
    qr = qrcode.QRCode(
        version=None,                             # tamaño automático
        error_correction=qrcode.constants.ERROR_CORRECT_M,  # ~15% de corrección
        box_size=10,
        border=4,
    )
    qr.add_data(url)
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white").convert("RGB")

    if label:
        w, h       = img.size
        label_h    = 28
        canvas     = Image.new("RGB", (w, h + label_h), "white")
        canvas.paste(img, (0, 0))
        draw = ImageDraw.Draw(canvas)
        # Fuente default (no requiere fuentes instaladas)
        text_w = len(label) * 6          # estimación para la fuente default
        x = max(0, (w - text_w) // 2)
        draw.text((x, h + 6), label, fill="black")
        canvas.save(out_path, "PNG", optimize=True)
    else:
        img.save(out_path, "PNG", optimize=True)

# ── Carga de asistentes ────────────────────────────────────────────────────

def load_from_csv(path: str) -> list[dict]:
    """
    Lee un CSV con los asistentes reales.
    Busca columnas: Nombre/nombre/Name y Email/email/EMAIL.
    Las columnas extra se ignoran.
    """
    attendees = []
    with open(path, newline='', encoding='utf-8-sig') as fh:
        reader = csv.DictReader(fh)
        for i, row in enumerate(reader, 1):
            nombre = (
                row.get('Nombre') or row.get('nombre') or
                row.get('Name')   or row.get('name')   or
                f'Asistente {i}'
            )
            email = (
                row.get('Email') or row.get('email') or
                row.get('EMAIL') or f'asistente{i}@evento.com'
            )
            attendees.append({'nombre': nombre.strip(), 'email': email.strip()})
    return attendees

def sample_attendees(n: int) -> list[dict]:
    """Genera datos de prueba cuando no hay CSV de entrada."""
    first_names = ["Ana", "Carlos", "María", "Juan", "Laura", "Pablo",
                   "Sofía", "Diego", "Valeria", "Martín", "Lucía", "Facundo"]
    last_names  = ["García", "López", "Martínez", "Rodríguez", "González",
                   "Hernández", "Pérez", "Sánchez", "Gómez", "Torres"]
    return [
        {
            'nombre': f"{first_names[i % len(first_names)]} {last_names[i % len(last_names)]}",
            'email':  f"asistente{i+1:04d}@evento.com",
        }
        for i in range(n)
    ]

# ── Subida a Google Sheets ─────────────────────────────────────────────────

def upload_to_sheets(rows: list[dict], sheet_id: str, creds_path: str) -> None:
    """
    Sube los datos al Google Sheet usando gspread + Service Account.

    Requiere:
      - gspread y google-auth instalados
      - Un Service Account con acceso al Sheet (Editor)
      - El archivo JSON de credenciales descargado desde Google Cloud Console
    """
    try:
        import gspread
        from google.oauth2.service_account import Credentials
    except ImportError:
        print("\n⚠️  Para subir a Sheets instalar: pip install gspread google-auth")
        return

    print(f"\n☁️  Subiendo {len(rows)} filas a Google Sheet ({sheet_id})...")

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_file(creds_path, scopes=scopes)
    gc    = gspread.authorize(creds)
    sh    = gc.open_by_key(sheet_id)

    try:
        ws = sh.worksheet("Asistentes")
        ws.clear()
        print("   Pestaña 'Asistentes' limpiada.")
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet("Asistentes", rows=len(rows) + 10, cols=8)
        print("   Pestaña 'Asistentes' creada.")

    # Subir encabezados + datos en un solo batch (mucho más rápido que fila por fila)
    all_values = [CSV_HEADERS] + [
        [
            r["ID"], r["Nombre"], r["Email"],
            r["Hash_Unico"], r["Estado_Ingreso"], r["Fecha_Ingreso"],
        ]
        for r in rows
    ]
    ws.update("A1", all_values, value_input_option="USER_ENTERED")
    print(f"   ✅ {len(rows)} filas escritas en el Sheet.")

# ── Subida a Google Drive ──────────────────────────────────────────────────

def upload_to_drive(qr_dir: Path, folder_id: str, creds_path: str) -> None:
    """
    Sube todas las imágenes PNG al Google Drive.

    Requiere:
      - google-api-python-client y google-auth instalados
      - Service Account con acceso a la carpeta de Drive (Editor)
    """
    try:
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaFileUpload
        from google.oauth2.service_account import Credentials
    except ImportError:
        print("\n⚠️  Para subir a Drive instalar: pip install google-api-python-client google-auth")
        return

    scopes = ["https://www.googleapis.com/auth/drive"]
    creds  = Credentials.from_service_account_file(creds_path, scopes=scopes)
    svc    = build("drive", "v3", credentials=creds, cache_discovery=False)

    png_files = sorted(qr_dir.glob("*.png"))
    print(f"\n☁️  Subiendo {len(png_files)} imágenes a Drive (folder: {folder_id})...")

    def _upload(fpath: Path) -> None:
        meta  = {"name": fpath.name, "parents": [folder_id]}
        media = MediaFileUpload(str(fpath), mimetype="image/png", resumable=False)
        svc.files().create(body=meta, media_body=media, fields="id").execute()

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(tqdm(
            pool.map(_upload, png_files),
            total=len(png_files),
            desc="Subiendo a Drive",
            unit="img",
        ))

    print(f"   ✅ {len(png_files)} imágenes subidas.")

# ── Main ───────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Genera QR codes para control de acceso a eventos.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--input",        "-i", metavar="CSV",       help="CSV de asistentes (columnas: Nombre, Email)")
    parser.add_argument("--count",        "-n", type=int, default=NUM_DEFAULT, metavar="N", help=f"Cantidad de asistentes si no hay --input (default: {NUM_DEFAULT})")
    parser.add_argument("--url",          "-u", default=WEBAPP_URL,  help="URL del Web App de Google Apps Script")
    parser.add_argument("--output",       "-o", default=str(QR_DIR), help="Directorio de salida para imágenes QR")
    parser.add_argument("--label",        "-l", action="store_true", help="Imprimir el nombre debajo de cada QR")
    parser.add_argument("--workers",      "-w", type=int, default=8, help="Workers paralelos para generar imágenes (default: 8)")
    parser.add_argument("--upload-sheet", metavar="SHEET_ID",        help="ID del Google Sheet destino")
    parser.add_argument("--upload-drive", metavar="FOLDER_ID",       help="ID de carpeta en Google Drive para las imágenes")
    parser.add_argument("--creds",        "-c", default="service_account.json", help="JSON de credenciales del Service Account (default: service_account.json)")
    args = parser.parse_args()

    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)

    sep = "─" * 52
    print(f"\n{sep}")
    print("  GENERADOR DE QR — CONTROL DE ACCESO A EVENTO")
    print(sep)

    # 1. Cargar asistentes
    if args.input:
        print(f"\n📂 Leyendo asistentes desde: {args.input}")
        attendees = load_from_csv(args.input)
        count = len(attendees)
        print(f"   → {count} asistentes cargados")
    else:
        count = args.count
        print(f"\n🔧 Sin --input: generando {count} asistentes de muestra")
        attendees = sample_attendees(count)

    # 2. Hashes únicos
    print(f"\n🔑 Generando {count} hashes únicos...", end=" ", flush=True)
    hashes = gen_unique_hashes(count)
    print("OK")

    # 3. Construir filas del CSV
    rows = [
        {
            "ID":             i + 1,
            "Nombre":         attendees[i]["nombre"],
            "Email":          attendees[i]["email"],
            "Hash_Unico":     hashes[i],
            "Estado_Ingreso": "FALSE",
            "Fecha_Ingreso":  "",
        }
        for i in range(count)
    ]

    # 4. Guardar CSV de importación
    with open(CSV_OUTPUT, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_HEADERS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"📄 CSV exportado → {CSV_OUTPUT}")

    # 5. Generar imágenes QR en paralelo
    print(f"\n🖼️  Generando imágenes en {out_dir}/ con {args.workers} workers...")

    errors: list[tuple[int, str]] = []

    def _gen(row: dict) -> bool:
        safe = row["Nombre"].replace(" ", "_").replace("/", "-")[:28]
        fname = out_dir / f"{row['ID']:04d}_{safe}_{row['Hash_Unico']}.png"
        # URL del QR: apunta al nuevo backend FastAPI
        url   = f"{args.url}/?id={row['Hash_Unico']}"
        label = row["Nombre"] if args.label else ""
        try:
            make_qr(url, fname, label)
            return True
        except Exception as exc:
            errors.append((row["ID"], str(exc)))
            return False

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(_gen, r): r for r in rows}
        results = list(tqdm(
            (f.result() for f in as_completed(futures)),
            total=count,
            desc="Generando QR",
            unit="qr",
        ))

    ok = sum(results)
    print(f"\n✅ {ok}/{count} imágenes generadas correctamente")
    if errors:
        print(f"⚠️  {len(errors)} errores (primeros 5):")
        for eid, emsg in errors[:5]:
            print(f"   ID {eid}: {emsg}")

    # 6. Subir al Sheet (opcional)
    if args.upload_sheet:
        upload_to_sheets(rows, args.upload_sheet, args.creds)

    # 7. Subir imágenes a Drive (opcional)
    if args.upload_drive:
        upload_to_drive(out_dir, args.upload_drive, args.creds)

    # Resumen
    print(f"\n{sep}")
    print("  RESUMEN")
    print(sep)
    print(f"  Asistentes  : {count}")
    print(f"  QR Images   : {out_dir}/")
    print(f"  CSV Import  : {CSV_OUTPUT}")
    print(f"\n  PRÓXIMOS PASOS")
    print(f"  1. Copiar .env.example a .env y ajustar credenciales")
    print(f"  2. docker compose up -d")
    print(f"  3. bash init-letsencrypt.sh   (para HTTPS con tu dominio)")
    print(f"  4. Actualizar WEBAPP_URL en este script con tu dominio")
    print(f"  5. python generate_qr.py --input tus_asistentes.csv")
    print(f"  6. Los QR se generan en {out_dir}/ y el CSV en {CSV_OUTPUT}")
    print(f"  7. POST /api/seed para importar el CSV a la base de datos")
    if "tu-dominio.com" in args.url:
        print(f"\n  ⚠️  WEBAPP_URL sigue siendo el placeholder.")
        print(f"     Actualizar la variable WEBAPP_URL (línea ~57) antes de la regeneración.")
    print(sep + "\n")


if __name__ == "__main__":
    main()
