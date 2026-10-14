
# load_clients_tracking_gen.py
import csv
import io
from pathlib import Path
from datetime import datetime

from step02_db import get_connection

ENTITY_KEY = "clients_tracking_gen"


# =========================================
# Helpers básicos
# =========================================
def clean_token(val):
    """
    Limpia un valor leído del CSV:
      - None o "" → None
      - "NULL", "null" → None
    """
    if val is None:
        return None
    if not isinstance(val, str):
        val = str(val)
    v = val.strip()
    if v == "" or v.upper() == "NULL":
        return None
    return v


def parse_int(val, default=None):
    v = clean_token(val)
    if v is None:
        return default
    try:
        return int(v)
    except (ValueError, TypeError):
        try:
            return int(float(str(v).replace(",", ".")))
        except (ValueError, TypeError):
            return default


def parse_date(val):
    """
    Devuelve un datetime.date o None.
    Acepta:
      - dd/mm/yyyy
      - yyyy-mm-dd
      - dd/mm/yyyy HH:MM:SS
      - yyyy-mm-dd HH:MM:SS
      - yyyy-mm-dd HH:MM:SS.mmm
    """
    v = clean_token(val)
    if v is None:
        return None

    formats = [
        "%d/%m/%Y",
        "%Y-%m-%d",
        "%d/%m/%Y %H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M:%S.%f",
    ]
    for fmt in formats:
        try:
            dt = datetime.strptime(v, fmt)
            return dt.date()
        except ValueError:
            continue

    try:
        dt = datetime.fromisoformat(v)
        return dt.date()
    except ValueError:
        return None


def parse_time(val):
    """
    Devuelve un datetime.time o None.
    Acepta:
      - HH:MM
      - HH:MM:SS
      - HH:MM:SS.mmm
    """
    v = clean_token(val)
    if v is None:
        return None

    formats = [
        "%H:%M",
        "%H:%M:%S",
        "%H:%M:%S.%f",
    ]
    for fmt in formats:
        try:
            dt = datetime.strptime(v, fmt)
            return dt.time()
        except ValueError:
            continue

    return None


def normalize_latin1(text):
    """
    Normaliza una cadena a latin1, reemplazando caracteres no representables
    y eliminando marcas bidi problemáticas.
    """
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


def detect_delimiter(raw: str) -> str:
    """
    Detección simple de separador: coma o punto y coma.
    """
    if not raw:
        return ";"
    first_line = raw.splitlines()[0]
    sep_semicolon = first_line.count(";")
    sep_comma = first_line.count(",")
    return ";" if sep_semicolon >= sep_comma else ","


def column_exists(cursor, table_name: str, column_name: str) -> bool:
    cursor.execute(
        """
        SELECT COUNT(*)
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = %s
          AND COLUMN_NAME = %s
        """,
        (table_name, column_name),
    )
    (count,) = cursor.fetchone()
    return count > 0


def add_column_if_not_exists(cursor, table_name: str, column_name: str, column_definition: str):
    if column_exists(cursor, table_name, column_name):
        print(f"   [{ENTITY_KEY}] La columna {table_name}.{column_name} ya existe.")
        return

    sql = f"ALTER TABLE `{table_name}` ADD COLUMN `{column_name}` {column_definition}"
    print(f"   [{ENTITY_KEY}] Añadiendo columna {table_name}.{column_name}...")
    cursor.execute(sql)


