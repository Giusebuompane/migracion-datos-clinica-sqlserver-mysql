# load_advances_gen.py
import csv
import io
from pathlib import Path
from datetime import datetime, date
from decimal import Decimal, InvalidOperation

from step02_db import get_connection

ENTITY_KEY = "advances_gen"

# =========================================
# Helpers básicos
# =========================================
def normalize_latin1(text: str | None) -> str | None:
    if text is None: return None
    if not isinstance(text, str): text = str(text)
    try:
        return text.encode("latin-1", errors="replace").decode("latin-1", errors="replace")
    except Exception: return text

def clean_token(val):
    if val is None: return None
    v = str(val).strip()
    if v == "" or v.upper() == "NULL": return None
    return v

def parse_int(val, default=None):
    v = clean_token(val)
    if v is None: return default
    try: return int(v)
    except (ValueError, TypeError): return default

def parse_decimal(val, default=None):
    v = clean_token(val)
    if v is None: return default
    v = v.replace(",", ".")
    try: return Decimal(v)
    except (InvalidOperation, ValueError): return default

def parse_date(val):
    """
    Intenta parsear la fecha con múltiples formatos.
    Si el valor es nulo o falla, usa hoy pero avisa por consola.
    """
    v = clean_token(val)
    if v is None:
        return date.today()

    # Formatos extendidos para cubrir todas las posibilidades del CSV
    formats = [
        "%d/%m/%Y",          # 25/12/2023
        "%Y-%m-%d",          # 2023-12-25
        "%d/%m/%y",          # 25/12/23
        "%d-%m-%Y",          # 25-12-2023
        "%d-%m-%y",          # 25-12-23
        "%Y/%m/%d",          # 2023/12/25
        "%d/%m/%Y %H:%M:%S", # 25/12/2023 10:30:00
        "%Y-%m-%d %H:%M:%S", # 2023-12-25 10:30:00
    ]
    
    for fmt in formats:
        try:
            return datetime.strptime(v, fmt).date()
        except ValueError:
            continue
    
    # Si llega aquí, es que ningún formato ha funcionado
    print(f"   [!] ADVERTENCIA: No se pudo reconocer el formato de fecha: '{val}'. Se usará CURDATE.")
    return date.today()

# =========================================
# Carga CSV → __mig_advances_gen
# =========================================
def load_csv_into_mig(cursor, entity_config: dict, context: dict) -> int:
    mig_table = entity_config.get("mig_table", "__mig_advances_gen")
    input_file = entity_config.get("input_file", "advances_gen.csv")
    input_folder = Path(context.get("input_folder", Path(".")))
    csv_path = input_folder / input_file

    if not csv_path.exists():
        raise FileNotFoundError(f"No se encontró el fichero: {csv_path}")

    raw = csv_path.read_text(encoding="utf-8-sig", errors="replace")
    if not raw.strip(): return 0

    lines = raw.splitlines()
    first_line = lines[0]
    delimiter = ";" if first_line.count(";") >= first_line.count(",") else ","

    f = io.StringIO(raw)
    reader = csv.DictReader(f, delimiter=delimiter)

    if reader.fieldnames and reader.fieldnames[0].startswith("ï»¿"):
        reader.fieldnames[0] = reader.fieldnames[0].replace("ï»¿", "")

    inserted = 0
    insert_sql = f"""
        INSERT INTO {mig_table} (
            AdvanceGID, AdvanceGDate, AdvanceGClientID, 
            AdvanceGClinicID, AdvanceAmount, AdvanceVAT
        ) VALUES (%s, %s, %s, %s, %s, %s)
    """

    for row in reader:
        # Extraemos la fecha usando el nombre exacto de la columna en tu CSV
        raw_date_val = row.get("AdvanceGDate")
        
        data = (
            parse_int(row.get("AdvanceGID")),
            parse_date(raw_date_val),
            parse_int(row.get("AdvanceGClientID")),
            parse_int(row.get("AdvanceGClinicID")),
            parse_decimal(row.get("AdvanceAmount"), Decimal("0.00")),
            parse_decimal(row.get("AdvanceVAT"), Decimal("0.00"))
        )
        cursor.execute(insert_sql, data)
        inserted += 1

    return inserted

# =========================================
# RUN principal
# =========================================
def run(entity_config: dict, context: dict):
    mig_table = entity_config.get("mig_table", "__mig_advances_gen")
    stop_on_error = bool(context.get("stop_on_error", True))
    
    conn = get_connection()
    cursor = conn.cursor()

    try:
        # 1) Recrear tabla de migración
        cursor.execute(f"DROP TABLE IF EXISTS {mig_table}")
        cursor.execute(f"""
            CREATE TABLE `{mig_table}` (
                `AdvanceGID` INT(11) NOT NULL,
                `AdvanceGDate` DATE NOT NULL,
                `AdvanceGClientID` INT(11) NULL DEFAULT NULL,
                `AdvanceGClinicID` INT(11) NULL DEFAULT NULL,
                `AdvanceAmount` DECIMAL(14,2) NULL DEFAULT NULL,
                `AdvanceVAT` DECIMAL(6,6) NULL DEFAULT NULL,
                PRIMARY KEY (`AdvanceGID`)
            ) COLLATE='latin1_spanish_ci' ENGINE=MyISAM
        """)
        conn.commit()

        # 2) Carga CSV
        inserted_mig = load_csv_into_mig(cursor, entity_config, context)
        conn.commit()
        print(f"   [{ENTITY_KEY}] Filas cargadas en MIG: {inserted_mig}")

        if inserted_mig == 0:
            if stop_on_error: raise ValueError("No hay datos en MIG.")
            return

        # 3) Asegurar columnas en tablas destino
        for table in ["advances_gen", "advances_det"]:
            try:
                cursor.execute(f"ALTER TABLE `{table}` ADD COLUMN `__MigAdvanceGID` INT(11) NULL DEFAULT NULL")
                conn.commit()
            except: pass

        # 4) Inserción en advances_gen (Cabecera)
        # Mantenemos el IFNULL por si la tabla MIG tuviera algún nulo residual
        insert_gen_sql = f"""
            INSERT INTO advances_gen (
                AdvanceGClinicID, AdvanceGClientID, AdvanceGDate, __MigAdvanceGID
            )
            SELECT 
                xc.ClinicID, 
                c.ClientID, 
                IFNULL(m.AdvanceGDate, CURDATE()), 
                m.AdvanceGID
            FROM {mig_table} m
            INNER JOIN clients c ON c.ClientID = m.AdvanceGClientID
            INNER JOIN x_config_clinics xc ON xc.ClinicID = m.AdvanceGClinicID
        """
        cursor.execute(insert_gen_sql)
        conn.commit()
        print(f"   [{ENTITY_KEY}] Registros en advances_gen: {cursor.rowcount}")

        # 5) Inserción en advances_det (Detalle)
        insert_det_sql = f"""
            INSERT INTO advances_det (
                AdvanceGID, AdvanceAmount, AdvanceVAT, __MigAdvanceGID
            )
            SELECT 
                ag.AdvanceGID, 
                m.AdvanceAmount, 
                m.AdvanceVAT, 
                m.AdvanceGID
            FROM {mig_table} m
            INNER JOIN advances_gen ag ON ag.__MigAdvanceGID = m.AdvanceGID
        """
        cursor.execute(insert_det_sql)
        conn.commit()
        print(f"   [{ENTITY_KEY}] Registros en advances_det: {cursor.rowcount}")

    finally:
        cursor.close()
        conn.close()