import csv
import io
from pathlib import Path
from datetime import datetime
from step02_db import get_connection

ENTITY_KEY = "pictures"

# =========================
# Helpers (alineados con otros loaders)
# =========================

def normalize_latin1(text: str | None) -> str | None:
    """Normaliza a latin1 y reemplaza caracteres no representables."""
    if text is None:
        return None
    if not isinstance(text, str):
        text = str(text)

    # quitar posibles caracteres bidi/raros (igual que otros loaders)
    bad_chars = "\u202a\u202b\u202c\u202d\u202e"
    for ch in bad_chars:
        text = text.replace(ch, "")

    return text.encode("latin-1", errors="replace").decode("latin-1", errors="replace")


def clean_token(val):
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
        return default


def parse_date(val):
    """
    Tolerante a varios formatos de fecha típicos.
    Devuelve date o None.
    """
    v = clean_token(val)
    if v is None:
        return None

    formats = [
        "%d/%m/%Y",
        "%d-%m-%Y",
        "%Y-%m-%d",
        "%d/%m/%Y %H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M:%S.%f",
        "%d/%m/%Y %H:%M",
        "%Y-%m-%d %H:%M",
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


def detect_delimiter(raw: str) -> str:
    if not raw:
        return ";"
    first_line = raw.splitlines()[0]
    return ";" if first_line.count(";") >= first_line.count(",") else ","


def normalize_header(h: str) -> str:
    return (h or "").lstrip("\ufeff").strip()


# =========================
# CSV → __mig_pictures
# =========================

def load_csv_into_mig(cursor, entity_config: dict, context: dict) -> int:
    """
    Carga el CSV indicado en entity_config["input_file"] en la tabla __mig_pictures.
    Solo rellena:
      - PictureClientID
      - PictureComments
      - PictureDate
      - PicturePath
    El PictureID se setea después vía UPDATE con @LastPictureID.
    """
    mig_table = entity_config.get("mig_table", "__mig_pictures")
    input_file = entity_config.get("input_file", "pictures.csv")
    input_folder = Path(context.get("input_folder", Path(".")))
    csv_path = input_folder / input_file

    print(f"   [{ENTITY_KEY}] Fichero de entrada: {csv_path}")

    if not csv_path.exists():
        raise FileNotFoundError(f"No se encontró el fichero de entrada: {csv_path}")

    raw = csv_path.read_text(encoding="utf-8-sig", errors="replace")
    if not raw.strip():
        print(f"   [{ENTITY_KEY}] El CSV está vacío. No se insertan filas en {mig_table}.")
        return 0

    delimiter = detect_delimiter(raw)
    f = io.StringIO(raw)
    reader = csv.DictReader(f, delimiter=delimiter)

    raw_headers = reader.fieldnames or []
    headers = [normalize_header(h) for h in raw_headers]

    # Alias de columnas para ser tolerantes con el naming
    alias_map = {
        # PictureClientID
        "pictureclientid": "PictureClientID",
        "clientid": "PictureClientID",
        "idclient": "PictureClientID",
        "idcliente": "PictureClientID",
        "clienteid": "PictureClientID",
        "originalclientid": "PictureClientID",

        # PictureClinicID (Nuevo para hacerlo multicentro)
        "pictureclinicid": "PictureClinicID",
        "clinicid": "PictureClinicID",

        # PictureComments
        "picturecomments": "PictureComments",
        "comments": "PictureComments",
        "comment": "PictureComments",
        "observaciones": "PictureComments",
        "nota": "PictureComments",
        "notas": "PictureComments",

        # PicturePath
        "picturepath": "PicturePath",
        "file_path": "PicturePath",
        "filepath": "PicturePath",
        "path": "PicturePath",
        "origen": "PicturePath",
        "sourcepath": "PicturePath",

        # PictureDate
        "picturedate": "PictureDate",
        "date": "PictureDate",
        "fecha": "PictureDate",
        "createdate": "PictureDate",
        "fechafoto": "PictureDate",
    }

    mapped_headers = []
    for h in headers:
        key = "".join(ch for ch in h.lower() if ch.isalnum() or ch == "_")
        mapped_headers.append(alias_map.get(key, h))

    reader.fieldnames = mapped_headers
    headers = mapped_headers

    # Requerimos mínimo cliente, clinic y path; comentarios y fecha pueden ser opcionales
    required_cols = {"PictureClientID", "PictureClinicID", "PicturePath"}
    missing_req = [c for c in required_cols if c not in headers]
    if missing_req:
        msg = (
            "Las columnas del CSV no coinciden con lo esperado para pictures.\n"
            f"   Encontradas: {headers}\n"
            f"   Requeridas al menos: {sorted(required_cols)}"
        )
        raise ValueError(msg)

    insert_sql = f"""
        INSERT INTO {mig_table} (
            PictureID,
            PictureClientID,
            PictureClinicID,
            PictureComments,
            PictureDate,
            PicturePath
        ) VALUES (%s,%s,%s,%s,%s,%s)
    """

    # =========================
    # CARGA RÁPIDA (batch)
    # =========================
    batch_size = int(context.get("csv_batch_size", 1000))
    batch = []
    rows_inserted = 0

    for row in reader:
        # saltar filas 100% vacías
        if all((v is None or str(v).strip() == "") for v in row.values()):
            continue

        PictureID = None  # se rellena después con @LastPictureID
        PictureClientID = parse_int(row.get("PictureClientID"))
        PictureClinicID = parse_int(row.get("PictureClinicID"))  # Nuevo campo para multicentro
        PictureComments = normalize_latin1(row.get("PictureComments"))
        PicturePath = normalize_latin1(row.get("PicturePath"))
        PictureDate = parse_date(row.get("PictureDate"))

        # si no hay cliente, clinic o path, no tiene sentido importar
        if PictureClientID is None or PictureClinicID is None or not PicturePath:
            continue

        data = (
            PictureID,
            PictureClientID,
            PictureClinicID,
            PictureComments,
            PictureDate,
            PicturePath,
        )
        batch.append(data)

        if len(batch) >= batch_size:
            cursor.executemany(insert_sql, batch)
            rows_inserted += len(batch)
            batch.clear()

    if batch:
        cursor.executemany(insert_sql, batch)
        rows_inserted += len(batch)
        batch.clear()

    print(f"   [{ENTITY_KEY}] Filas insertadas en {mig_table}: {rows_inserted}")
    return rows_inserted


# =========================
# RUN principal
# =========================

def run(entity_config: dict, context: dict):
    """
    Flujo (según instrucciones del usuario):

      Paso 1: CREATE TABLE __mig_pictures
      Paso 2: SET @LastPictureID y UPDATE __mig_pictures.PictureID incremental
      Paso 3: SET @PictureDownSample (solo set, no se usa aquí)
      Paso 4: INSERT INTO pictures ... SELECT ... (con pre-check)
      Paso 5: Ejecución de Query para CSV (en Python)
    """
    mig_table = entity_config.get("mig_table", "__mig_pictures")
    stop_on_error = bool(context.get("stop_on_error", True))

    input_folder = Path(context.get("input_folder", Path(".")))
    # Respetar estructura anterior: /output al mismo nivel que /input
    output_folder = Path(context.get("output_folder", input_folder.parent / "output"))
    output_folder.mkdir(parents=True, exist_ok=True)

    conn = get_connection()
    cursor = conn.cursor()

    csv_path = None

    try:
        # Paso 1: crear tabla migración (idéntico al DDL proporcionado)
        print(f"   [{ENTITY_KEY}] Paso 1/5: Recreando tabla {mig_table}...")
        cursor.execute(f"DROP TABLE IF EXISTS {mig_table}")

        create_sql = """
CREATE TABLE `__mig_pictures` (
    `PictureID` INT(11) NULL DEFAULT NULL,
    `PictureClientID` INT(11) NULL DEFAULT NULL,
    `PictureClinicID` INT(11) NULL DEFAULT NULL,
    `PictureComments` VARCHAR(255) NULL DEFAULT NULL COLLATE 'latin1_spanish_ci',
    `PictureDate` DATE NULL DEFAULT NULL,
    `PicturePath` VARCHAR(255) NULL DEFAULT NULL COLLATE 'latin1_spanish_ci'
)
COLLATE='latin1_spanish_ci'
ENGINE=MYISAM;
"""
        cursor.execute(create_sql)
        conn.commit()

        # Cargar CSV en __mig_pictures (PictureID queda NULL por ahora)
        print(f"   [{ENTITY_KEY}] Cargando CSV en {mig_table}...")
        rows_mig = load_csv_into_mig(cursor, entity_config, context)
        conn.commit()

        if rows_mig == 0:
            msg = f"No se han insertado filas en la tabla de migración {mig_table}."
            print(f"   [{ENTITY_KEY}] ⚠ {msg}")
            if stop_on_error:
                raise RuntimeError(msg)
            return {"status": "no-data", "rows_mig": 0}

        # Paso 2: set last id + update mig
        print(f"   [{ENTITY_KEY}] Paso 2/5: SET @LastPictureID y UPDATE __mig_pictures.PictureID...")
        cursor.execute("SET @LastPictureID=IFNULL((SELECT MAX(pictures.PictureID) FROM pictures),0);")
        cursor.execute("""UPDATE __mig_pictures SET __mig_pictures.PictureID= @LastPictureID := @LastPictureID + 1;""")
        conn.commit()

        # Paso 3: set downsample variable
        print(f"   [{ENTITY_KEY}] Paso 3/5: SET @PictureDownSample...")
        cursor.execute("""SET @PictureDownSample = IFNULL(
    (SELECT xcs.SettingValue FROM x_config_settings xcs WHERE xcs.SettingName='SET_CLIENT_PICTURES_DOWNSAMPLE'),
    -1);""")
        conn.commit()

        # Paso 4: pre-check (si no hay resultados, error y salida)
        print(f"   [{ENTITY_KEY}] Paso 4/5: Pre-check INSERT pictures (SELECT)...")
        check_sql = """
SELECT COUNT(*) FROM (
SELECT
    PictureID
FROM
    __mig_pictures
    INNER JOIN clients ON clients.ClientID=__mig_pictures.PictureClientID
) t;
"""
        cursor.execute(check_sql)
        rows_to_insert = (cursor.fetchone()[0] or 0)

        if rows_to_insert == 0:
            msg = "No hay registros para insertar en pictures (JOIN con clients vacío)."
            print(f"   [{ENTITY_KEY}] ❌ {msg}")
            raise RuntimeError(msg)

        print(f"   [{ENTITY_KEY}] OK, hay {rows_to_insert} registros para insertar en pictures. Ejecutando INSERT...")
        insert_sql = """
INSERT INTO
    pictures
    (
        PictureID,
        PictureClientID,
        PictureComments,
        PictureDate,
        PictureCloudStored
    )

SELECT
    PictureID,
    clients.ClientID,
    PictureComments,
    PictureDate,
    -1 AS PictureCloudStored
FROM
    __mig_pictures
    INNER JOIN clients ON clients.ClientID=__mig_pictures.PictureClientID;
"""
        cursor.execute(insert_sql)
        conn.commit()
        rows_pictures = cursor.rowcount
        print(f"   [{ENTITY_KEY}] Insertados {rows_pictures} registros en pictures.")

        # Paso 5: Ejecución de Query para CSV proporcionada
        print(f"   [{ENTITY_KEY}] Paso 5/5: Ejecutando query y generando CSV en carpeta output...")
        
        cursor.execute("SET @RegionBucket=REPLACE(LEFT(@@hostname,2),'rc','eu');")
        cursor.execute("SET @IISPath=CONCAT(@RegionBucket,'.flowww.net\\\\',REPLACE(DATABASE(),'flowww_',''),'\\\\pictures');")

        export_sql = """
        SELECT
            __mig_pictures.PicturePath,
            CONCAT(@IISPath,'\\\\',LPAD(__mig_pictures.PictureID,9,0),IF(@PictureDownSample=-1,'_lq',''),'.jpg') AS FileRemoteName
        FROM
            __mig_pictures
            INNER JOIN pictures ON pictures.PictureID=__mig_pictures.PictureID;
        """
        cursor.execute(export_sql)
        rows = cursor.fetchall() or []

        if not rows:
            msg = "No hay líneas para generar el CSV (sin registros tras JOIN con pictures)."
            print(f"   [{ENTITY_KEY}] ❌ {msg}")
            raise RuntimeError(msg)

        output_csv_name = entity_config.get("output_csv", "copy_pictures_query.csv")
        csv_path = output_folder / output_csv_name
        
        with open(csv_path, mode="w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f, delimiter=";")
            # Extraemos cabeceras dinámicamente
            headers = [desc[0] for desc in cursor.description]
            writer.writerow(headers)
            writer.writerows(rows)

        print(f"   [{ENTITY_KEY}] ✔ Fichero CSV generado en: {csv_path}")

        return {
            "status": "ok",
            "rows_mig": rows_mig,
            "rows_pictures": rows_pictures,
            "csv_path": str(csv_path),
        }

    except Exception as e:
        print(f"❌ Error en loader {ENTITY_KEY}: {e}")
        if stop_on_error:
            raise
        return {"status": "error", "error": str(e)}

    finally:
        try:
            cursor.close()
        except Exception:
            pass
        try:
            conn.close()
        except Exception:
            pass