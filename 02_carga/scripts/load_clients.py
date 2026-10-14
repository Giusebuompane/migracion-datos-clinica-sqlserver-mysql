import csv
import io
from pathlib import Path
from datetime import datetime

from step02_db import get_connection

ENTITY_KEY = "clients"


# =========================================
# Helpers básicos
# =========================================

def truncate(text: str | None, max_len: int) -> str | None:
    """
    Trunca el texto a max_len caracteres si se pasa de largo.
    """
    if text is None:
        return None
    if not isinstance(text, str):
        text = str(text)
    if len(text) <= max_len:
        return text
    return text[:max_len]
    

def normalize_latin1(text: str | None) -> str | None:
    """
    Normaliza una cadena a latin1, reemplazando caracteres no representables.
    Además limpia caracteres de control Unicode problemáticos (marcas bidi).
    """
    if text is None:
        return None
    if not isinstance(text, str):
        text = str(text)

    # Eliminar caracteres de control bidi que suelen colarse de copiar/pegar
    # U+202A, U+202B, U+202C, U+202D, U+202E
    bad_chars = "\u202a\u202b\u202c\u202d\u202e"
    for ch in bad_chars:
        text = text.replace(ch, "")

    try:
        return text.encode("latin-1", errors="replace").decode("latin-1", errors="replace")
    except Exception:
        # En el peor caso devolvemos el original, pero ya sin bad_chars
        return text


def clean_xml_text(text: str | None) -> str | None:
    """
    Reemplaza caracteres conflictivos para XML (&, <, >, ", ').
    Igual que en otros loaders, lo usamos a nivel Python
    y luego hacemos una limpieza adicional en MySQL.
    """
    if text is None:
        return None
    return (
        text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&apos;")
    )


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
        # Soporta "1.0", "2,0", etc.
        try:
            return int(float(str(v).replace(",", ".")))
        except (ValueError, TypeError):
            return default


def parse_bool_tinyint(val, default=None):
    """
    Convierte valores tipo "1"/"0", "S"/"N", "Y"/"N", "TRUE"/"FALSE" a 1/0.
    """
    v = clean_token(val)
    if v is None:
        return default
    up = v.upper()
    if up in ("1", "S", "Y", "TRUE"):
        return 1
    if up in ("0", "N", "FALSE"):
        return 0
    # Si no es reconocible, devolvemos default
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

    # Último intento ISO
    try:
        dt = datetime.fromisoformat(v)
        return dt.date()
    except ValueError:
        return None


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


