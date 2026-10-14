import csv
import io
import re
from pathlib import Path
from datetime import datetime
from decimal import Decimal, InvalidOperation

from step02_db import get_connection

ENTITY_KEY = "clients_crm"


# =========================================
# Helpers básicos (alineados con otros loaders)
# =========================================
def normalize_latin1(text: str | None) -> str | None:
    """
    Normaliza una cadena a latin1, reemplazando caracteres no representables.
    Evita errores de 'Failed converting Python str' con el conector MySQL.
    """
    if text is None:
        return None
    if not isinstance(text, str):
        text = str(text)
    try:
        return text.encode("latin-1", errors="replace").decode("latin-1", errors="replace")
    except Exception:
        return text


def clean_xml_text(text: str | None) -> str | None:
    """
    Limpia el texto para evitar errores en el XML de ASP:
    1. Elimina etiquetas <br> y cualquier otra etiqueta HTML.
    2. Escapa los caracteres prohibidos (&, <, >, ", ').
    3. Elimina caracteres de control no imprimibles.
    """
    if text is None:
        return None
    if not isinstance(text, str):
        text = str(text)
    
    # 1. Eliminar etiquetas HTML para evitar etiquetas anidadas en atributos XML
    text = re.sub(r'<br\s*/?>', ' ', text, flags=re.IGNORECASE)
    text = re.sub(r'<[^>]+>', '', text)
    
    # 2. Escapar caracteres conflictivos
    text = (
        text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&apos;")
    )
    
    # 3. Eliminar caracteres de control (ASCII 0-31) excepto tab, salto de línea y retorno
    text = "".join(c for c in text if ord(c) >= 32 or c in "\t\n\r")
    
    return text


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
        return default


def parse_decimal(val, default=None):
    v = clean_token(val)
    if v is None:
        return default
    v = v.replace(",", ".")
    try:
        return Decimal(v)
    except (InvalidOperation, ValueError):
        return default


