import csv
import io
from pathlib import Path
from datetime import datetime

from step02_db import get_connection

ENTITY_KEY = "files"

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
        "%Y/%m/%d",              # <-- AÑADIR
        "%d/%m/%Y %H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y/%m/%d %H:%M:%S",     # <-- AÑADIR (por si viene con hora)
        "%Y-%m-%d %H:%M:%S.%f",
        "%d/%m/%Y %H:%M",
        "%Y-%m-%d %H:%M",
        "%Y/%m/%d %H:%M",        # <-- AÑADIR
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
# CSV → __mig_files
# =========================

def load_csv_into_mig(cursor, entity_config: dict, context: dict) -> int:
    """
    Carga el CSV indicado en entity_config["input_file"] en la tabla __mig_files.
    Solo rellena:
      - FileClientID
      - FileName
      - FileClassID (opcional)
      - FilePath
      - FileDate
    El FileID se setea después vía UPDATE con @LastFileID.
    """
    mig_table = entity_config.get("mig_table", "__mig_files")
    input_file = entity_config.get("input_file", "files.csv")
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
        # FileClientID
        "fileclientid": "FileClientID",
        "clientid": "FileClientID",
        "idclient": "FileClientID",
        "idcliente": "FileClientID",
        "clienteid": "FileClientID",
        "originalclientid": "FileClientID", 

        # FileName
        "filename": "FileName",
        "file_name": "FileName",
        "name": "FileName",
        "nombre": "FileName",

        # FileClassID
        "fileclassid": "FileClassID",
        "classid": "FileClassID",
        "idclass": "FileClassID",
        "filetype": "FileClassID",
        "tipofichero": "FileClassID",

        # FilePath
        "filepath": "FilePath",
        "file_path": "FilePath",
        "path": "FilePath",
        "origen": "FilePath",
        "sourcepath": "FilePath",

        # FileDate
        "filedate": "FileDate",
        "date": "FileDate",
        "fecha": "FileDate",
        "createdate": "FileDate",
        "fechafichero": "FileDate",
        
        # FileComments
        "filecomments": "FileComments",
        "comments": "FileComments",
        "comment": "FileComments",
        "observaciones": "FileComments",
        "nota": "FileComments",
        "notas": "FileComments",
        
    }

    mapped_headers = []
    for h in headers:
        key = "".join(ch for ch in h.lower() if ch.isalnum() or ch == "_")
        mapped_headers.append(alias_map.get(key, h))

    reader.fieldnames = mapped_headers
    headers = mapped_headers

    required_cols = {"FileClientID", "FileName", "FilePath"}
    missing_req = [c for c in required_cols if c not in headers]
    if missing_req:
        msg = (
            "Las columnas del CSV no coinciden con lo esperado para files.\n"
            f"   Encontradas: {headers}\n"
            f"   Requeridas al menos: {sorted(required_cols)}"
        )
        raise ValueError(msg)

    insert_sql = f"""
        INSERT INTO {mig_table} (
            FileID,
            FileClientID,
            FileName,
            FileClassID,
            FilePath,
            FileDate,
            FileComments
        ) VALUES (%s,%s,%s,%s,%s,%s,%s)
    """

    # =========================
    # OPTIMIZACIÓN: batch insert (executemany)
    # =========================
    batch_size = int(entity_config.get("batch_size", 2000))
    batch = []
    rows_inserted = 0

    for row in reader:
        # saltar filas 100% vacías
        if all((v is None or str(v).strip() == "") for v in row.values()):
            continue

        FileID = None  # se rellena después con @LastFileID
        FileClientID = parse_int(row.get("FileClientID"))
        FileName = normalize_latin1(row.get("FileName"))
        FileClassID = parse_int(row.get("FileClassID"))
        FilePath = normalize_latin1(row.get("FilePath"))
        FileDate = parse_date(row.get("FileDate"))
        FileComments = normalize_latin1(row.get("FileComments"))

        # si no hay cliente o nombre o path, no tiene sentido importar
        if FileClientID is None or not FileName or not FilePath:
            continue

        data = (
            FileID,
            FileClientID,
            FileName,
            FileClassID,
            FilePath,
            FileDate,
            FileComments,
        )

        batch.append(data)

        if len(batch) >= batch_size:
            cursor.executemany(insert_sql, batch)
            rows_inserted += len(batch)
            batch.clear()

    # flush final
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
    Proceso de migración para 'files':

      1) DROP + CREATE de __mig_files (DDL EXACTO proporcionado)
      2) Carga CSV en __mig_files
      3) SET @LastFileID con MAX(files.FileID)
      4) UPDATE __mig_files.FileID = @LastFileID := @LastFileID + 1
      5) SELECT COUNT(*) previo usando el mismo SELECT del INSERT
      6) INSERT INTO files (...) SELECT ... FROM __mig_files JOIN clients ...
      7) SET @IISPath = CONCAT('C:\\inetpub\\wwwroot\\_flowww\\',@@hostname,...)
      8) Generación de archivo CSV en /output
    """
    mig_table = entity_config.get("mig_table", "__mig_files")
    stop_on_error = bool(context.get("stop_on_error", True))

    input_folder = Path(context.get("input_folder", Path(".")))
    output_folder = Path(context.get("output_folder", input_folder.parent / "output"))
    output_folder.mkdir(parents=True, exist_ok=True)

    conn = get_connection()
    cursor = conn.cursor()

    try:
        # 1) Recrear tabla de migración
        print(f"   [{ENTITY_KEY}] Paso 1/8: Recreando tabla {mig_table}...")
        cursor.execute(f"DROP TABLE IF EXISTS {mig_table}")

        create_sql = """