# =========================================
# Carga CSV → __mig_clients
# =========================================
def load_csv_into_mig(cursor, entity_config: dict, context: dict) -> int:
    """
    Carga el CSV de clientes en la tabla __mig_clients.
    Aplica:
      - detección de separador (coma / punto y coma)
      - manejo de BOM en cabeceras
      - conversión de fechas
      - conversión de NULL / números
      - limpieza básica de textos (latin1 + XML en ClientNotes y custom)
    Devuelve el número de filas insertadas.
    """
    mig_table = entity_config.get("mig_table", "__mig_clients")
    input_file = entity_config.get("input_file", "clients.csv")
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

    # Normalizamos posibles BOM en la primera cabecera
    if reader.fieldnames and reader.fieldnames[0].startswith("ï»¿"):
        reader.fieldnames[0] = reader.fieldnames[0].replace("ï»¿", "")

    fieldnames = reader.fieldnames or []
    fieldnames = [fn.strip() for fn in fieldnames]
    
    # Aceptar ClinicID o ClientClinicID (alias)
    if "ClinicID" not in fieldnames and "ClientClinicID" in fieldnames:
        # Mapeamos el header para que el resto del loader siga igual
        fieldnames = ["ClinicID" if fn == "ClientClinicID" else fn for fn in fieldnames]
        reader.fieldnames = fieldnames

    required_cols = ["ClientID", "ClinicID"]
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
            ClientID,
            ClinicID,
            ClientEnableRGPD,
            ClientAddress,
            ClientColony,
            ClientPostCode,
            ClientExtra,
            ClientCity,
            ClientStrNum,
            ClientCountry,
            ClientProvince,
            ClientEMail,
            ClientDate,
            ClientBirthDate,
            ClientLocalIE,
            ClientIESSUF,
            ClientName,
            ClientNotes,
            ClientNIF,
            ClientNumber,
            ClientCode,
            ClientEnableGeneralConditions,
            ClientSurname1,
            ClientRG,
            ClientSurname2,
            ClientSex,
            ClientPhone1,
            ClientPhone2,
            ClientPhone3,
            RefererDesc,
            ClientCustom1,
            ClientCustom2,
            ClientCustom3,
            ClientCustom4,
            ClientCustom5,
            ClientCustom6,
            ClientCustom7,
            ClientCustom8,
            ClientCustom9,
            ClientCustom10
        )
        VALUES (
            %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
            %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
            %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
            %s,%s,%s,%s,%s,%s,%s,%s,%s,%s
        )
    """

    # =========================================
    # MEJORA: inserts por lotes con executemany()
    # =========================================
    rows_inserted = 0
    batch = []
    batch_size = int(entity_config.get("batch_size", 1000))

    for row in reader:
        # Saltar filas totalmente vacías
        if all((v is None or str(v).strip() == "") for v in row.values()):
            continue

        ClientID = parse_int(row.get("ClientID"))
        ClinicID = parse_int(row.get("ClinicID") or row.get("ClientClinicID"))


        # Si falta el ID o la clínica, saltamos la fila
        if ClientID is None or ClinicID is None:
            continue

        ClientEnableRGPD = parse_bool_tinyint(row.get("ClientEnableRGPD"), None)

        ClientAddress  = truncate(normalize_latin1(row.get("ClientAddress")), 255)
        ClientColony   = normalize_latin1(row.get("ClientColony"))
        ClientPostCode = normalize_latin1(clean_token(row.get("ClientPostCode")))
        ClientExtra    = truncate(normalize_latin1(row.get("ClientExtra")), 255)
        ClientCity     = normalize_latin1(row.get("ClientCity"))
        ClientStrNum   = normalize_latin1(row.get("ClientStrNum"))
        ClientCountry  = normalize_latin1(row.get("ClientCountry"))
        ClientProvince = normalize_latin1(row.get("ClientProvince"))
        ClientEMail    = truncate(normalize_latin1(clean_token(row.get("ClientEMail"))), 255)

        ClientDate      = parse_date(row.get("ClientDate"))
        ClientBirthDate = parse_date(row.get("ClientBirthDate"))

        ClientLocalIE = normalize_latin1(clean_token(row.get("ClientLocalIE")))
        ClientIESSUF  = normalize_latin1(clean_token(row.get("ClientIESSUF")))

        ClientName  = truncate(normalize_latin1(row.get("ClientName")), 255)
        ClientNotes = normalize_latin1(clean_xml_text(row.get("ClientNotes")))
        ClientNIF   = normalize_latin1(clean_token(row.get("ClientNIF")))
        ClientNumber = parse_int(row.get("ClientNumber"))
        ClientCode   = normalize_latin1(clean_token(row.get("ClientCode")))

        ClientEnableGeneralConditions = parse_bool_tinyint(
            row.get("ClientEnableGeneralConditions"), None
        )

        ClientSurname1 = normalize_latin1(row.get("ClientSurname1"))
        ClientRG       = normalize_latin1(clean_token(row.get("ClientRG")))
        ClientSurname2 = normalize_latin1(row.get("ClientSurname2"))
        ClientSex      = normalize_latin1(clean_token(row.get("ClientSex")))

        ClientPhone1 = normalize_latin1(clean_token(row.get("ClientPhone1")))
        ClientPhone2 = normalize_latin1(clean_token(row.get("ClientPhone2")))
        ClientPhone3 = normalize_latin1(clean_token(row.get("ClientPhone3")))

        RefererDesc = truncate(normalize_latin1(row.get("RefererDesc")), 255)

        ClientCustom1  = truncate(normalize_latin1(clean_xml_text(row.get("ClientCustom1"))), 255)
        ClientCustom2  = truncate(normalize_latin1(clean_xml_text(row.get("ClientCustom2"))), 255)
        ClientCustom3  = truncate(normalize_latin1(clean_xml_text(row.get("ClientCustom3"))), 255)
        ClientCustom4  = truncate(normalize_latin1(clean_xml_text(row.get("ClientCustom4"))), 255)
        ClientCustom5  = truncate(normalize_latin1(clean_xml_text(row.get("ClientCustom5"))), 255)
        ClientCustom6  = truncate(normalize_latin1(clean_xml_text(row.get("ClientCustom6"))), 255)
        ClientCustom7  = truncate(normalize_latin1(clean_xml_text(row.get("ClientCustom7"))), 255)
        ClientCustom8  = truncate(normalize_latin1(clean_xml_text(row.get("ClientCustom8"))), 255)
        ClientCustom9  = truncate(normalize_latin1(clean_xml_text(row.get("ClientCustom9"))), 255)
        ClientCustom10 = truncate(normalize_latin1(clean_xml_text(row.get("ClientCustom10"))), 255)


        data = (
            ClientID,
            ClinicID,
            ClientEnableRGPD,
            ClientAddress,
            ClientColony,
            ClientPostCode,
            ClientExtra,
            ClientCity,
            ClientStrNum,
            ClientCountry,
            ClientProvince,
            ClientEMail,
            ClientDate,
            ClientBirthDate,
            ClientLocalIE,
            ClientIESSUF,
            ClientName,
            ClientNotes,
            ClientNIF,
            ClientNumber,
            ClientCode,
            ClientEnableGeneralConditions,
            ClientSurname1,
            ClientRG,
            ClientSurname2,
            ClientSex,
            ClientPhone1,
            ClientPhone2,
            ClientPhone3,
            RefererDesc,
            ClientCustom1,
            ClientCustom2,
            ClientCustom3,
            ClientCustom4,
            ClientCustom5,
            ClientCustom6,
            ClientCustom7,
            ClientCustom8,
            ClientCustom9,
            ClientCustom10,
        )

        batch.append(data)

        if len(batch) >= batch_size:
            cursor.executemany(insert_sql, batch)
            rows_inserted += len(batch)
            batch.clear()

    # Flush final
    if batch:
        cursor.executemany(insert_sql, batch)
        rows_inserted += len(batch)

    return rows_inserted


# =========================================
# RUN
# =========================================
def run(entity_config: dict, context: dict):
    """
    Proceso de migración para 'clients':
      1) DROP + CREATE de la tabla __mig_clients
      2) Carga del CSV en la tabla de migración
      3) Limpieza de caracteres conflictivos XML en ClientNotes/custom
      4) INSERT a clients con la SQL original (adaptada a mig_table)
      5) Actualizaciones posteriores (nombre, dirección, ubicaciones, referers)
    """

    mig_table = entity_config.get("mig_table", "__mig_clients")
    input_file = entity_config.get("input_file", "clients.csv")
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
        # 1) Eliminar y crear la tabla __mig_clients
        print(f"   [{ENTITY_KEY}] Recreando tabla {mig_table}.")
        cursor.execute(f"DROP TABLE IF EXISTS {mig_table}")

        create_sql = f"""
        CREATE TABLE `{mig_table}` (
            ClientID INT PRIMARY KEY,
            ClinicID INT,
            ClientEnableRGPD TINYINT(1),
            ClientAddress VARCHAR(255),
            ClientColony VARCHAR(100),
            ClientPostCode VARCHAR(20),
            ClientExtra VARCHAR(255),
            ClientCity VARCHAR(100),
            ClientStrNum VARCHAR(50),
            ClientCountry VARCHAR(100),
            ClientProvince VARCHAR(100),
            ClientEMail VARCHAR(255),
            ClientDate DATE,
            ClientBirthDate DATE,
            ClientLocalIE VARCHAR(50),
            ClientIESSUF VARCHAR(50),
            ClientName VARCHAR(255),
            ClientNotes TEXT,
            ClientNIF VARCHAR(50),
            ClientNumber INT,
            ClientCode VARCHAR(50),
            ClientEnableGeneralConditions TINYINT(1),
            ClientSurname1 VARCHAR(100),
            ClientRG VARCHAR(50),
            ClientSurname2 VARCHAR(100),
            ClientSex VARCHAR(10),
            ClientPhone1 VARCHAR(64),
            ClientPhone2 VARCHAR(64),
            ClientPhone3 VARCHAR(64),
            RefererDesc VARCHAR(255),
            ClientCustom1 VARCHAR(255),
            ClientCustom2 VARCHAR(255),
            ClientCustom3 VARCHAR(255),
            ClientCustom4 VARCHAR(255),
            ClientCustom5 VARCHAR(255),
            ClientCustom6 VARCHAR(255),
            ClientCustom7 VARCHAR(255),
            ClientCustom8 VARCHAR(255),
            ClientCustom9 VARCHAR(255),
            ClientCustom10 VARCHAR(255)
        )
        """
        cursor.execute(create_sql)
        conn.commit()

        # 2) Cargar CSV en la tabla de migración
        rows_mig = load_csv_into_mig(cursor, entity_config, context)
        conn.commit()

        if rows_mig == 0:
            msg = "No se han insertado filas en la tabla de migración de clientes."
            print(f"   [{ENTITY_KEY}] {msg}")
            if stop_on_error:
                raise ValueError(msg)
            else:
                return {"status": "no-data", "rows_mig": 0}

        # 3) Limpieza XML en textos (ClientNotes + custom)
        print(f"   [{ENTITY_KEY}] Limpiando caracteres XML en notas y campos personalizados.")
        xml_update_sql = f"""
            UPDATE {mig_table}
            SET
                ClientNotes   = LEFT(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(ClientNotes,   '&', '&amp;'), '<','&lt;'),'>','&gt;'),'"','&quot;'),"'",'&apos;'), 255),
                ClientCustom1 = LEFT(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(ClientCustom1, '&', '&amp;'), '<','&lt;'),'>','&gt;'),'"','&quot;'),"'",'&apos;'), 255),
                ClientCustom2 = LEFT(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(ClientCustom2, '&', '&amp;'), '<','&lt;'),'>','&gt;'),'"','&quot;'),"'",'&apos;'), 255),
                ClientCustom3 = LEFT(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(ClientCustom3, '&', '&amp;'), '<','&lt;'),'>','&gt;'),'"','&quot;'),"'",'&apos;'), 255),
                ClientCustom4 = LEFT(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(ClientCustom4, '&', '&amp;'), '<','&lt;'),'>','&gt;'),'"','&quot;'),"'",'&apos;'), 255),
                ClientCustom5 = LEFT(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(ClientCustom5, '&', '&amp;'), '<','&lt;'),'>','&gt;'),'"','&quot;'),"'",'&apos;'), 255),
                ClientCustom6 = LEFT(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(ClientCustom6, '&', '&amp;'), '<','&lt;'),'>','&gt;'),'"','&quot;'),"'",'&apos;'), 255),
                ClientCustom7 = LEFT(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(ClientCustom7, '&', '&amp;'), '<','&lt;'),'>','&gt;'),'"','&quot;'),"'",'&apos;'), 255),
                ClientCustom8 = LEFT(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(ClientCustom8, '&', '&amp;'), '<','&lt;'),'>','&gt;'),'"','&quot;'),"'",'&apos;'), 255),
                ClientCustom9 = LEFT(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(ClientCustom9, '&', '&amp;'), '<','&lt;'),'>','&gt;'),'"','&quot;'),"'",'&apos;'), 255),
                ClientCustom10= LEFT(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(ClientCustom10,'&', '&amp;'), '<','&lt;'),'>','&gt;'),'"','&quot;'),"'",'&apos;'), 255)
        """
        cursor.execute(xml_update_sql)
        conn.commit()

        # 4) INSERT en clients con la SQL que nos has pasado (adaptada a mig_table)
        print(f"   [{ENTITY_KEY}] Comprobando si hay datos para insertar en clients.")
        count_sql = f"""
            SELECT COUNT(*)
            FROM {mig_table} s
            INNER JOIN x_config_clinics c ON s.ClinicID = c.ClinicID
        """
        cursor.execute(count_sql)
        (rows_to_insert,) = cursor.fetchone()

        if rows_to_insert == 0:
            msg = "No se han encontrado datos para subir a clients."
            print(f"   [{ENTITY_KEY}] {msg}")
            if stop_on_error:
                raise ValueError(msg)
            else:
                return {"status": "no-data", "rows_mig": rows_mig, "rows_clients": 0}

        print(f"   [{ENTITY_KEY}] Se van a insertar {rows_to_insert} clientes en clients.")

        # SET @sImportID
        cursor.execute("SET @sImportID = CAST(DATE_FORMAT(NOW(), '%Y%m%d') AS UNSIGNED)")

        insert_clients_sql = f"""
            INSERT INTO 
              clients 
              (
                ClientEnableRGPD,
                ClientAddress,
                ClientColony,
                ClientPostCode,
                ClientExtra,
                ClientCity,
                ClientStrNum,
                ClientCountry,
                ClientProvince,
                ClientEMail,
                ClientDate,
                ClientBirthDate,
                ClientLocalIE,
                ClientIESSUF,
                ClientName,
                ClientNotes,
                ClientNIF,
                ClientNumber,
                ClientCode,
                ClientEnableGeneralConditions,
                ClientSurname1,
                ClientRG,
                ClientSurname2,
                ClientSex,
                ClientPhone1,
                ClientPhone2,
                ClientPhone3,
                ClientCustom1,
                ClientCustom2,
                ClientCustom3,
                ClientCustom4,
                ClientCustom5,
                ClientCustom6,
                ClientCustom7,
                ClientCustom8,
                ClientCustom9,
                ClientCustom10,
                -- Campos internos
                ClientImportID,
                ClientMigrated,
                ClientClinicID,
                ClientID,
                ClientFWALogin,
                ClientFWAPassword,
                ClientUserID,
                ClientTime,
                ClientZones
              )
            SELECT
                IFNULL(s.ClientEnableRGPD,0),
                IFNULL(s.ClientAddress,""),
                IFNULL(s.ClientColony,""),
                IFNULL(s.ClientPostCode,""),
                IFNULL(s.ClientExtra,""),
                IFNULL(s.ClientCity,""),
                IFNULL(s.ClientStrNum,""),
                IFNULL(s.ClientCountry,""),
                IFNULL(s.ClientProvince,""),
                IFNULL(s.ClientEMail,""),
                IFNULL(s.ClientDate, CURDATE()),
                s.ClientBirthDate,
                IFNULL(s.ClientLocalIE,""),
                IFNULL(s.ClientIESSUF,""),
                IFNULL(s.ClientName,""),
                IFNULL(s.ClientNotes,""),
                IFNULL(s.ClientNIF,""),
                IFNULL(s.ClientNumber,0),
                NULLIF(s.ClientCode,''),              -- clave: '' -> NULL para INT
                IFNULL(s.ClientEnableGeneralConditions,0),
                IFNULL(s.ClientSurname1,""),
                IFNULL(s.ClientRG,""),
                IFNULL(s.ClientSurname2,""),
                IFNULL(s.ClientSex,""),
                IFNULL(REPLACE(REPLACE(REPLACE(s.ClientPhone1, '.', ''), '-', ''), ' ', ''),""),
                IFNULL(REPLACE(REPLACE(REPLACE(s.ClientPhone2, '.', ''), '-', ''), ' ', ''),""),
                IFNULL(REPLACE(REPLACE(REPLACE(s.ClientPhone3, '.', ''), '-', ''), ' ', ''),""),
                IFNULL(s.ClientCustom1,""),
                IFNULL(s.ClientCustom2,""),
                IFNULL(s.ClientCustom3,""),
                IFNULL(s.ClientCustom4,""),
                IFNULL(s.ClientCustom5,""),
                IFNULL(s.ClientCustom6,""),
                IFNULL(s.ClientCustom7,""),
                IFNULL(s.ClientCustom8,""),
                IFNULL(s.ClientCustom9,""),
                IFNULL(s.ClientCustom10,""),
                @sImportID,
                -1,
                IFNULL(s.ClinicID,0),
                IFNULL(s.ClientID,0),
                IFNULL(s.ClientEMail,""),
                HEX(RAND()),
                -2,
                CURTIME(),
                '|'
            FROM 
              {mig_table} s
              INNER JOIN x_config_clinics c ON s.ClinicID = c.ClinicID
        """
        cursor.execute(insert_clients_sql)
        conn.commit()
        rows_clients = cursor.rowcount
        print(f"   [{ENTITY_KEY}] Clientes insertados en clients: {rows_clients}")

        # 5) ACTUALIZACIONES POSTERIORES

        # 5.1 Concatenación de Nombre (SET_NAME_SPLIT = 0)
        print(f"   [{ENTITY_KEY}] Actualizando nombre completo según SET_NAME_SPLIT.")
        update_name_sql = """
            UPDATE 
              clients 
            SET 
              ClientName = CONCAT_WS(' ',
                    IF(ClientName='',NULL,ClientName), 
                    IF(ClientSurname1='',NULL,ClientSurname1),
                    IF(ClientSurname2='',NULL,ClientSurname2)
              ), 
              ClientSurname1 = '', 
              ClientSurname2 = '' 
            WHERE 
              ClientImportID = @sImportID AND 
              (SELECT SettingValue FROM x_config_settings WHERE SettingName = 'SET_NAME_SPLIT') = 0
        """
        cursor.execute(update_name_sql)
        conn.commit()

        # 5.2 Concatenación de Dirección (SET_CLIENT_ADDRESS_SPLIT = 0)
        print(f"   [{ENTITY_KEY}] Actualizando dirección según SET_CLIENT_ADDRESS_SPLIT.")
        update_address_sql = """
            UPDATE 
              clients 
            SET 
              ClientAddress = CONCAT_WS(', ', 
                    IF(ClientAddress='',NULL,ClientAddress), 
                    IF(ClientStrNum='',NULL,ClientStrNum),
                    IF(ClientExtra='',NULL,ClientExtra)
              ), 
              ClientStrNum = '', 
              ClientExtra = '' 
            WHERE 
              ClientImportID = @sImportID AND 
              (SELECT SettingValue FROM x_config_settings WHERE SettingName = 'SET_CLIENT_ADDRESS_SPLIT') = 0
        """
        cursor.execute(update_address_sql)
        conn.commit()

        # 5.3 Actualización de IDs de País
        print(f"   [{ENTITY_KEY}] Actualizando CountryID, ProvinceID y CityID.")
        update_country_sql = """
            UPDATE 
              clients c
              INNER JOIN x_config_countries co ON c.ClientCountry = co.CountryName
            SET 
              c.ClientCountryID = co.CountryID
            WHERE 
              c.ClientImportID = @sImportID AND 
              c.ClientCountry IS NOT NULL AND 
              c.ClientCountry != ''
        """
        cursor.execute(update_country_sql)
        conn.commit()

        # 5.4 Provincia
        update_province_sql = """
            UPDATE 
              clients c
              INNER JOIN x_config_provinces p ON c.ClientProvince = p.ProvinceName
            SET 
              c.ClientProvinceID = p.ProvinceID
            WHERE 
              c.ClientImportID = @sImportID AND 
              c.ClientProvince IS NOT NULL AND 
              c.ClientProvince != ''
        """
        cursor.execute(update_province_sql)
        conn.commit()

        # 5.5 Ciudad
        update_city_sql = """
            UPDATE 
              clients c
              INNER JOIN x_config_cities ci ON c.ClientCity = ci.CityName
            SET 
              c.ClientCityID = ci.CityID
            WHERE 
              c.ClientImportID = @sImportID AND 
              c.ClientCity IS NOT NULL AND 
              c.ClientCity != ''
        """
        cursor.execute(update_city_sql)
        conn.commit()

        # 5.6 Creación de nuevos referers
        print(f"   [{ENTITY_KEY}] Creando referers nuevos en x_config_referers.")
        insert_referers_sql = f"""
            INSERT INTO 
              x_config_referers 
              (
                RefererDesc, 
                RefererClinicID
              )
            SELECT 
              DISTINCT c.RefererDesc, 
              c.ClinicID
            FROM 
              {mig_table} c
            WHERE 
              c.RefererDesc IS NOT NULL AND 
              c.RefererDesc != '' AND 
              NOT EXISTS (
                  SELECT 
                    1 
                  FROM 
                    x_config_referers r 
                  WHERE 
                    r.RefererDesc = c.RefererDesc AND 
                    r.RefererClinicID = c.ClinicID
              )
        """
        cursor.execute(insert_referers_sql)
        conn.commit()

        # 5.7 Actualizar ClientRefererID
        print(f"   [{ENTITY_KEY}] Actualizando ClientRefererID en clients.")
        update_referer_id_sql = f"""
            UPDATE 
              clients c
              INNER JOIN {mig_table} mc ON mc.ClientID = c.ClientID
              INNER JOIN x_config_referers r 
                    ON mc.RefererDesc = r.RefererDesc 
                   AND mc.ClinicID   = r.RefererClinicID	
            SET 
              c.ClientRefererID = r.RefererID
            WHERE 
              c.ClientImportID = @sImportID AND 
              mc.RefererDesc IS NOT NULL AND 
              mc.RefererDesc != ''
        """
        cursor.execute(update_referer_id_sql)
        conn.commit()

        return {
            "status": "ok",
            "rows_mig": rows_mig,
            "rows_clients": rows_clients,
        }

    except Exception as e:
        print(f"❌ Error en loader {ENTITY_KEY}: {e}")
        if stop_on_error:
            raise
        return {"status": "error", "error": str(e)}

    finally:
        conn.close()
