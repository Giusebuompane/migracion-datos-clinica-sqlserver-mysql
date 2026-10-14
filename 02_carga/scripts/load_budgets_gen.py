import csv
import io
from pathlib import Path
from datetime import datetime
from decimal import Decimal, InvalidOperation

from step02_db import get_connection

ENTITY_KEY = "budgets_gen"


# =========================================
# Helpers básicos
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
    Reemplaza caracteres conflictivos para XML (&, <, >, ", ').
    Lo usamos primero a nivel Python y además lanzaremos un UPDATE en MySQL.
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
      - dd/mm/yyyy HH:MM:SS
      - yyyy-mm-dd HH:MM:SS
    """
    v = clean_token(val)
    if v is None:
        return None

    formats = [
        "%d/%m/%Y",
        "%Y-%m-%d",
        "%d/%m/%Y %H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
    ]
    for fmt in formats:
        try:
            dt = datetime.strptime(v, fmt)
            return dt.date()
        except ValueError:
            continue
    return None


# =========================================
# Carga CSV → __mig_budgets_gen
# =========================================
def load_csv_into_mig(cursor, entity_config: dict, context: dict) -> int:
    """
    Carga el CSV de budgets_gen en la tabla __mig_budgets_gen.
    Aplica:
      - detección de separador (coma / punto y coma)
      - manejo de BOM en cabeceras
      - conversión de fechas
      - conversión de NULL / números
      - limpieza básica de textos
      - soporte opcional de columnas dentales
    Devuelve el número de filas insertadas.
    """
    mig_table = entity_config.get("mig_table", "__mig_budgets_gen")
    input_file = entity_config.get("input_file", "budgets_gen.csv")
    input_folder = Path(context.get("input_folder", Path(".")))
    csv_path = input_folder / input_file

    is_dental = bool(context.get("is_dental", False))

    if not csv_path.exists():
        raise FileNotFoundError(f"No se encontró el fichero de entrada: {csv_path}")

    print(f"   [{ENTITY_KEY}] Fichero de entrada: {csv_path}")

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
    if reader.fieldnames and reader.fieldnames[0].startswith("ï»¿"):
        reader.fieldnames[0] = reader.fieldnames[0].replace("ï»¿", "")

    fieldnames = reader.fieldnames or []
    fieldnames = [fn.strip() if fn else fn for fn in fieldnames]

     # Campos requeridos mínimos para poder generar budgets_gen y budgets_det
    # Permitimos que el producto venga como BudgetProductID O como BudgetZoneID
    has_budget_product_col = ("BudgetProductID" in fieldnames) or ("BudgetZoneID" in fieldnames)

    required_min = [
        "BudgetGID",
        "BudgetID",
        "BudgetGClinicID",
        "BudgetGClientID",
        "BudgetGUserID",
        "BudgetGDate",
        # Ojo: BudgetProductID / BudgetZoneID se controla aparte
        "BudgetUnits",
        "BudgetPrice",
        "BudgetDiscountAmount",
        "BudgetVAT",
        "BudgetGStatus",
    ]

    missing_required = [c for c in required_min if c not in fieldnames]

    # Si no tenemos ni BudgetProductID ni BudgetZoneID, lo consideramos como falta de BudgetProductID
    if not has_budget_product_col:
        missing_required.append("BudgetProductID (o BudgetZoneID)")

    if missing_required:
        msg = (
            "Las columnas del CSV no cumplen los mínimos requeridos.\n"
            f"   Encontradas: {fieldnames}\n"
            f"   Requeridas al menos: {required_min} + BudgetProductID/BudgetZoneID\n"
            f"   Faltan: {missing_required}"
        )
        raise ValueError(msg)

    # Columnas dentales opcionales (si faltan y is_dental=True, forzamos 0 / vacío)
    dental_cols = [
        "DentalID",
        "DentalPathologyID",
        "DentalPieceStart",
        "DentalPieceEnd",
        "DentalSurfaces",
        "DentalNotes",
        "DentalMigratedDiary",
        "DentalMigratedTicket",
    ]

    inserted = 0

    insert_sql = f"""
        INSERT INTO {mig_table} (
            BudgetGID,
            BudgetID,
            BudgetGClientID,
            BudgetGClinicID,
            BudgetGUserID,
            BudgetGNumber,
            BudgetGDate,
            BudgetGExpireDate,
            BudgetGNotes,
            BudgetGStatus,
            BudgetUserID,
            BudgetDoctorID,
            BudgetProductID,
            BudgetUnits,
            BudgetPrice,
            BudgetDiscountAmount,
            BudgetVAT,
            BudgetComments,
            DentalID,
            DentalPathologyID,
            DentalPieceStart,
            DentalPieceEnd,
            DentalSurfaces,
            DentalNotes,
            DentalMigratedDiary,
            DentalMigratedTicket
        )
        VALUES (
            %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
            %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
            %s,%s,%s,%s,%s,%s
        )
    """

    # =========================================================
    # OPTIMIZACIÓN: INSERT por lotes (executemany)
    # =========================================================
    batch_size = int(context.get("csv_batch_size", 1000))
    batch = []

    for row in reader:
        # Core
        BudgetGID = parse_int(row.get("BudgetGID"), 0)
        BudgetID = parse_int(row.get("BudgetID"), 0)
        BudgetGClientID = parse_int(row.get("BudgetGClientID"))
        BudgetGClinicID = parse_int(row.get("BudgetGClinicID"))
        BudgetGUserID = parse_int(row.get("BudgetGUserID"))
        BudgetGNumber = parse_int(row.get("BudgetGNumber"))  # se recalcula luego, pero por si viene algo

        BudgetGDate = parse_date(row.get("BudgetGDate"))
        BudgetGExpireDate = parse_date(row.get("BudgetGExpireDate"))

        BudgetGNotes = normalize_latin1(clean_xml_text(row.get("BudgetGNotes")))
        BudgetGStatus = parse_int(row.get("BudgetGStatus"), 0)

        BudgetUserID = parse_int(row.get("BudgetUserID"))
        BudgetDoctorID = parse_int(row.get("BudgetDoctorID"))

        # El producto puede venir como BudgetProductID o como BudgetZoneID en el CSV
        raw_budget_product = row.get("BudgetProductID")
        if raw_budget_product is None:
            raw_budget_product = row.get("BudgetZoneID")
        BudgetProductID = parse_int(raw_budget_product)
        BudgetUnits = parse_int(row.get("BudgetUnits"), 0)
        BudgetPrice = parse_decimal(row.get("BudgetPrice"), Decimal("0"))
        BudgetDiscountAmount = parse_decimal(row.get("BudgetDiscountAmount"), Decimal("0"))
        BudgetVAT = parse_decimal(row.get("BudgetVAT"), Decimal("0"))

        BudgetComments = normalize_latin1(clean_xml_text(row.get("BudgetComments")))

        # Dentales (opcionales)
        if "DentalID" in fieldnames:
            DentalID = parse_int(row.get("DentalID"), 0)
        else:
            # si no hay columna y la tabla no permite NULL, metemos 0
            DentalID = 0

        DentalPathologyID = parse_int(row.get("DentalPathologyID"))
        DentalPieceStart = parse_int(row.get("DentalPieceStart"))
        DentalPieceEnd = parse_int(row.get("DentalPieceEnd"))
        DentalSurfaces = parse_int(row.get("DentalSurfaces"))
        DentalNotes = normalize_latin1(clean_xml_text(row.get("DentalNotes")))

        DentalMigratedDiary = parse_int(row.get("DentalMigratedDiary"))
        DentalMigratedTicket = parse_int(row.get("DentalMigratedTicket"))

        # Si is_dental=False y no hay info dental, normalizamos todo a 0 / None
        if not is_dental:
            DentalID = 0 if DentalID is None else DentalID
            DentalPathologyID = None
            DentalPieceStart = None
            DentalPieceEnd = None
            DentalSurfaces = None
            DentalNotes = None
            DentalMigratedDiary = None
            DentalMigratedTicket = None
        else:
            # Si is_dental=True pero faltan columnas en el CSV, aseguramos defaults válidos
            if "DentalID" not in fieldnames:
                DentalID = 0
            DentalPathologyID = DentalPathologyID or 0
            DentalSurfaces = DentalSurfaces or 0

        data = (
            BudgetGID,
            BudgetID,
            BudgetGClientID,
            BudgetGClinicID,
            BudgetGUserID,
            BudgetGNumber,
            BudgetGDate,
            BudgetGExpireDate,
            BudgetGNotes,
            BudgetGStatus,
            BudgetUserID,
            BudgetDoctorID,
            BudgetProductID,
            BudgetUnits,
            BudgetPrice,
            BudgetDiscountAmount,
            BudgetVAT,
            BudgetComments,
            DentalID,
            DentalPathologyID,
            DentalPieceStart,
            DentalPieceEnd,
            DentalSurfaces,
            DentalNotes,
            DentalMigratedDiary,
            DentalMigratedTicket,
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
        batch.clear()

    print(f"   [{ENTITY_KEY}] Filas insertadas en __mig_budgets_gen: {inserted}")
    return inserted


# =========================================
# RUN principal
# =========================================
def run(entity_config: dict, context: dict):
    """
    Proceso de migración para 'budgets_gen':
      1) DROP + CREATE de __mig_budgets_gen
      2) Carga CSV en __mig_budgets_gen
      3) Limpieza XML en notas
      4) Reasignación de BudgetGNumber y actualización de ClinicBudgetCounter
      5) Inserción en budgets_gen (previo SELECT de comprobación)
      6) (Opcional) Update BudgetGClassID / BudgetGTitle si is_dental=True
      7) Inserción en budgets_det (previo SELECT de comprobación)
      8) (Opcional) Inserción en budgets_det_dental si is_dental=True
    """
    mig_table = entity_config.get("mig_table", "__mig_budgets_gen")
    stop_on_error = bool(context.get("stop_on_error", True))
    is_dental = bool(context.get("is_dental", False))

    clinic_ids = context.get("clinic_ids") or [1]
    clinic_id = clinic_ids[0]

    conn = get_connection()
    cursor = conn.cursor()

    try:
        # 1) DROP + CREATE tabla de migración
        print(f"   [{ENTITY_KEY}] Recreando tabla {mig_table}...")
        cursor.execute(f"DROP TABLE IF EXISTS {mig_table}")
        create_sql = f"""
            CREATE TABLE `{mig_table}` (
                `BudgetGID` INT(11) NOT NULL,
                `BudgetID` INT(11) NOT NULL,
                `BudgetGClientID` INT(11) NULL DEFAULT NULL,
                `BudgetGClinicID` INT(11) NULL DEFAULT NULL,
                `BudgetGUserID` INT(11) NULL DEFAULT NULL,
                `BudgetGNumber` INT(11) NULL DEFAULT NULL,
                `BudgetGDate` DATE NULL DEFAULT NULL,
                `BudgetGExpireDate` DATE NULL DEFAULT NULL,
                `BudgetGNotes` TEXT NULL DEFAULT NULL COLLATE 'latin1_spanish_ci',
                `BudgetGStatus` INT(11) NULL DEFAULT '0',
                `BudgetUserID` INT(1) NULL DEFAULT NULL,
                `BudgetDoctorID` INT(1) NULL DEFAULT NULL,
                `BudgetProductID` INT(11) NULL DEFAULT NULL,
                `BudgetUnits` INT(11) NULL DEFAULT NULL,
                `BudgetPrice` DECIMAL(14,4) NULL DEFAULT NULL,
                `BudgetDiscountAmount` DECIMAL(16,10) NULL DEFAULT NULL,
                `BudgetVAT` DECIMAL(6,6) NULL DEFAULT NULL,
                `BudgetComments` TEXT NULL DEFAULT NULL COLLATE 'latin1_spanish_ci',
                `DentalID` INT(1) NOT NULL,
                `DentalPathologyID` INT(1) NULL DEFAULT NULL,
                `DentalPieceStart` TINYINT(1) NULL DEFAULT NULL,
                `DentalPieceEnd` TINYINT(1) NULL DEFAULT NULL,
                `DentalSurfaces` TINYINT(1) NULL DEFAULT NULL,
                `DentalNotes` TEXT NULL DEFAULT NULL COLLATE 'latin1_spanish_ci',
                `DentalMigratedDiary` TINYINT(1) NULL DEFAULT NULL,
                `DentalMigratedTicket` TINYINT(1) NULL DEFAULT NULL,
                PRIMARY KEY (`DentalID`, `BudgetGID`, `BudgetID`) USING BTREE
            )
            COLLATE='latin1_spanish_ci'
            ENGINE=MyISAM
        """
        cursor.execute(create_sql)
        conn.commit()

        # 2) Carga CSV en MIG
        inserted_mig = load_csv_into_mig(cursor, entity_config, context)
        conn.commit()

        if inserted_mig == 0:
            print(f"   [{ENTITY_KEY}] No se han insertado filas en {mig_table}.")
            if stop_on_error:
                raise ValueError("No hay datos en la tabla de migración de presupuestos.")
            else:
                return

        # 3) Limpieza XML en textos de la tabla MIG
        print(f"   [{ENTITY_KEY}] Limpiando caracteres XML en notas...")
        xml_update_sql = f"""
            UPDATE {mig_table}
            SET
                BudgetGNotes = REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(BudgetGNotes, '&', '&amp;'), '<','&lt;'),'>','&gt;'),'"','&quot;'),"'",'&apos;'),
                BudgetComments = REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(BudgetComments, '&', '&amp;'), '<','&lt;'),'>','&gt;'),'"','&quot;'),"'",'&apos;'),
                DentalNotes = REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(DentalNotes, '&', '&amp;'), '<','&lt;'),'>','&gt;'),'"','&quot;'),"'",'&apos;')
        """
        cursor.execute(xml_update_sql)
        conn.commit()

        # 4) Reasignación de BudgetGNumber + actualización del contador de clínica
        print(f"   [{ENTITY_KEY}] Reasignando BudgetGNumber y actualizando ClinicBudgetCounter...")
        cursor.execute(f"SET @ClinicID = {clinic_id}")
        cursor.execute("""
            SET @NumberID = (
                SELECT x_config_clinics.ClinicBudgetCounter
                FROM x_config_clinics
                WHERE ClinicID = @ClinicID
            )
        """)
        cursor.execute(f"""
            UPDATE {mig_table}
            SET BudgetGNumber = @NumberID := @NumberID + 1
        """)
        cursor.execute("""
            UPDATE x_config_clinics
            SET ClinicBudgetCounter = @NumberID + 1
            WHERE ClinicID = @ClinicID
        """)
        conn.commit()

        # 5) Inserción en budgets_gen (con SELECT previo de comprobación)
        print(f"   [{ENTITY_KEY}] Comprobando si hay presupuestos para insertar en budgets_gen...")
        count_gen_sql = f"""
            SELECT COUNT(*)
            FROM (
                SELECT
                    {mig_table}.BudgetGID
                FROM
                    __mig_budgets_gen
                    INNER JOIN __mapping_products ON id=BudgetProductID
                    LEFT JOIN __mapping_users mp1 ON __mig_budgets_gen.BudgetGUserID=mp1.id
                    LEFT JOIN __mapping_users mp2 ON __mig_budgets_gen.BudgetDoctorID=mp2.id
                    LEFT JOIN x_config_users xc1 ON xc1.UserID=mp1.idFlowww
                    LEFT JOIN x_config_users xc2 ON xc2.UserID=mp2.idFlowww
                WHERE
                    {mig_table}.BudgetGClinicID = @ClinicID
                GROUP BY
                    {mig_table}.BudgetGID
            ) AS t
        """
        cursor.execute(count_gen_sql)
        (rows_to_insert_gen,) = cursor.fetchone()

        if rows_to_insert_gen == 0:
            msg = "No se han encontrado datos para subir a budgets_gen."
            print(f"   [{ENTITY_KEY}] {msg}")
            if stop_on_error:
                raise ValueError(msg)
        else:
            print(f"   [{ENTITY_KEY}] Se van a insertar {rows_to_insert_gen} presupuestos en budgets_gen...")

            insert_gen_sql = f"""
                INSERT INTO
                    budgets_gen
                    (
                        __MigBudgetGID,
                        BudgetGClientID,
                        BudgetGClinicID,
                        BudgetGUserID,
                        BudgetGDoctorID,
                        BudgetGNumber,
                        BudgetGYear,
                        BudgetGDate,
                        BudgetGNotes,
                        BudgetGStatus,
                        BudgetGStatusDate,
                        BudgetGStamp
                    )
                SELECT
                    {mig_table}.BudgetGID,
                    {mig_table}.BudgetGClientID,
                    {mig_table}.BudgetGClinicID,
                    IFNULL(xc1.UserID,0),
                    IFNULL(xc2.UserID,0),
                    {mig_table}.BudgetGNumber,
                    YEAR({mig_table}.BudgetGDate),
                    {mig_table}.BudgetGDate,
                    {mig_table}.BudgetGNotes,
                    {mig_table}.BudgetGStatus,
                    {mig_table}.BudgetGDate,
                    CAST(CONCAT(CURDATE(), ' 00:00:00') AS DATETIME)
                FROM
                    __mig_budgets_gen
                    INNER JOIN __mapping_products ON id=BudgetProductID
                    LEFT JOIN __mapping_users mp1 ON __mig_budgets_gen.BudgetGUserID=mp1.id
                    LEFT JOIN __mapping_users mp2 ON __mig_budgets_gen.BudgetDoctorID=mp2.id
                    LEFT JOIN x_config_users xc1 ON xc1.UserID=mp1.idFlowww
                    LEFT JOIN x_config_users xc2 ON xc2.UserID=mp2.idFlowww
                WHERE
                    {mig_table}.BudgetGClinicID = @ClinicID
                GROUP BY
                    {mig_table}.BudgetGID
            """
            cursor.execute(insert_gen_sql)
            conn.commit()
            print(f"   [{ENTITY_KEY}] Presupuestos insertados en budgets_gen: {cursor.rowcount}")

        # 6) (Opcional) si is_dental=True → actualizar clase y título
        if is_dental:
            print(f"   [{ENTITY_KEY}] is_dental=True → actualizando BudgetGClassID y BudgetGTitle...")
            update_dental_header_sql = f"""
                UPDATE
                    budgets_gen
                    INNER JOIN {mig_table}
                        ON budgets_gen.__MigBudgetGID = {mig_table}.BudgetGID
                SET
                    budgets_gen.BudgetGClassID = 'DENTAL',
                    budgets_gen.BudgetGTitle  = 'Presupuesto migrado'
            """
            cursor.execute(update_dental_header_sql)
            conn.commit()
        else:
            print(f"   [{ENTITY_KEY}] is_dental=False → no se modifican BudgetGClassID/BudgetGTitle.")

        # 7) Inserción en budgets_det
        print(f"   [{ENTITY_KEY}] Comprobando si hay líneas de detalle para insertar en budgets_det...")
        count_det_sql = f"""
            SELECT COUNT(*)
            FROM (
                SELECT
                    {mig_table}.BudgetID
                FROM
                    {mig_table}
                    LEFT JOIN budgets_gen 
                        ON budgets_gen.__MigBudgetGID = {mig_table}.BudgetGID
                    LEFT JOIN __mapping_products 
                        ON __mapping_products.id = {mig_table}.BudgetProductID
                    LEFT JOIN x_config_products_gen 
                        ON x_config_products_gen.ProductGClinicID = {mig_table}.BudgetGClinicID
                    LEFT JOIN x_config_products_det 
                        ON x_config_products_det.ProductSourceID = __mapping_products.idFlowww
                        AND x_config_products_gen.ProductGID = x_config_products_det.ProductGID
                WHERE
                    {mig_table}.BudgetGClinicID = @ClinicID
                    AND ProductType IN (2,7,5,8,9,10,11,12)
            ) AS t
        """
        cursor.execute(count_det_sql)
        (rows_to_insert_det,) = cursor.fetchone()

        if rows_to_insert_det == 0:
            msg = "No se han encontrado datos para subir a budgets_det."
            print(f"   [{ENTITY_KEY}] {msg}")
            if stop_on_error:
                raise ValueError(msg)
        else:
            print(f"   [{ENTITY_KEY}] Se van a insertar {rows_to_insert_det} líneas en budgets_det...")

            insert_det_sql = f"""
                INSERT INTO
                    budgets_det
                    (
                        BudgetGID,
                        BudgetProductID,
                        BudgetUnits,
                        BudgetPrice,
                        BudgetDiscount,
                        BudgetVAT,
                        BudgetComments,
                        -- BudgetMigratedDiary,
                        -- BudgetMigratedTicket,
                        __MigBudgetGID,
                        __MigBudgetID
                    )
                SELECT
                    budgets_gen.BudgetGID,
                    x_config_products_det.ProductID,
                    {mig_table}.BudgetUnits,
                    ROUND({mig_table}.BudgetPrice, 4),
                    ifnull({mig_table}.BudgetDiscountAmount,0),
                    {mig_table}.BudgetVAT,
                    {mig_table}.BudgetComments,
                    -- IFNULL(IF(x_config_products_det.ProductDentalPicID=0,__mig_budgets_gen.DentalMigratedDiary,0),0),
                   --  IFNULL(IF(x_config_products_det.ProductDentalPicID=0,__mig_budgets_gen.DentalMigratedTicket,0),0),
                    {mig_table}.BudgetGID,
                    {mig_table}.BudgetID
                FROM
                    {mig_table}
                    LEFT JOIN budgets_gen 
                        ON budgets_gen.__MigBudgetGID = {mig_table}.BudgetGID
                    LEFT JOIN __mapping_products 
                        ON __mapping_products.id = {mig_table}.BudgetProductID
                    LEFT JOIN x_config_products_gen 
                        ON x_config_products_gen.ProductGClinicID = {mig_table}.BudgetGClinicID
                    LEFT JOIN x_config_products_det 
                        ON x_config_products_det.ProductSourceID = __mapping_products.idFlowww
                        AND x_config_products_gen.ProductGID = x_config_products_det.ProductGID
                WHERE
                    {mig_table}.BudgetGClinicID = @ClinicID
                    AND ProductType IN (2,7,5,8,9,10,11,12)
                GROUP BY
                    {mig_table}.BudgetID
            """
            cursor.execute(insert_det_sql)
            conn.commit()
            print(f"   [{ENTITY_KEY}] Líneas insertadas en budgets_det: {cursor.rowcount}")

        # 8) (Opcional) Inserción en budgets_det_dental
        if is_dental:
            print(f"   [{ENTITY_KEY}] Comprobando si hay registros dentales para insertar en budgets_det_dental...")
            count_dental_sql = f"""
                SELECT COUNT(*)
                FROM (
                    SELECT
                        {mig_table}.DentalID
                    FROM
                        {mig_table}
                        INNER JOIN budgets_det 
                            ON budgets_det.__MigBudgetID = {mig_table}.BudgetID
                    WHERE
                        {mig_table}.DentalID IS NOT NULL
                ) AS t
            """
            cursor.execute(count_dental_sql)
            (rows_to_insert_dental,) = cursor.fetchone()

            if rows_to_insert_dental == 0:
                print(f"   [{ENTITY_KEY}] No se han encontrado datos para subir a budgets_det_dental.")
            else:
                print(f"   [{ENTITY_KEY}] Se van a insertar {rows_to_insert_dental} líneas dentales en budgets_det_dental...")

                insert_dental_sql = f"""
                    INSERT INTO 
                        budgets_det_dental
                        (
                            DentalBudgetID,
                            DentalProductID,
                            DentalPathologyID,
                            DentalPieceStart,
                            DentalPieceEnd,
                            DentalSurfaces,
                            DentalNotes,
                            DentalMigratedDiary,
                            DentalMigratedTicket,
                            __MigDentalID
                        )
                    SELECT
                        budgets_det.BudgetID,
                        budgets_det.BudgetProductID,
                        IFNULL({mig_table}.DentalPathologyID, 0),
                        {mig_table}.DentalPieceStart,
                        {mig_table}.DentalPieceEnd,
                        IFNULL({mig_table}.DentalSurfaces, 0),
                        {mig_table}.DentalNotes,
                        IFNULL(IF(x_config_products_det.ProductDentalPicID=0,__mig_budgets_gen.DentalMigratedDiary,0),0),
                        IFNULL(IF(x_config_products_det.ProductDentalPicID=0,__mig_budgets_gen.DentalMigratedTicket,0),0),
                        {mig_table}.DentalID
                    FROM
                        __mig_budgets_gen
                        INNER JOIN budgets_det ON budgets_det.__MigBudgetID=__mig_budgets_gen.BudgetID
                        LEFT JOIN __mapping_products ON id=__mig_budgets_gen.BudgetProductID
                        LEFT JOIN x_config_products_gen ON x_config_products_gen.ProductGClinicID=__mig_budgets_gen.BudgetGClinicID
                        LEFT JOIN x_config_products_det ON x_config_products_det.ProductSourceID=idFlowww AND x_config_products_gen.ProductGID=x_config_products_det.ProductGID
                    WHERE 
                        DentalPieceStart<>0
                    GROUP BY
                        {mig_table}.DentalID
                """
                cursor.execute(insert_dental_sql)
                conn.commit()
                print(f"   [{ENTITY_KEY}] Líneas dentales insertadas en budgets_det_dental: {cursor.rowcount}")
        else:
            print(f"   [{ENTITY_KEY}] is_dental=False → se omite la inserción en budgets_det_dental.")

    finally:
        cursor.close()
        conn.close()