CREATE TABLE `__mig_files` (
	`FileID` INT(11) NULL DEFAULT NULL,
	`FileClientID` INT(11) NULL DEFAULT NULL,
	`FileName` VARCHAR(255) NULL DEFAULT NULL COLLATE 'latin1_spanish_ci',
	`FileClassID` INT(11) NULL DEFAULT NULL,
	`FilePath` VARCHAR(255) NULL DEFAULT NULL COLLATE 'latin1_spanish_ci',
	`FileDate` DATE NULL DEFAULT NULL,
    `FileComments` VARCHAR(255) NULL DEFAULT NULL COLLATE 'latin1_spanish_ci'
)
COLLATE='latin1_spanish_ci'
ENGINE=MyISAM
"""
        cursor.execute(create_sql)
        conn.commit()

        # 2) Cargar CSV en __mig_files
        print(f"   [{ENTITY_KEY}] Paso 2/8: Cargando CSV en {mig_table}...")
        rows_mig = load_csv_into_mig(cursor, entity_config, context)
        conn.commit()

        if rows_mig == 0:
            msg = f"No se han insertado filas en la tabla de migración {mig_table}."
            print(f"   [{ENTITY_KEY}] ⚠ {msg}")
            if stop_on_error:
                raise RuntimeError(msg)
            return {"status": "no-data", "rows_mig": 0}

        # 3) SET @LastFileID
        print(f"   [{ENTITY_KEY}] Paso 3/8: Calculando @LastFileID desde files...")
        cursor.execute("SET @LastFileID=IFNULL((SELECT MAX(files.FileID) FROM files),0);")

        # 4) UPDATE __mig_files para numerar FileID
        print(f"   [{ENTITY_KEY}] Paso 4/8: Actualizando FileID en __mig_files...")
        cursor.execute("UPDATE __mig_files SET __mig_files.FileID= @LastFileID := @LastFileID + 1;")
        conn.commit()

        # 5) SELECT COUNT(*) previo (misma lógica que el INSERT)
        print(f"   [{ENTITY_KEY}] Paso 5/8: Comprobando si hay datos para insertar en files...")
        check_sql = """
        SELECT COUNT(*) FROM (
            SELECT
                __mig_files.FileID
            FROM
                __mig_files
                INNER JOIN clients ON clients.ClientID=__mig_files.FileClientID
        ) t;
        """
        cursor.execute(check_sql)
        rows_to_insert = cursor.fetchone()[0] or 0

        if rows_to_insert == 0:
            msg = "No se han encontrado datos válidos para insertar en files (JOIN con clients)."
            print(f"   [{ENTITY_KEY}] ⚠ {msg}")
            if stop_on_error:
                raise RuntimeError(msg)
            return {
                "status": "no-data",
                "rows_mig": rows_mig,
                "rows_files": 0,
            }

        print(f"   [{ENTITY_KEY}] Se van a insertar {rows_to_insert} registros en files.")

        # 6) INSERT definitivo en files
        print(f"   [{ENTITY_KEY}] Paso 6/8: Insertando en tabla files...")
        insert_sql = """
INSERT INTO
	files
	(
		FileID,
		FileClientID,
		FileName,
		FileClassID,
		FileDate,
        FileComments
        FileCloudStored
	)
SELECT
	__mig_files.FileID,
	clients.ClientID,
	__mig_files.FileName,
	__mig_files.FileClassID,
	__mig_files.FileDate,
    ifnull(__mig_files.FileComments,""),
    -1 AS FileCloudStored
FROM
	__mig_files
	INNER JOIN clients ON clients.ClientID=__mig_files.FileClientID;
"""
        cursor.execute(insert_sql)
        conn.commit()
        rows_files = cursor.rowcount
        print(f"   [{ENTITY_KEY}] ✔ Registros insertados en files: {rows_files}")

        # 8) Generación de archivo CSV en /output
        print(f"   [{ENTITY_KEY}] Paso 8/8: Generando archivo CSV en carpeta output...")

        # Nuevas variables de entorno SQL
        cursor.execute("SET @RegionBucket=REPLACE(LEFT(@@hostname,2),'rc','eu');")
        cursor.execute("SET @IISPath=CONCAT(@RegionBucket,'.flowww.net\\\\',REPLACE(DATABASE(),'flowww_',''),'\\\\files');")

        # Nuevo Query SQL
        cursor.execute(
            """
            SELECT
                __mig_files.FilePath,
                CONCAT(@IISPath,'\\\\',LPAD(__mig_files.FileID,9,0),'_',__mig_files.FileName) AS FileRemoteName
            FROM
                __mig_files
                INNER JOIN files ON files.FileID = __mig_files.FileID;
            """
        )
        rows = cursor.fetchall()

        if not rows:
            print(f"   [{ENTITY_KEY}] ⚠ No se han generado líneas para el CSV (quizá no hay paths válidos).")
            csv_path = None
        else:
            # Crear CSV con las filas extraídas
            output_csv_name = entity_config.get("output_csv", "files_export.csv")
            csv_path = output_folder / output_csv_name

            with open(csv_path, mode="w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f, delimiter=";")
                # Cabeceras dinámicas sacadas de la nueva Query (FilePath, FileRemoteName)
                headers = [desc[0] for desc in cursor.description]
                writer.writerow(headers)
                writer.writerows(rows)

            print(f"   [{ENTITY_KEY}] ✔ Archivo CSV generado en: {csv_path}")

        return {
            "status": "ok",
            "rows_mig": rows_mig,
            "rows_files": rows_files,
            "csv_path": str(csv_path) if rows else None,
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