def parse_date(val):
    """
    Devuelve un datetime.date o None.
    Acepta:
      - dd/mm/yyyy
      - yyyy-mm-dd
      - dd/mm/yyyy HH:MM[:SS[.fff]]
      - yyyy-mm-dd HH:MM[:SS[.fff]]
    """
    v = clean_token(val)
    if v is None:
        return None

    formats = [
        # Con milisegundos
        "%Y-%m-%d %H:%M:%S.%f",
        "%d/%m/%Y %H:%M:%S.%f",
        # Sin milisegundos
        "%Y-%m-%d %H:%M:%S",
        "%d/%m/%Y %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%d/%m/%Y %H:%M",
        # Solo fecha
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


# =========================================
# Carga del CSV en tabla de migración
# =========================================
def load_csv_into_mig(cursor, entity_config: dict, context: dict) -> int:
    """
    Carga el CSV de clients_crm en la tabla __mig_clients_crm.
    Aplica:
      - detección de separador (coma / punto y coma)
      - manejo de BOM en cabeceras
      - conversión de fechas
      - limpieza básica de textos (incluyendo limpieza XML en comentarios)
    Devuelve el número de filas insertadas.
    """
    mig_table = entity_config.get("mig_table", "__mig_clients_crm")
    input_file = entity_config.get("input_file", "clients_crm.csv")
    input_folder = Path(context.get("input_folder", Path(".")))
    csv_path = input_folder / input_file

    print(f"   [{ENTITY_KEY}] Fichero de entrada: {csv_path}")

    if not csv_path.exists():
        raise FileNotFoundError(f"Fichero no encontrado: {csv_path}")

    # Leemos el contenido para poder detectar el delimitador
    raw = csv_path.read_text(encoding="utf-8-sig", errors="replace")
    if not raw.strip():
        print(f"   [{ENTITY_KEY}] El CSV está vacío. No se insertan filas en {mig_table}.")
        return 0

    first_line = raw.splitlines()[0]
    sep_semicolon = first_line.count(";")
    sep_comma = first_line.count(",")

    if sep_semicolon >= sep_comma:
        delimiter = ";"
    else:
        delimiter = ","

    f = io.StringIO(raw)
    reader = csv.DictReader(f, delimiter=delimiter)

    # Normalizamos posibles BOM en la primera cabecera
    if reader.fieldnames and reader.fieldnames[0] and reader.fieldnames[0].startswith("ï»¿"):
        reader.fieldnames[0] = reader.fieldnames[0].replace("ï»¿", "")

    fieldnames = reader.fieldnames or []
    fieldnames = [fn.strip() if fn else fn for fn in fieldnames]
    print(f"   [{ENTITY_KEY}] Cabeceras encontradas en CSV: {fieldnames}")

    # Columnas mínimas requeridas (según definición de la tabla de migración)
    required_cols = {
        "ClientCID",
        "ClinicID",
        "ClientID",
        "ClientCDate",
        "ClientCComments",
    }

    missing = [c for c in required_cols if c not in fieldnames]
    if missing:
        msg = (
            "Las columnas del CSV no coinciden.\n"
            f"   Encontradas: {fieldnames}\n"
            f"   Requeridas al menos: {sorted(required_cols)}"
        )
        raise ValueError(msg)

    insert_sql = f"""
        INSERT INTO {mig_table} (
            ClientCID,
            ClinicID,
            ClientID,
            ClientCDate,
            ClientCComments
        ) VALUES (
            %s,%s,%s,%s,%s
        )
    """

    # =========================================
    # MEJORA: inserts por lotes con executemany()
    # =========================================
    inserted = 0
    batch = []
    batch_size = int(entity_config.get("batch_size", 1000))

    for row in reader:
        ClientCID = parse_int(row.get("ClientCID"))
        ClinicID = parse_int(row.get("ClinicID"))
        ClientID = parse_int(row.get("ClientID"))
        ClientCDate = parse_date(row.get("ClientCDate"))
        # Limpieza XML + normalización latin1 en comentarios
        ClientCComments = normalize_latin1(clean_xml_text(row.get("ClientCComments")))

        data = (
            ClientCID,
            ClinicID,
            ClientID,
            ClientCDate,
            ClientCComments,
        )

        batch.append(data)

        if len(batch) >= batch_size:
            cursor.executemany(insert_sql, batch)
            inserted += len(batch)
            batch.clear()

    # Flush final
    if batch:
        cursor.executemany(insert_sql, batch)
        inserted += len(batch)

    print(f"   [{ENTITY_KEY}] Filas insertadas en {mig_table}: {inserted}")
    return inserted


# =========================================
# RUN principal
# =========================================
def run(entity_config: dict, context: dict):
    """
    Proceso de migración para 'clients_crm':

      1) DROP + CREATE de __mig_clients_crm
      2) Carga CSV en __mig_clients_crm
      3) Inserción en clients_crm (previo SELECT de comprobación),
         usando la query original basada en @sImportID.
    """
    mig_table = entity_config.get("mig_table", "__mig_clients_crm")
    stop_on_error = bool(context.get("stop_on_error", True))

    conn = get_connection()
    cursor = conn.cursor()

    try:
        # 0) PREPARAR TABLA DESTINO
        print(f"   [{ENTITY_KEY}] Asegurando columnas de migración en tabla destino...")
        try:
            # Forzamos la creación sin IF NOT EXISTS por si es una versión antigua, 
            # manejando el error si ya existe.
            cursor.execute("ALTER TABLE clients_crm ADD __MigClientCID INT NULL")
            conn.commit()
        except Exception as e:
            # Si el error es 1060 (columna duplicada), lo ignoramos
            if '1060' not in str(e):
                print(f"   [Aviso] No se pudo añadir la columna: {e}")
            
        # 1) Eliminar y crear tabla de migración
        print(f"   [{ENTITY_KEY}] Recreando tabla {mig_table}...")
        cursor.execute(f"DROP TABLE IF EXISTS {mig_table}")

        create_mig_sql = f"""
        CREATE TABLE {mig_table} (
            ClientCID INT PRIMARY KEY,
            ClinicID INT,
            ClientID INT,
            ClientCDate DATE,
            ClientCComments TEXT,
            ClientCUserID INT	
        )
        ENGINE=InnoDB
        DEFAULT CHARSET=latin1
        COLLATE=latin1_spanish_ci;
        """
        cursor.execute(create_mig_sql)
        conn.commit()

        # 2) Cargar CSV en tabla de migración
        try:
            rows_mig = load_csv_into_mig(cursor, entity_config, context)
            conn.commit()
        except Exception as e:
            print(f"   ❌ Error cargando CSV en {mig_table}: {e}")
            if stop_on_error:
                raise
            return False

        if rows_mig == 0:
            print(f"   [{ENTITY_KEY}] No hay filas en {mig_table}. Se omite la inserción en clients_crm.")
            return True

        # 3) Inserción en clients_crm
        print(f"   [{ENTITY_KEY}] Preparando inserción en clients_crm...")

        # Respetamos la lógica original: mismo @sImportID basado en la fecha actual
        set_import_sql = "SET @sImportID = CAST(DATE_FORMAT(NOW(), '%Y%m%d') AS UNSIGNED);"
        cursor.execute(set_import_sql)

        # SELECT previo para ver si se insertarán registros
        check_sql = f"""
        SELECT COUNT(*)
        FROM {mig_table} s
        INNER JOIN clients c ON c.ClientID = s.ClientID
        INNER JOIN x_config_clinics cc 
            ON c.ClientClinicID = cc.ClinicID;
        """
        cursor.execute(check_sql)
        rows_to_insert = cursor.fetchone()[0] or 0

        if rows_to_insert == 0:
            msg = (
                f"No se han encontrado datos para insertar en clients_crm "
                f"desde {mig_table} (JOIN con clients + ClientImportID = @sImportID)."
            )
            print(f"   ⚠ {msg}")
            if stop_on_error:
                raise RuntimeError(msg)
            return True

        print(f"   [{ENTITY_KEY}] Se van a insertar {rows_to_insert} registros en clients_crm.")

        insert_sql = f"""
        INSERT INTO 
            clients_crm 
            (
                ClientCClientID,
                ClientCComments,
                ClientCDate,
                ClientCTime,
                ClientCUserID,
                ClientCImportID,
                __MigClientCID
            )
        SELECT
            c.ClientID,
            s.ClientCComments,
            IFNULL(s.ClientCDate, CURDATE()),
            '09:00',
            IFNULL(xcu.UserID,0),
            @sImportID,
            s.ClientCID
        FROM 
            {mig_table} s
           INNER JOIN clients c ON c.ClientID = s.ClientID
            INNER JOIN x_config_clinics cc 
                ON c.ClientClinicID = cc.ClinicID
             LEFT JOIN __mapping_users mpu ON mpu.id = s.ClientCUserID
              LEFT JOIN x_config_users xcu ON xcu.UserID = mpu.idFlowww;
        """
        cursor.execute(insert_sql)
        conn.commit()
        print(f"   [{ENTITY_KEY}] Registros insertados en clients_crm: {cursor.rowcount}")

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
