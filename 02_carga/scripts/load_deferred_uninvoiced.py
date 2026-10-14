# load_deferred_uninvoiced.py
import csv
import io
import re
from pathlib import Path
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from step02_db import get_connection

ENTITY_KEY = "deferred_uninvoiced"


# =========================================
# Helpers
# =========================================
def normalize_latin1(text: str | None) -> str | None:
    if text is None:
        return None
    if not isinstance(text, str):
        text = str(text)

    bad_chars = "\u202a\u202b\u202c\u202d\u202e"
    for ch in bad_chars:
        text = text.replace(ch, "")

    try:
        return text.encode("latin-1", errors="replace").decode("latin-1", errors="replace")
    except Exception:
        return text


def clean_token(val):
    if val is None:
        return None
    if not isinstance(val, str):
        val = str(val)
    v = val.strip()
    if v == "" or v.upper() == "NULL":
        return None
    return v


def clean_str(val, max_len: int | None = None):
    v = clean_token(val)
    if v is None:
        return None
    v = normalize_latin1(v)
    if max_len is not None:
        return v[:max_len]
    return v


def parse_int(val, default=None):
    v = clean_token(val)
    if v is None:
        return default
    try:
        return int(v)
    except (ValueError, TypeError):
        try:
            return int(float(v.replace(",", ".")))
        except Exception:
            return default


def parse_tinyint(val, default=0):
    v = parse_int(val, None)
    if v is None:
        return default
    return 1 if v != 0 else 0


def parse_decimal_eu(val, default=None, scale: int | None = None):
    """
    Parser robusto para importes europeos:
      - elimina símbolos (€, etc) y espacios
      - soporta 1.234,56 (miles '.' y decimal ',')
      - soporta 1234,56
      - soporta 1234.56
    Si scale se indica, redondea a esa escala.
    """
    v = clean_token(val)
    if v is None:
        return default

    # Mantener solo dígitos, separadores, signo
    v = v.strip()
    v = v.replace("€", "")
    v = v.replace("\u00a0", " ")  # NBSP
    v = v.replace(" ", "")
    v = re.sub(r"[^\d\-\.,]", "", v)

    if v in ("", "-", ".", ","):
        return default

    # Caso europeo: contiene '.' y ',' => '.' miles, ',' decimal
    if "." in v and "," in v:
        v = v.replace(".", "")
        v = v.replace(",", ".")
    # Solo coma => coma decimal
    elif "," in v and "." not in v:
        v = v.replace(",", ".")
    # Solo punto => ya OK

    try:
        d = Decimal(v)
        if scale is not None:
            q = Decimal("1." + ("0" * scale))
            d = d.quantize(q, rounding=ROUND_HALF_UP)
        return d
    except (InvalidOperation, ValueError):
        return default


def parse_date(val):
    v = clean_token(val)
    if v is None:
        return None

    formats = [
        "%Y-%m-%d %H:%M:%S.%f",
        "%d/%m/%Y %H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S",
        "%d/%m/%Y %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%d/%m/%Y %H:%M",
        "%Y-%m-%d",
        "%d/%m/%Y",
    ]
    for fmt in formats:
        try:
            dt = datetime.strptime(v, fmt)
            return dt.date()
        except ValueError:
            continue
    return None


