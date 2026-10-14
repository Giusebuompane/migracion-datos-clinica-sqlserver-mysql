import csv
import os
import io
from pathlib import Path
from datetime import datetime
import mysql.connector

# =========================================
# Configuración de conexión MySQL
# =========================================
def get_connection():
    return mysql.connector.connect(
        host=os.getenv("MYSQL_HOST"),
        database=os.getenv("MYSQL_DATABASE"),
        user=os.getenv("MYSQL_USER"),
        password=os.getenv("MYSQL_PASSWORD"),
        charset="latin1",
        use_unicode=True,
        autocommit=False,
    )


# =========================================
# Cargar CSV en la tabla de migración __mig_diary_gen_hidden
# =========================================
def load_csv_into_mig(cursor, entity_config, context):
    mig_table = entity_config.get("mig_table", "__mig_diary_gen_hidden")
    input_file = entity_config.get("input_file", "diary_gen_hidden.csv")
    input_folder = Path(context.get("input_folder", Path(".")))
    csv_path = input_folder / input_file

    if not csv_path.exists():
        raise FileNotFoundError(f"No se encontró el fichero de entrada: {csv_path}")

    print(f"   Fichero de entrada: {csv_path}")

    raw = csv_path.read_text(encoding="utf-8-sig", errors="replace")
    if not raw.strip():
        print(f"   El CSV está vacío. No se insertan filas en {mig_table}.")
        return 0

    delimiter = detect_delimiter(raw)

    f = io.StringIO(raw)
    reader = csv.DictReader(f, delimiter=delimiter)

    fieldnames = reader.fieldnames or []
    fieldnames = [fn.strip() for fn in fieldnames]

    required_cols = ["DiaryGID", "DiaryGClientID", "DiaryGClinicID", "DiaryGDate", "DiaryGStart", "DiaryGEnd"]
    missing = [c for c in required_cols if c not in fieldnames]

    if missing:
        msg = f"Las columnas del CSV no cumplen los mínimos requeridos. Faltan: {missing}"
        raise ValueError(msg)

    insert_sql = f"""
        INSERT INTO {mig_table} (
            DiaryGID,
            DiaryID,
            DiaryGClientID,
            DiaryGClinicID,
            DiaryGDate,
            DiaryGStart,
            DiaryGEnd
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s)
    """

    rows_inserted = 0

    for row in reader:
        if all((v is None or str(v).strip() == "") for v in row.values()):
            continue

        DiaryGID = parse_int(row.get("DiaryGID"))
        DiaryGClientID = parse_int(row.get("DiaryGClientID"))
        DiaryGClinicID = parse_int(row.get("DiaryGClinicID"))
        DiaryGDate = parse_date(row.get("DiaryGDate"))
        DiaryGStart = parse_time(row.get("DiaryGStart"))
        DiaryGEnd = parse_time(row.get("DiaryGEnd"))

        if DiaryGID is None or DiaryGClientID is None or DiaryGClinicID is None or DiaryGDate is None:
            continue

        data = (DiaryGID, None, DiaryGClientID, DiaryGClinicID, DiaryGDate, DiaryGStart, DiaryGEnd)
        cursor.execute(insert_sql, data)
        rows_inserted += 1

    return rows_inserted


# =========================================
# Detectar delimitador CSV
# =========================================
def detect_delimiter(raw: str) -> str:
    if not raw:
        return ";"
    first_line = raw.splitlines()[0]
    sep_semicolon = first_line.count(";")
    sep_comma = first_line.count(",")
    return ";" if sep_semicolon >= sep_comma else ","


# =========================================
# Parseo de funciones
# =========================================
def parse_int(val, default=None):
    v = clean_token(val)
    if v is None:
        return default
    try:
        return int(v)
    except (ValueError, TypeError):
        return default


def parse_time(val):
    v = clean_token(val)
    if v is None:
        return None
    try:
        return datetime.strptime(v, "%H:%M:%S").time()
    except ValueError:
        return None


def parse_date(val):
    v = clean_token(val)
    if v is None:
        return None
    try:
        return datetime.strptime(v, "%Y-%m-%d").date()
    except ValueError:
        return None


def clean_token(val):
    if val is None:
        return None
    if not isinstance(val, str):
        val = str(val)
    v = val.strip()
    if v == "" or v.upper() == "NULL":
        return None
    return v


# =========================================
# Carga de datos en diary_gen
# =========================================
def insert_into_diary_gen(cursor):
    insert_sql = """
        INSERT INTO diary_gen
        (
            DiaryGClinicID,
            DiaryGClientID,
            DiaryGDate,
            DiaryGStart,
            DiaryGEnd,
            DiaryGCreated,
            DiaryGInvisible,
            __MigDiaryGID
        )
        SELECT
            x_config_clinics.ClinicID,
            clients.ClientID,
            s.DiaryGDate,
            s.DiaryGStart,
            s.DiaryGEnd,
            s.DiaryGDate,
            -1,
            s.DiaryGID
        FROM
            __mig_diary_gen_hidden s
            INNER JOIN clients ON clients.ClientID = s.DiaryGClientID
            INNER JOIN x_config_clinics ON x_config_clinics.ClinicID = s.DiaryGClinicID
            LEFT JOIN diary_gen ON diary_gen.__MigDiaryGID = s.DiaryGID
        WHERE
            ISNULL(diary_gen.DiaryGID)
        GROUP BY 
            s.DiaryGID
    """
    cursor.execute(insert_sql)


# =========================================
# Comprobación y adición de columnas si no existen
# =========================================
def add_column_if_not_exists(cursor, table_name: str, column_name: str, column_definition: str):
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
    if count > 0:
        print(f"   La columna {table_name}.{column_name} ya existe.")
        return

    sql = f"ALTER TABLE `{table_name}` ADD COLUMN `{column_name}` {column_definition}"
    print(f"   Añadiendo columna {table_name}.{column_name}...")
    cursor.execute(sql)


# =========================================
# Script principal
# =========================================
def run(entity_config: dict, context: dict):
    conn = get_connection()
    cursor = conn.cursor()

    try:
        # 1) Crear tabla __mig_diary_gen_hidden
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS `__mig_diary_gen_hidden` (
                `DiaryGID` INT(11) NULL DEFAULT NULL,
                `DiaryID` INT(11) NULL DEFAULT NULL,
                `DiaryGClientID` INT(11) NULL DEFAULT NULL,
                `DiaryGClinicID` INT(11) NULL DEFAULT NULL,
                `DiaryGDate` DATE NULL DEFAULT NULL,
                `DiaryGStart` TIME NULL DEFAULT NULL,
                `DiaryGEnd` TIME NULL DEFAULT NULL
            )
            COLLATE='latin1_spanish_ci'
            ENGINE=MyISAM;
        """)

        # 2) Agregar columna a diary_gen solo si no existe
        add_column_if_not_exists(cursor, "diary_gen", "__MigDiaryGID", "INT NULL DEFAULT NULL")
        
        # 3) Cargar CSV en tabla de migración
        load_csv_into_mig(cursor, {"mig_table": "__mig_diary_gen_hidden", "input_file": "diary_gen_hidden.csv"}, {"input_folder": "input"})

        # 4) Insertar registros en diary_gen
        insert_into_diary_gen(cursor)

        # 5) Confirmar transacciones
        conn.commit()

    except Exception as e:
        print(f"Error: {e}")
        conn.rollback()
    finally:
        conn.close()


if __name__ == "__main__":
    run()