# =========================================
# Carga CSV → __mig_clients_tracking_gen
# =========================================
def load_csv_into_mig(cursor, entity_config: dict, context: dict) -> int:
    """
    Carga el CSV de tracking en la tabla __mig_clients_tracking_gen.
    Aplica:
      - detección de separador (coma / punto y coma)
      - manejo de BOM en cabeceras
      - conversión de fechas / horas / enteros
      - normalización latin1 en TrackValue
    """
    mig_table = entity_config.get("mig_table", "__mig_clients_tracking_gen")
    input_file = entity_config.get("input_file", "clients_tracking.csv")
    input_folder = Path(context.get("input_folder", Path(".")))
    csv_path = input_folder / input_file

    if not csv_path.exists():
        raise FileNotFoundError(f"No se encontró el fichero de entrada: {csv_path}")

    print(f"   [{ENTITY_KEY}] Fichero de entrada: {csv_path}")

    raw = csv_path.read_text(encoding="utf-8-sig", errors="replace")
    if not raw.strip():
        print(f"   [{ENTITY_KEY}] El CSV está vacío. No se insertan filas en {mig_table}.")
        return 0

    delimiter = detect_delimiter(raw)

    f = io.StringIO(raw)
    reader = csv.DictReader(f, delimiter=delimiter)

    if reader.fieldnames and reader.fieldnames[0].startswith("ï»¿"):
        reader.fieldnames[0] = reader.fieldnames[0].replace("ï»¿", "")

    fieldnames = reader.fieldnames or []
    fieldnames = [fn.strip() for fn in fieldnames]
    reader.fieldnames = fieldnames

    required_cols = [
        "TrackGID",
        "TrackID",
        "TrackGClientID",
        "TrackGClinicID",
        "TrackGDiaryID",
        "TrackGDate",
        "TrackGTime",
        "TrackParamID",
        "TrackValue",
    ]
    missing = [c for c in required_cols if c not in fieldnames]
    if missing:
        msg = (
            f"Las columnas del CSV no cumplen los mínimos requeridos.\n"
            f"   Encontradas: {fieldnames}\n"
            f"   Faltan: {missing}"
        )
        raise ValueError(msg)

    insert_sql = f"""
        INSERT INTO {mig_table} (
            TrackGID,
            TrackID,
            TrackGClientID,
            TrackGClinicID,
            TrackGDiaryID,
            TrackGDate,
            TrackGTime,
            TrackParamID,
            TrackValue
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
    """

    rows_inserted = 0

    for row in reader:
        if all((v is None or str(v).strip() == "") for v in row.values()):
            continue

        TrackGID = parse_int(row.get("TrackGID"))
        TrackID = parse_int(row.get("TrackID"))
        TrackGClientID = parse_int(row.get("TrackGClientID"))
        TrackGClinicID = parse_int(row.get("TrackGClinicID"))
        TrackGDiaryID = parse_int(row.get("TrackGDiaryID"))
        TrackGDate = parse_date(row.get("TrackGDate"))
        TrackGTime = parse_time(row.get("TrackGTime"))
        TrackParamID = parse_int(row.get("TrackParamID"))
        TrackValue = normalize_latin1(clean_token(row.get("TrackValue")))

        data = (
            TrackGID,
            TrackID,
            TrackGClientID,
            TrackGClinicID,
            TrackGDiaryID,
            TrackGDate,
            TrackGTime,
            TrackParamID,
            TrackValue,
        )

        cursor.execute(insert_sql, data)
        rows_inserted += 1

    return rows_inserted