def parse_time(val):
    v = clean_token(val)
    if v is None:
        return None

    formats = [
        "%H:%M:%S",
        "%H:%M",
        "%H:%M:%S.%f",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(v, fmt).time()
        except ValueError:
            continue
    return None


def detect_delimiter(raw: str) -> str:
    first_line = raw.splitlines()[0] if raw else ""
    return ";" if first_line.count(";") >= first_line.count(",") else ","


# =========================================
# CSV → __mig_deferred_uninvoiced
# =========================================
def load_csv_into_mig(cursor, entity_config: dict, context: dict) -> int:
    mig_table = entity_config.get("mig_table", "__mig_deferred_uninvoiced")
    input_file = entity_config.get("input_file", "deferred_uninvoiced.csv")
    input_folder = Path(context.get("input_folder", Path(".")))
    csv_path = input_folder / input_file

    print(f"   [{ENTITY_KEY}] Fichero de entrada: {csv_path}")

    raw = csv_path.read_text(encoding="utf-8-sig", errors="replace")
    delimiter = detect_delimiter(raw)
    f = io.StringIO(raw)
    reader = csv.DictReader(f, delimiter=delimiter)

    if reader.fieldnames and reader.fieldnames[0] and reader.fieldnames[0].startswith("ï»¿"):
        reader.fieldnames[0] = reader.fieldnames[0].replace("ï»¿", "")

    fieldnames = [fn.strip() if fn else fn for fn in (reader.fieldnames or [])]
    print(f"   [{ENTITY_KEY}] Cabeceras encontradas en CSV: {fieldnames}")

    for c in ("DeferredUID", "ClinicID", "ClientID"):
        if c not in fieldnames:
            raise ValueError(f"Falta columna obligatoria en CSV: {c}")

    insert_sql = f"""
        INSERT INTO {mig_table} (
            DeferredUID, ClinicID, ClientID,
            DeferredUTicketGID, DeferredUTicketID, DeferredUNumber, DeferredUYear,
            DeferredUAmount, DeferredUSettlement,
            DeferredUPTicketGID, DeferredUDeleted, DeferredUPClinicID,
            DeferredUPDate, DeferredUPTime, DeferredUImportID,
            DeferredUMigratedVAT, DeferredUMigratedDate, DeferredUMigratedDesc
        ) VALUES (
            %s,%s,%s,
            %s,%s,%s,%s,
            %s,%s,
            %s,%s,%s,
            %s,%s,%s,
            %s,%s,%s
        )
    """

    inserted = 0
    batch = []
    batch_size = int(entity_config.get("batch_size", 1000))

    for row in reader:
        DeferredUID = parse_int(row.get("DeferredUID"))
        ClinicID = parse_int(row.get("ClinicID"))
        ClientID = parse_int(row.get("ClientID"))
        if DeferredUID is None or ClinicID is None or ClientID is None:
            continue

        DeferredUTicketGID = parse_int(row.get("DeferredUTicketGID"), 0)
        DeferredUTicketID = parse_int(row.get("DeferredUTicketID"), 0)
        DeferredUNumber = parse_int(row.get("DeferredUNumber"), 0)
        DeferredUYear = parse_int(row.get("DeferredUYear"), None)

        # ✅ ARREGLO AQUÍ: importe europeo robusto + 2 decimales
        DeferredUAmount = parse_decimal_eu(row.get("DeferredUAmount"), Decimal("0"), scale=2)

        DeferredUSettlement = parse_date(row.get("DeferredUSettlement"))
        DeferredUPTicketGID = parse_int(row.get("DeferredUPTicketGID"), 0)
        DeferredUDeleted = parse_tinyint(row.get("DeferredUDeleted"), 0)
        DeferredUPClinicID = parse_int(row.get("DeferredUPClinicID"), None)
        DeferredUPDate = parse_date(row.get("DeferredUPDate"))
        DeferredUPTime = parse_time(row.get("DeferredUPTime"))
        DeferredUImportID = parse_int(row.get("DeferredUImportID"), 0)

        DeferredUMigratedVAT = parse_decimal_eu(row.get("DeferredUMigratedVAT"), Decimal("0"), scale=6)
        DeferredUMigratedDate = parse_date(row.get("DeferredUMigratedDate"))
        DeferredUMigratedDesc = clean_str(row.get("DeferredUMigratedDesc"), 255)

        batch.append(
            (
                DeferredUID, ClinicID, ClientID,
                DeferredUTicketGID, DeferredUTicketID, DeferredUNumber, DeferredUYear,
                DeferredUAmount, DeferredUSettlement,
                DeferredUPTicketGID, DeferredUDeleted, DeferredUPClinicID,
                DeferredUPDate, DeferredUPTime, DeferredUImportID,
                DeferredUMigratedVAT, DeferredUMigratedDate, DeferredUMigratedDesc,
            )
        )

        if len(batch) >= batch_size:
            cursor.executemany(insert_sql, batch)
            inserted += len(batch)
            batch.clear()

    if batch:
        cursor.executemany(insert_sql, batch)
        inserted += len(batch)

    print(f"   [{ENTITY_KEY}] Filas insertadas en {mig_table}: {inserted}")
    return inserted


def choose_clients_join_column(cursor, mig_table: str) -> str:
    cursor.execute(
        """
        SELECT COUNT(*)
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'clients'
          AND COLUMN_NAME = '__MigClientID'
        """
    )
    (has_mig_col,) = cursor.fetchone()

    if has_mig_col:
        cursor.execute(
            f"""
            SELECT COUNT(*)
            FROM {mig_table} s
            JOIN clients c
              ON c.__MigClientID = s.ClientID
            """
        )
        (cnt,) = cursor.fetchone()
        if cnt and int(cnt) > 0:
            return "__MigClientID"

    return "ClientID"


def insert_into_final(cursor, join_col: str, mig_table: str) -> int:
    q = f"""
INSERT INTO deferred_uninvoiced
(
    DeferredUID,
    DeferredUTicketGID,
    DeferredUTicketID,
    DeferredUNumber,
    DeferredUYear,
    DeferredUAmount,
    DeferredUSettlement,
    DeferredUPTicketGID,
    DeferredUDeleted,
    DeferredUPClinicID,
    DeferredUPDate,
    DeferredUPTime,
    DeferredUImportID,

    DeferredUMigratedClinicID,
    DeferredUMigratedClientID,
    DeferredUMigratedVAT,
    DeferredUMigratedDate,
    DeferredUMigratedDesc
)
SELECT
    s.DeferredUID,
    IFNULL(s.DeferredUTicketGID, 0),
    IFNULL(s.DeferredUTicketID, 0),
    IFNULL(s.DeferredUNumber, 0),
    s.DeferredUYear,
    IFNULL(s.DeferredUAmount, 0),
    s.DeferredUSettlement,
    IFNULL(s.DeferredUPTicketGID, 0),
    IFNULL(s.DeferredUDeleted, 0),
    s.DeferredUPClinicID,
    s.DeferredUPDate,
    s.DeferredUPTime,
    IFNULL(s.DeferredUImportID, 0),

    s.ClinicID,
    c.ClientID,
    CASE
        WHEN s.DeferredUMigratedVAT > 1 THEN s.DeferredUMigratedVAT / 100
        ELSE IFNULL(s.DeferredUMigratedVAT, 0)
    END,
    IFNULL(s.DeferredUMigratedDate, CURDATE()),
    s.DeferredUMigratedDesc
FROM
    {mig_table} s
    INNER JOIN clients c
        ON c.{join_col} = s.ClientID
       AND c.ClientImportID = (
            SELECT MAX(c2.ClientImportID)
            FROM clients c2
            WHERE c2.{join_col} = s.ClientID
        )
    INNER JOIN x_config_clinics cc
        ON c.ClientClinicID = cc.ClinicID;
""".strip()

    print(f"   [{ENTITY_KEY}] Ejecutando INSERT final (join_col={join_col}):")
    print("      SQL> " + q.replace("\n", "\n      "))

    cursor.execute(q)
    return cursor.rowcount


def run(entity_config: dict, context: dict):
    mig_table = entity_config.get("mig_table", "__mig_deferred_uninvoiced")
    stop_on_error = bool(context.get("stop_on_error", True))

    conn = get_connection()
    cursor = conn.cursor()

    try:
        q1 = "DROP TABLE IF EXISTS __mig_deferred_uninvoiced;"
        print(f"   [{ENTITY_KEY}] (1) Ejecutando query 1/4:")
        print(f"      SQL> {q1}")
        cursor.execute(q1)
        conn.commit()

        q2 = """
CREATE TABLE __mig_deferred_uninvoiced (
    DeferredUID INT PRIMARY KEY,
    ClinicID INT,
    ClientID INT,

    DeferredUTicketGID INT,
    DeferredUTicketID INT,
    DeferredUNumber INT,
    DeferredUYear YEAR,
    DeferredUAmount DECIMAL(14,2),
    DeferredUSettlement DATE,
    DeferredUPTicketGID INT,
    DeferredUDeleted TINYINT,
    DeferredUPClinicID SMALLINT,
    DeferredUPDate DATE,
    DeferredUPTime TIME,
    DeferredUImportID INT,

    DeferredUMigratedVAT DECIMAL(10,6),
    DeferredUMigratedDate DATE,
    DeferredUMigratedDesc VARCHAR(255)
);
""".strip()

        print(f"   [{ENTITY_KEY}] (2) Ejecutando query 2/4:")
        print("      SQL> " + q2.replace("\n", "\n      "))
        cursor.execute(q2)
        conn.commit()

        rows_mig = load_csv_into_mig(cursor, entity_config, context)
        conn.commit()
        if rows_mig == 0:
            print(f"   [{ENTITY_KEY}] No hay filas en {mig_table}. Se omite inserción.")
            return True

        join_col = choose_clients_join_column(cursor, mig_table)
        print(f"   [{ENTITY_KEY}] Join detectado en clients: {join_col}")

        inserted = insert_into_final(cursor, join_col, mig_table)
        conn.commit()

        print(f"   [{ENTITY_KEY}] Registros insertados en deferred_uninvoiced: {inserted}")
        return True

    except Exception as e:
        print(f"   ❌ Error en loader {ENTITY_KEY}: {e}")
        if stop_on_error:
            raise
        return False

    finally:
        try:
            cursor.close()
        except Exception:
            pass
        try:
            conn.close()
        except Exception:
            pass