# =========================================
# RUN
# =========================================
def run(entity_config: dict, context: dict):
    """
    Proceso de migración para 'clients_tracking_gen':
      1) DROP + CREATE de la tabla __mig_clients_tracking_gen
      2) ALTER TABLE para añadir __MigTrackGID / __MigTrackID si no existen
      3) Carga del CSV en la tabla de migración
      4) INSERT en clients_tracking_gen respetando la SQL original
      5) INSERT en clients_tracking_det respetando la SQL original
    """
    mig_table = entity_config.get("mig_table", "__mig_clients_tracking_gen")
    input_file = entity_config.get("input_file", "clients_tracking.csv")
    stop_on_error = bool(context.get("stop_on_error", False))

    input_folder = context["input_folder"]
    input_path = Path(input_folder) / input_file

    print(f"   [{ENTITY_KEY}] Fichero de entrada: {input_path}")

    if not input_path.exists():
        msg = f"Fichero no encontrado: {input_path}"
        print(f"   ❌ {msg}")
        if stop_on_error:
            raise FileNotFoundError(msg)
        return False

    conn = get_connection()
    cursor = conn.cursor()

    try:
        # 1) DROP + CREATE tabla de migración
        print(f"   [{ENTITY_KEY}] Recreando tabla {mig_table}.")
        cursor.execute(f"DROP TABLE IF EXISTS `{mig_table}`")

        create_sql = f"""
            CREATE TABLE `{mig_table}` (
                `TrackGID` INT(11) NULL DEFAULT NULL,
                `TrackID` INT(11) NULL DEFAULT NULL,
                `TrackGClientID` INT(11) NULL DEFAULT NULL,
                `TrackGClinicID` INT(11) NULL DEFAULT NULL,
                `TrackGDiaryID` INT(11) NULL DEFAULT NULL,
                `TrackGDate` DATE NULL DEFAULT NULL,
                `TrackGTime` TIME NULL DEFAULT NULL,
                `TrackParamID` INT(11) NULL DEFAULT NULL,
                `TrackValue` TEXT NULL DEFAULT NULL COLLATE 'latin1_spanish_ci'
            )
            COLLATE='latin1_spanish_ci'
            ENGINE=MyISAM
        """
        cursor.execute(create_sql)
        conn.commit()

        # 2) ALTER TABLE tablas definitivas
        print(f"   [{ENTITY_KEY}] Añadiendo columnas de migración a tablas definitivas (si no existen).")
        add_column_if_not_exists(cursor, "clients_tracking_gen", "__MigTrackGID", "INT NULL DEFAULT NULL")
        add_column_if_not_exists(cursor, "clients_tracking_det", "__MigTrackID", "INT NULL DEFAULT NULL")
        add_column_if_not_exists(cursor, "clients_tracking_det", "__MigTrackGID", "INT NULL DEFAULT NULL")
        conn.commit()

        # 3) Carga CSV en tabla migración
        rows_mig = load_csv_into_mig(cursor, entity_config, context)
        conn.commit()

        if rows_mig == 0:
            msg = "No se han insertado filas en la tabla de migración de tracking."
            print(f"   [{ENTITY_KEY}] {msg}")
            if stop_on_error:
                raise ValueError(msg)
            return {"status": "no-data", "rows_mig": 0}

        # 4) INSERT tracking cabecera
        print(f"   [{ENTITY_KEY}] Comprobando datos para insertar en clients_tracking_gen.")
        count_gen_sql = f"""
            SELECT COUNT(DISTINCT s.TrackGID)
            FROM {mig_table} s
            INNER JOIN clients ON clients.ClientCode = s.TrackGClientID
                              AND clients.ClientClinicID = s.TrackGClinicID
            INNER JOIN x_config_clinics ON x_config_clinics.ClinicID = s.TrackGClinicID
            INNER JOIN diary_gen ON diary_gen.__MigDiaryGID = s.TrackGDiaryID
            LEFT JOIN clients_tracking_gen
                   ON clients_tracking_gen.__MigTrackGID = s.TrackGID
            WHERE ISNULL(clients_tracking_gen.TrackGID)
        """
        cursor.execute(count_gen_sql)
        (rows_gen_to_insert,) = cursor.fetchone()
        print(f"   [{ENTITY_KEY}] Se van a insertar {rows_gen_to_insert} registros en clients_tracking_gen.")

        insert_gen_sql = f"""
            INSERT INTO
                clients_tracking_gen
                (
                    TrackGClientID,
                    TrackGDiaryGID,
                    TrackGDate,
                    TrackGTime,
                    __MigTrackGID
                )
            SELECT
                clients.ClientID,
                diary_gen.DiaryGID,
                s.TrackGDate,
                s.TrackGTime,
                s.TrackGID
            FROM
                {mig_table} s
                INNER JOIN clients ON clients.ClientCode = s.TrackGClientID
                                  AND clients.ClientClinicID = s.TrackGClinicID
                INNER JOIN x_config_clinics ON x_config_clinics.ClinicID = s.TrackGClinicID
                INNER JOIN diary_gen ON diary_gen.__MigDiaryGID = s.TrackGDiaryID
                LEFT JOIN clients_tracking_gen ON clients_tracking_gen.__MigTrackGID = s.TrackGID
            WHERE
                ISNULL(clients_tracking_gen.TrackGID)
            GROUP BY
                s.TrackGID
        """
        cursor.execute(insert_gen_sql)
        conn.commit()
        rows_gen_inserted = cursor.rowcount
        print(f"   [{ENTITY_KEY}] Insertados {rows_gen_inserted} registros en clients_tracking_gen.")

        # 5) INSERT tracking detalle
        print(f"   [{ENTITY_KEY}] Comprobando datos para insertar en clients_tracking_det.")
        count_det_sql = f"""
            SELECT COUNT(DISTINCT s.TrackID)
            FROM {mig_table} s
            INNER JOIN clients_tracking_gen
                    ON clients_tracking_gen.__MigTrackGID = s.TrackGID
            LEFT JOIN clients_tracking_det
                   ON clients_tracking_det.__MigTrackID = s.TrackID
            INNER JOIN x_config_tracking_params
                    ON x_config_tracking_params.ParamID = s.TrackParamID
            WHERE ISNULL(clients_tracking_det.TrackID)
        """
        cursor.execute(count_det_sql)
        (rows_det_to_insert,) = cursor.fetchone()
        print(f"   [{ENTITY_KEY}] Se van a insertar {rows_det_to_insert} registros en clients_tracking_det.")

        insert_det_sql = f"""
            INSERT INTO
                clients_tracking_det
                (
                    TrackGID,
                    TrackParamID,
                    TrackValue,
                    __MigTrackGID,
                    __MigTrackID
                )
            SELECT
                clients_tracking_gen.TrackGID,
                x_config_tracking_params.ParamID,
                s.TrackValue,
                s.TrackGID,
                s.TrackID
            FROM
                {mig_table} s
                INNER JOIN clients_tracking_gen
                        ON clients_tracking_gen.__MigTrackGID = s.TrackGID
                LEFT JOIN clients_tracking_det
                       ON clients_tracking_det.__MigTrackID = s.TrackID
                INNER JOIN x_config_tracking_params
                        ON x_config_tracking_params.ParamID = s.TrackParamID
            WHERE
                ISNULL(clients_tracking_det.TrackID)
            GROUP BY
                s.TrackID
        """
        cursor.execute(insert_det_sql)
        conn.commit()
        rows_det_inserted = cursor.rowcount
        print(f"   [{ENTITY_KEY}] Insertados {rows_det_inserted} registros en clients_tracking_det.")

        return {
            "status": "ok",
            "rows_mig": rows_mig,
            "rows_clients_tracking_gen": rows_gen_inserted,
            "rows_clients_tracking_det": rows_det_inserted,
        }

    except Exception as e:
        print(f"❌ Error en loader {ENTITY_KEY}: {e}")
        if stop_on_error:
            raise
        return {"status": "error", "error": str(e)}

    finally:
        conn.close()
