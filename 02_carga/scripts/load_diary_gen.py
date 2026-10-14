# load_diary_gen.py

import csv
from pathlib import Path
from datetime import datetime, timedelta

from step02_db import get_connection

def clean_int_value(value, default=None):
    """
    Normaliza un valor "numérico" que puede venir como:
      - '123'
      - ''
      - 'NULL', 'null', 'None', 'NULO'
      - None

    Devuelve:
      - int(valor) si es un número válido
      - default si está vacío o es un 'NULL' simbólico
    """
    if value is None:
        return default

    v = str(value).strip()
    if v == "":
        return default

    upper = v.upper()
    if upper in ("NULL", "NONE", "NULO"):
        return default

    try:
        return int(v)
    except ValueError:
        return default
        
def normalize_latin1(text: str | None) -> str | None:
    """
    Normaliza una cadena a latin1, reemplazando caracteres no representables.
    Evita errores de codificación con el conector MySQL.
    """
    if text is None:
        return None
    if not isinstance(text, str):
        text = str(text)
    return text.encode("latin1", errors="replace").decode("latin1")


def parse_date(value: str | None):
    """
    Convierte fecha/fechahora a date.
    Soporta: dd/mm/yyyy, yyyy-mm-dd, dd-mm-yyyy y variantes con hora.
    """
    if not value:
        return None
    value = value.strip()
    # Si viene con hora, nos quedamos solo con la parte de fecha
    if " " in value:
        value = value.split(" ")[0]

    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue

    try:
        return datetime.fromisoformat(value).date()
    except ValueError:
        return None


def parse_time(value: str | None):
    """
    Convierte cadena a time.
    Soporta: HH:MM:SS, H:MM:SS, HH:MM.
    """
    if not value:
        return None
    value = value.strip()
    # Si viene con fecha delante, nos quedamos solo con la parte de hora
    if " " in value:
        value = value.split(" ")[-1]

    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            return datetime.strptime(value, fmt).time()
        except ValueError:
            continue

    return None


def parse_time(value: str | None):
    """
    Convierte hora/fechahora a time.
    Acepta:
      - HH:MM
      - HH:MM:SS
      - YYYY-MM-DD HH:MM[:SS[.mmm]]
    """
    if not value:
        return None
    value = value.strip()

    candidate = value
    if " " in value:
        # Si viene con fecha delante, nos quedamos con el último trozo
        candidate = value.split()[-1]

    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            return datetime.strptime(candidate, fmt).time()
        except ValueError:
            continue

    try:
        dt = datetime.fromisoformat(value)
        return dt.time()
    except ValueError:
        return None


def parse_datetime(value: str | None):
    """
    Convierte cadena a datetime (fecha + hora).
    """
    if not value:
        return None
    value = value.strip()

    formats = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M:%S.%f",
        "%d/%m/%Y %H:%M:%S",
        "%d/%m/%Y %H:%M",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f",
    ]

    for fmt in formats:
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue

    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None

def resolve_diary_overlaps(cursor, conn, context: dict):
    """
    Ajusta solapamientos de citas en diary_gen moviéndolas de cabina
    según la lógica de diary_gen_overlaps.

    - Inicializa DiaryGCabinetNum:
        1) Pone todas a 1
        2) Ajusta según ProductCabinets cuando haya configuración
    - Bucle:
        - Busca grupos de citas solapadas por clínica, cabina y día
        - Para cada iteración:
            - Setea @DiaryGIDToMove con los ids a mover
            - Setea @CabinetNum
            - Actualiza DiaryGCabinetNum según default_product_cabin
        - Incrementa @CabinetNum y rota si se pasa de nº de cabinas
        - Sale cuando no hay más grupos de solapados
    """

    stop_on_error = bool(context.get("stop_on_error", True))
    default_product_cabin = bool(context.get("default_product_cabin", True))

    # 1) Inicializar cabinas
    try:
        print("   [diary_gen_overlaps] Inicializando cabinas...")

        # Todas las citas a cabina 1
        cursor.execute("UPDATE diary_gen SET DiaryGCabinetNum = 1;")
        conn.commit()

        # Según ProductCabinets (primer valor)
        init_cabinets_sql = """
        UPDATE
            diary_gen dg
            INNER JOIN
            (
                SELECT
                    REPLACE(
                        SUBSTRING_INDEX(pd.ProductCabinets,'|',2),
                        CONCAT(SUBSTRING_INDEX(pd.ProductCabinets,'|',1),'|'),
                        ''
                    ) AS CabinetNum,
                    dg.DiaryGID
                FROM
                    diary_gen dg
                    INNER JOIN diary_det dt ON dt.DiaryGID = dg.DiaryGID
                    INNER JOIN x_config_products_det pd ON pd.ProductID = dt.DiaryZoneID
                WHERE
                    pd.ProductCabinets LIKE '|%'
                    AND dg.DiaryGLocked = 0
            ) dc ON dc.DiaryGID = dg.DiaryGID
        SET
            dg.DiaryGCabinetNum = dc.CabinetNum;
        """
        cursor.execute(init_cabinets_sql)
        conn.commit()

    except Exception as e:
        print("   ❌ Error inicializando cabinas (diary_gen_overlaps):", e)
        if stop_on_error:
            raise
        return

    # 2) Parámetros de fechas y clínicas
    today = datetime.today().date()
    date_start = today - timedelta(days=365)        # 1 año antes
    date_end = today + timedelta(days=3 * 365)      # 3 años después

    clinic_ids = context.get("clinic_ids", [1])
    clinic_ids_str = ",".join(str(c) for c in clinic_ids)

    # Nº máximo de cabinas
    cursor.execute("SELECT COALESCE(COUNT(*), 0) FROM x_config_clinics_cab;")
    row = cursor.fetchone()
    max_cabinets = row[0] if row and row[0] > 0 else 1

    cabinet_num = 1
    total_iterations = 0
    total_groups_moved = 0
    max_iterations = 50  # cortafuegos anti bucles infinitos

    print(f"   [diary_gen_overlaps] Empezando resolución de solapamientos "
          f"(clinics={clinic_ids_str}, rango={date_start}..{date_end}, max_cabinas={max_cabinets})")

    while True:
        total_iterations += 1
        if total_iterations > max_iterations:
            print("   ⚠ Se ha alcanzado el nº máximo de iteraciones en diary_gen_overlaps. Se detiene el proceso.")
            break

        # Set de variables de rango y clínicas
        cursor.execute("SET @DateStart = %s;", (date_start.strftime("%Y-%m-%d"),))
        cursor.execute("SET @DateEnd   = %s;", (date_end.strftime("%Y-%m-%d"),))
        cursor.execute("SET @ClinicIDs = %s;", (clinic_ids_str,))

        # Query para obtener los ids de las citas solapadas (grupo)
        overlaps_sql = """
        SELECT GROUP_CONCAT(DiaryGToMove) AS DiaryGToMoveList FROM (
            SELECT
                SUBSTRING_INDEX(mult.DiaryIDs,',',1) AS DiaryGToMove,
                mult.DiaryGID AS DiaryGIDPivot,
                mult.DiaryGMultClinicID,
                mult.DiaryGDate,
                mult.DiaryIDs,
                mult.DiaryGStartMin AS DiaryGMultTimeStart,
                mult.DiaryGEndMax AS DiaryGMultTimeEnd,
                mult.DiaryGMultCabinetID
            FROM
            (
                SELECT
                    dg.DiaryGID,
                    dg.DiaryGClinicID AS DiaryGMultClinicID,
                    dg.DiaryGDate AS DiaryGDate,
                    dg.DiaryGCabinetNum AS DiaryGMultCabinetID,
                    dg.DiaryGUserID AS DiaryGMultUserID,
                    (
                        SELECT
                            CONCAT(
                                @DiaryIDs := GROUP_CONCAT(d.DiaryGID),
                                @DiaryGStartMin := MIN(d.DiaryGStart),
                                @DiaryGEndMax := MAX(d.DiaryGEnd)
                            )
                        FROM
                            diary_gen d
                        WHERE
                            d.DiaryGClinicID = dg.DiaryGClinicID
                            AND d.DiaryGCabinetNum = dg.DiaryGCabinetNum
                            AND d.DiaryGDate = dg.DiaryGDate
                            AND (
                                (d.DiaryGStart > dg.DiaryGStart AND d.DiaryGStart < dg.DiaryGEnd)
                                OR (d.DiaryGEnd > dg.DiaryGStart AND d.DiaryGEnd < dg.DiaryGEnd)
                                OR d.DiaryGStart = dg.DiaryGStart
                                OR d.DiaryGEnd = dg.DiaryGEnd
                                OR (
                                    (dg.DiaryGStart > d.DiaryGStart AND dg.DiaryGStart < d.DiaryGEnd)
                                    OR (dg.DiaryGEnd > d.DiaryGStart AND dg.DiaryGEnd < d.DiaryGEnd)
                                )
                            )
                            AND d.DiaryGDelayed = 0
                            AND d.DiaryGLaserGID = 0
                            AND d.DiaryGNotAttended = 0
                            AND dg.DiaryGMultID = 0
                            AND dg.DiaryGInvisible = 0
                        ORDER BY
                            d.DiaryGID ASC
                    ) AS DiaryGIDTimeCoexit,
                    IF(@DiaryIDs = CAST(dg.DiaryGID AS CHAR), NULL, @DiaryIDs) AS DiaryIDs,
                    IF(@DiaryIDs = CAST(dg.DiaryGID AS CHAR), NULL, @DiaryGStartMin) AS DiaryGStartMin,
                    IF(@DiaryIDs = CAST(dg.DiaryGID AS CHAR), NULL, @DiaryGEndMax) AS DiaryGEndMax
                FROM
                    diary_gen dg
                WHERE
                    dg.DiaryGDate BETWEEN @DateStart AND @DateEnd
                    AND FIND_IN_SET(dg.DiaryGClinicID, @ClinicIDs) > 0
                    AND dg.DiaryGDelayed = 0
                    AND dg.DiaryGLaserGID = 0
                    AND dg.DiaryGNotAttended = 0
                    AND dg.DiaryGMultID = 0
                    AND dg.DiaryGInvisible = 0
                    AND dg.DiaryGLocked = 0
            ) mult
            WHERE
                NOT ISNULL(mult.DiaryIDs)
            GROUP BY
                mult.DiaryGMultClinicID,
                mult.DiaryGDate,
                mult.DiaryIDs,
                mult.DiaryGStartMin,
                mult.DiaryGEndMax,
                mult.DiaryGMultCabinetID
            ORDER BY
                mult.DiaryGDate ASC
        ) tmp;
        """
        cursor.execute(overlaps_sql)
        row = cursor.fetchone()
        ids_concat = row[0] if row else None

        if not ids_concat:
            print(f"   [diary_gen_overlaps] Sin más solapamientos tras {total_iterations - 1} iteraciones.")
            break

        # Tenemos al menos un grupo de citas a mover
        total_groups_moved += 1

        # Set de variables para esta iteración
        cursor.execute("SET @DiaryGIDToMove = %s;", (ids_concat,))
        cursor.execute("SET @CabinetNum = %s;", (cabinet_num,))

        # UPDATE según default_product_cabin
        if default_product_cabin:
            update_sql = """
            UPDATE
                diary_gen dg
                INNER JOIN
                (
                    SELECT
                        REPLACE(
                            SUBSTRING_INDEX(pd.ProductCabinets,'|',@CabinetNum+1),
                            CONCAT(SUBSTRING_INDEX(pd.ProductCabinets,'|',@CabinetNum),'|'),
                            ''
                        ) AS CabinetNum,
                        dg.DiaryGID
                    FROM
                        diary_gen dg
                        INNER JOIN diary_det dt ON dt.DiaryGID = dg.DiaryGID
                        INNER JOIN x_config_products_det pd ON pd.ProductID = dt.DiaryZoneID
                    WHERE
                        pd.ProductCabinets LIKE '|%%'
                        AND FIND_IN_SET(dg.DiaryGID,@DiaryGIDToMove)
                        AND dg.DiaryGLocked = 0
                    HAVING
                        CabinetNum <> ''
                        AND CabinetNum NOT LIKE '|%%'
                ) dc ON dc.DiaryGID = dg.DiaryGID
            SET
                dg.DiaryGCabinetNum = dc.CabinetNum;
            """
        else:
            update_sql = """
            UPDATE
                diary_gen dg
                INNER JOIN diary_det dt ON dt.DiaryGID = dg.DiaryGID
                INNER JOIN x_config_products_det pd ON pd.ProductID = dt.DiaryZoneID
            SET
                dg.DiaryGCabinetNum = @CabinetNum
            WHERE
                FIND_IN_SET(dg.DiaryGID,@DiaryGIDToMove)
                AND dg.DiaryGLocked = 0;
            """

        cursor.execute(update_sql)
        conn.commit()

        print(f"   [diary_gen_overlaps] Iteración {total_iterations}: "
              f"ajustadas {cursor.rowcount} citas (cabina={cabinet_num}).")

        # Rotamos la cabina
        cabinet_num += 1
        if cabinet_num > max_cabinets:
            cabinet_num = 1

    print(f"   [diary_gen_overlaps] Proceso finalizado. Iteraciones={total_iterations - 1}, "
          f"grupos movidos={total_groups_moved}.")

def run(entity_config: dict, context: dict):
    """
    Proceso de migración para 'diary_gen' (agenda):

      1) DROP + CREATE de __mig_diary_gen
      2) CREATE IF NOT EXISTS de tablas de mapeo
      3) ALTER TABLE de diary_gen / diary_det / diary_det_dental para añadir columnas __Mig*
      4) Carga CSV → __mig_diary_gen (detección de delimitador, fechas, tiempos, limpieza XML)
      # 5) Inicializamos @DefaultZoneID desde MIGRATION_CONTEXT["default_diary_product"]
      6) SELECT previo + INSERT en diary_gen
      7) SELECT previo + INSERT en diary_det
      8) UPDATE diary_gen concatenando ProductDesc a DiaryGComments
      9) (Opcional) SELECT previo + INSERT en diary_det_dental si context["is_dental"] = True
    """

    mig_table = entity_config["mig_table"]        # "__mig_diary_gen"
    input_file = entity_config["input_file"]      # "diary_gen.csv"
    stop_on_error = bool(context.get("stop_on_error", False))
    is_dental = bool(context.get("is_dental", False))

    input_folder = context["input_folder"]
    input_path = Path(input_folder) / input_file

    print(f"   [diary_gen] Fichero de entrada: {input_path}")

    if not input_path.exists():
        msg = f"Fichero no encontrado: {input_path}"
        print(f"   ❌ {msg}")
        if stop_on_error:
            raise FileNotFoundError(msg)
        return False

    conn = get_connection()
    cursor = conn.cursor()

    try:
        # 1) Eliminar y crear tabla __mig_diary_gen
        print(f"   [diary_gen] Recreando tabla {mig_table}...")
        cursor.execute(f"DROP TABLE IF EXISTS {mig_table}")

        create_mig_sql = f"""
        CREATE TABLE `{mig_table}` (
            `DiaryGID` INT(11) NULL DEFAULT NULL,
            `DiaryID` INT(11) NULL DEFAULT NULL,
            `DentalID` INT(11) NULL DEFAULT NULL,
            `DiaryGClientID` INT(11) NULL DEFAULT NULL,
            `DiaryGClinicID` INT(11) NULL DEFAULT NULL,
            `DiaryGCabinetNum` INT(11) NULL DEFAULT NULL,
            `DiaryGUserID` INT(11) NULL DEFAULT NULL,
            `DiaryGSUserID` INT(11) NULL DEFAULT NULL,
            `DiaryGDate` DATE NULL DEFAULT NULL,
            `DiaryGStart` TIME NULL DEFAULT NULL,
            `DiaryGEnd` TIME NULL DEFAULT NULL,
            `DiaryGComments` TEXT NULL DEFAULT NULL COLLATE 'latin1_spanish_ci',
            `DiaryGCreated` DATETIME NULL DEFAULT NULL COMMENT 'Fecha y hora de creación de la cita',
            `DiaryGTags` VARCHAR(255) NULL DEFAULT NULL,
            `DiaryZoneID` INT(11) NULL DEFAULT NULL,
            `ProductDesc` TEXT NULL DEFAULT NULL COLLATE 'latin1_spanish_ci',
            `DentalPathologyID` INT(1) UNSIGNED NOT NULL DEFAULT '0',
            `DentalPieceStart` TINYINT(1) UNSIGNED NOT NULL DEFAULT '0',
            `DentalPieceEnd` TINYINT(1) UNSIGNED NOT NULL DEFAULT '0',
            `DentalSurfaces` TINYINT(1) UNSIGNED NOT NULL DEFAULT '0',
            `DentalNotes` TEXT NULL DEFAULT NULL
        )
        COLLATE='latin1_spanish_ci'
        ENGINE=MyISAM
        """
        cursor.execute(create_mig_sql)
        conn.commit()

        # 2) Tablas de mapeo (servicios, cabinas, usuarios)
        print("   [diary_gen] Creando tablas de mapeo si no existen...")
        mapping_sqls = [
            """
            CREATE TABLE IF NOT EXISTS `__mapping_services` (
                `id` INT(11) NOT NULL,
                `idFlowww` TEXT NULL DEFAULT NULL,
                PRIMARY KEY (`id`) USING BTREE
            )
            COLLATE='latin1_spanish_ci'
            ENGINE=MyISAM
            """,
            """
            CREATE TABLE IF NOT EXISTS `__mapping_cabinets` (
                `id` INT(11) NOT NULL,
                `idFlowww` INT(11) NULL DEFAULT NULL,
                PRIMARY KEY (`id`) USING BTREE
            )
            COLLATE='latin1_spanish_ci'
            ENGINE=MyISAM
            """,
            """
            CREATE TABLE IF NOT EXISTS `__mapping_users` (
                `id` INT(11) NOT NULL,
                `idFlowww` INT(11) NULL DEFAULT NULL,
                PRIMARY KEY (`id`) USING BTREE
            )
            COLLATE='latin1_spanish_ci'
            ENGINE=MyISAM
            """,
        ]
        for sql in mapping_sqls:
            cursor.execute(sql)
        conn.commit()

        # 3) ALTER TABLE para añadir columnas __Mig* si no existen
        print("   [diary_gen] Añadiendo columnas de mapeo a tablas definitivas (si no existen)...")
        alter_stmts = [
            "ALTER TABLE `diary_gen` ADD COLUMN `__MigDiaryGID` INT NULL DEFAULT NULL",
            "ALTER TABLE `diary_det` ADD COLUMN `__MigDiaryGID` INT NULL DEFAULT NULL",
            "ALTER TABLE `diary_det` ADD COLUMN `__MigDiaryID` INT NULL DEFAULT NULL",
            "ALTER TABLE `diary_det_dental` ADD COLUMN `__MigDentalID` INT NULL DEFAULT NULL",
        ]
        for stmt in alter_stmts:
            try:
                cursor.execute(stmt)
                conn.commit()
            except Exception as e:
                # Ignoramos errores de columna duplicada
                msg = str(e)
                if "Duplicate column name" in msg or "already exists" in msg:
                    continue
                print(f"   ⚠ Aviso en ALTER TABLE: {msg}")

        # 4) Cargar CSV en la tabla de migración
        print(f"   [diary_gen] Cargando datos en {mig_table} desde CSV...")
        
        

        with open(input_path, "r", encoding="utf-8-sig", newline="") as f:
            # Detectar delimitador ; o ,
            sample = f.read(2048)
            f.seek(0)

            delimiter = ";"
            if sample.count(",") > sample.count(";"):
                delimiter = ","

            reader = csv.DictReader(f, delimiter=delimiter)

            raw_headers = reader.fieldnames or []
            headers = [h.lstrip("\ufeff").strip() if h else h for h in raw_headers]

            # Mapeo por si algún nombre viene cambiado (ejemplo)
            mapped_headers = []
            for h in headers:
                # Aquí podrías mapear, por ejemplo: "DiaryGZoneID" -> "DiaryZoneID"
                if h == "DiaryGZoneID":
                    mapped_headers.append("DiaryZoneID")
                else:
                    mapped_headers.append(h)

            reader.fieldnames = mapped_headers
            headers = mapped_headers

            # Columnas mínimas que debería haber (core de la cita)
            required_cols = {
                "DiaryGID",
                "DiaryID",
                "DiaryGClientID",
                "DiaryGClinicID",
                "DiaryGCabinetNum",
                "DiaryGUserID",
                "DiaryGSUserID",
                "DiaryGDate",
                "DiaryGStart",
                "DiaryGEnd",
                "DiaryZoneID",
            }

            # Otras columnas que usamos si existen
            optional_cols = {
                "DiaryGComments",
                "DiaryGCreated",
                "DiaryGTags",
                "ProductDesc",
                "DentalID",
                "DentalPathologyID",
                "DentalPieceStart",
                "DentalPieceEnd",
                "DentalSurfaces",
                "DentalNotes",
            }

            if not required_cols.issubset(set(headers)):
                msg = (
                    "Las columnas del CSV no coinciden.\n"
                    f"   Encontradas: {headers}\n"
                    f"   Requeridas al menos: {sorted(required_cols)}"
                )
                print(f"   ❌ {msg}")
                if stop_on_error:
                    raise ValueError(msg)
                return False

            insert_mig_sql = f"""
                INSERT INTO {mig_table} (
                    DiaryGID,
                    DiaryID,
                    DentalID,
                    DiaryGClientID,
                    DiaryGClinicID,
                    DiaryGCabinetNum,
                    DiaryGUserID,
                    DiaryGSUserID,
                    DiaryGDate,
                    DiaryGStart,
                    DiaryGEnd,
                    DiaryGComments,
                    DiaryGCreated,
                    DiaryGTags,
                    DiaryZoneID,
                    ProductDesc,
                    DentalPathologyID,
                    DentalPieceStart,
                    DentalPieceEnd,
                    DentalSurfaces,
                    DentalNotes
                )
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """

            count = 0
            for row in reader:
                # --- Campos numéricos / IDs ---
                DiaryGID         = clean_int_value(row.get("DiaryGID"))
                DiaryID          = clean_int_value(row.get("DiaryID"))
                DentalID         = clean_int_value(row.get("DentalID")) if "DentalID" in headers else None
                DiaryGClientID   = clean_int_value(row.get("DiaryGClientID"))
                DiaryGClinicID   = clean_int_value(row.get("DiaryGClinicID"))
                DiaryGCabinetNum = clean_int_value(row.get("DiaryGCabinetNum"), default=1)
                if not DiaryGCabinetNum or DiaryGCabinetNum == 0:
                    DiaryGCabinetNum = 1
                DiaryGUserID     = clean_int_value(row.get("DiaryGUserID"))
                DiaryGSUserID    = clean_int_value(row.get("DiaryGSUserID"))
                # DiaryZoneID NO debe venir del CSV. Se fuerza al valor fijo definido en MIGRATION_CONTEXT
                DiaryZoneID = clean_int_value(context.get("default_diary_product"), default=0)

                # --- Fechas y horas ---
                DiaryGDate  = parse_date(row.get("DiaryGDate"))       # dd/mm/yyyy o yyyy-mm-dd, etc.
                DiaryGStart = parse_time(row.get("DiaryGStart"))      # 18:30:00, 9:30, etc.
                DiaryGEnd   = parse_time(row.get("DiaryGEnd"))

                # --- Textos ---
                DiaryGComments = (
                    normalize_latin1(row.get("DiaryGComments"))
                    if "DiaryGComments" in headers else None
                )

                DiaryGCreated = (
                    parse_datetime(row.get("DiaryGCreated"))
                    if "DiaryGCreated" in headers else None
                )

                DiaryGTags = (
                    normalize_latin1(row.get("DiaryGTags"))
                    if "DiaryGTags" in headers else None
                )

                ProductDesc = (
                    normalize_latin1(row.get("ProductDesc"))
                    if "ProductDesc" in headers else None
                )

                # --- Campos dentales: si no existen en el CSV o vienen vacíos/NULL, usamos 0 ---
                if "DentalPathologyID" in headers:
                    DentalPathologyID = clean_int_value(row.get("DentalPathologyID"), default=0)
                else:
                    DentalPathologyID = 0

                if "DentalPieceStart" in headers:
                    DentalPieceStart = clean_int_value(row.get("DentalPieceStart"), default=0)
                else:
                    DentalPieceStart = 0

                if "DentalPieceEnd" in headers:
                    DentalPieceEnd = clean_int_value(row.get("DentalPieceEnd"), default=0)
                else:
                    DentalPieceEnd = 0

                if "DentalSurfaces" in headers:
                    DentalSurfaces = clean_int_value(row.get("DentalSurfaces"), default=0)
                else:
                    DentalSurfaces = 0

                DentalNotes = (
                    normalize_latin1(row.get("DentalNotes"))
                    if "DentalNotes" in headers else None
                )

                data = (
                    DiaryGID,
                    DiaryID,
                    DentalID,
                    DiaryGClientID,
                    DiaryGClinicID,
                    DiaryGCabinetNum,
                    DiaryGUserID,
                    DiaryGSUserID,
                    DiaryGDate,
                    DiaryGStart,
                    DiaryGEnd,
                    DiaryGComments,
                    DiaryGCreated,
                    DiaryGTags,
                    DiaryZoneID,
                    ProductDesc,
                    DentalPathologyID,
                    DentalPieceStart,
                    DentalPieceEnd,
                    DentalSurfaces,
                    DentalNotes,
                )

                try:
                    cursor.execute(insert_mig_sql, data)
                except Exception as e:
                    print("   ❌ Error insertando fila en __mig_diary_gen:")
                    print(f"      Fila original: {row}")
                    print(f"      Datos preparados: {data}")
                    raise e

                count += 1

        conn.commit()
        print(f"   [diary_gen] Insertados {count} registros en {mig_table}.")

        # 4b) Limpieza XML en campos TEXT: DiaryGComments, ProductDesc, DentalNotes
        print("   [diary_gen] Limpiando caracteres XML en campos TEXT...")
        clean_sqls = [
            f"""
            UPDATE {mig_table}
            SET DiaryGComments = REPLACE(
                                    REPLACE(
                                      REPLACE(
                                        REPLACE(
                                          REPLACE(DiaryGComments, '&', '&amp;'),
                                        '<', '&lt;'),
                                      '>', '&gt;'),
                                    '"', '&quot;'),
                                  "'", '&apos;')
            WHERE DiaryGComments IS NOT NULL;
            """,
            f"""
            UPDATE {mig_table}
            SET ProductDesc = REPLACE(
                                    REPLACE(
                                      REPLACE(
                                        REPLACE(
                                          REPLACE(ProductDesc, '&', '&amp;'),
                                        '<', '&lt;'),
                                      '>', '&gt;'),
                                    '"', '&quot;'),
                                  "'", '&apos;')
            WHERE ProductDesc IS NOT NULL;
            """,
            f"""
            UPDATE {mig_table}
            SET DentalNotes = REPLACE(
                                    REPLACE(
                                      REPLACE(
                                        REPLACE(
                                          REPLACE(DentalNotes, '&', '&amp;'),
                                        '<', '&lt;'),
                                      '>', '&gt;'),
                                    '"', '&quot;'),
                                  "'", '&apos;')
            WHERE DentalNotes IS NOT NULL;
            """,
        ]
        for sql in clean_sqls:
            cursor.execute(sql)
        conn.commit()

        # 5) Inicializamos @DefaultZoneID desde MIGRATION_CONTEXT["default_diary_product"]
        default_zone_id = int(context.get("default_diary_product", 0))
        cursor.execute("SET @DefaultZoneID = %s;", (default_zone_id,))

        # 6) INSERT en diary_gen (previo SELECT de comprobación)
        print("   [diary_gen] Comprobando si hay citas para insertar en diary_gen...")

        check_gen_sql = f"""
        SELECT COUNT(*) FROM (
            SELECT
                __mig_diary_gen.DiaryGID
            FROM
                {mig_table} AS __mig_diary_gen
                INNER JOIN clients ON clients.ClientID = __mig_diary_gen.DiaryGClientID
                INNER JOIN x_config_clinics ON x_config_clinics.ClinicID = __mig_diary_gen.DiaryGClinicID
                LEFT JOIN __mapping_cabinets ON __mapping_cabinets.id = __mig_diary_gen.DiaryGCabinetNum
                LEFT JOIN x_config_clinics_cab 
                    ON x_config_clinics_cab.ClinicCabClinicID = __mig_diary_gen.DiaryGClinicID
                LEFT JOIN x_config_products_gen 
                    ON x_config_products_gen.ProductGClinicID = __mig_diary_gen.DiaryGClinicID
                LEFT JOIN __mapping_services 
                    ON __mapping_services.id = __mig_diary_gen.DiaryZoneID
                LEFT JOIN __mapping_users mpu1 ON mpu1.id = __mig_diary_gen.DiaryGUserID
                LEFT JOIN __mapping_users mpu2 ON mpu2.id = __mig_diary_gen.DiaryGSUserID
                LEFT JOIN x_config_products_det 
                    ON x_config_products_det.ProductSourceID = IFNULL(__mapping_services.idFlowww, @DefaultZoneID)
                   AND x_config_products_gen.ProductGID = x_config_products_det.ProductGID
                LEFT JOIN x_config_users xcu1 ON xcu1.UserID = mpu1.idFlowww
                LEFT JOIN x_config_users xcu2 ON xcu2.UserID = mpu2.idFlowww
                LEFT JOIN diary_gen ON diary_gen.__MigDiaryGID = __mig_diary_gen.DiaryGID
            WHERE
                (x_config_products_det.ProductType IN (1,4) OR x_config_products_det.ProductType IS NULL)
                AND (xcu1.UserID IS NOT NULL OR x_config_clinics_cab.ClinicCabClinicID IS NOT NULL)
                AND diary_gen.DiaryGID IS NULL
            GROUP BY
                __mig_diary_gen.DiaryGID
        ) t;
        """
        cursor.execute(check_gen_sql)
        (rows_to_insert_gen,) = cursor.fetchone()

        if rows_to_insert_gen == 0:
            msg = "No se han encontrado citas nuevas para insertar en diary_gen."
            print(f"   ⚠ {msg}")
        else:
            print(f"   [diary_gen] Se van a insertar {rows_to_insert_gen} registros en diary_gen.")
            
            # Reaseguramos @DefaultZoneID antes del INSERT en diary_gen
            cursor.execute("SET @DefaultZoneID = %s;", (default_zone_id,))
            
            insert_gen_sql = f"""
            INSERT INTO
                diary_gen
                (
                    DiaryGClinicID,
                    DiaryGClientID,
                    DiaryGCabinetNum,
                    DiaryGUserID,
                    DiaryGSUserID,
                    DiaryGDate,
                    DiaryGStart,
                    DiaryGEnd,
                    DiaryGComments,
                    DiaryGTags,
                    DiaryGStamp,
                    DiaryGCreated,
                    __MigDiaryGID
                )
            SELECT
                x_config_clinics.ClinicID,
                clients.ClientID,
                IFNULL(x_config_clinics_cab.ClinicCabID,1),
                IFNULL(xcu1.UserID,0),
                IFNULL(xcu2.UserID,0),
                __mig_diary_gen.DiaryGDate,
                __mig_diary_gen.DiaryGStart,
                __mig_diary_gen.DiaryGEnd,
                __mig_diary_gen.DiaryGComments,
                IFNULL(__mig_diary_gen.DiaryGTags,''),
                CAST(CONCAT(CURDATE(),' 00:00:00') AS DATETIME),
                __mig_diary_gen.DiaryGCreated,
                __mig_diary_gen.DiaryGID
            FROM
                {mig_table} AS __mig_diary_gen
                INNER JOIN clients ON clients.ClientID = __mig_diary_gen.DiaryGClientID
                INNER JOIN x_config_clinics ON x_config_clinics.ClinicID = __mig_diary_gen.DiaryGClinicID
                LEFT JOIN __mapping_cabinets ON __mapping_cabinets.id = __mig_diary_gen.DiaryGCabinetNum
                LEFT JOIN x_config_clinics_cab 
                    ON x_config_clinics_cab.ClinicCabClinicID = __mig_diary_gen.DiaryGClinicID
                LEFT JOIN x_config_products_gen 
                    ON x_config_products_gen.ProductGClinicID = __mig_diary_gen.DiaryGClinicID
                LEFT JOIN __mapping_services 
                    ON __mapping_services.id = __mig_diary_gen.DiaryZoneID
                LEFT JOIN __mapping_users mpu1 ON mpu1.id = __mig_diary_gen.DiaryGUserID
                LEFT JOIN __mapping_users mpu2 ON mpu2.id = __mig_diary_gen.DiaryGSUserID
                LEFT JOIN x_config_products_det 
                    ON x_config_products_det.ProductSourceID = IFNULL(__mapping_services.idFlowww, @DefaultZoneID)
                   AND x_config_products_gen.ProductGID = x_config_products_det.ProductGID
                LEFT JOIN x_config_users xcu1 ON xcu1.UserID = mpu1.idFlowww
                LEFT JOIN x_config_users xcu2 ON xcu2.UserID = mpu2.idFlowww
                LEFT JOIN diary_gen ON diary_gen.__MigDiaryGID = __mig_diary_gen.DiaryGID
            WHERE
                (x_config_products_det.ProductType IN (1,4) OR x_config_products_det.ProductType IS NULL)
                AND (xcu1.UserID IS NOT NULL OR x_config_clinics_cab.ClinicCabClinicID IS NOT NULL)
                AND diary_gen.DiaryGID IS NULL
            GROUP BY 
                __mig_diary_gen.DiaryGID;
            """
            cursor.execute(insert_gen_sql)
            conn.commit()
            print(f"   ✔ Insertadas {cursor.rowcount} filas en diary_gen.")

        # 7) INSERT en diary_det
        print("   [diary_gen] Comprobando datos para insertar en diary_det...")
        check_det_sql = f"""
        SELECT COUNT(*) FROM (
            SELECT
                __mig_diary_gen.DiaryID
            FROM
                {mig_table} AS __mig_diary_gen
                INNER JOIN diary_gen ON diary_gen.__MigDiaryGID = __mig_diary_gen.DiaryGID
                LEFT JOIN diary_det ON diary_det.__MigDiaryID = __mig_diary_gen.DiaryID
                INNER JOIN x_config_products_gen 
                    ON x_config_products_gen.ProductGClinicID = __mig_diary_gen.DiaryGClinicID
                LEFT JOIN __mapping_services 
                    ON __mapping_services.id = __mig_diary_gen.DiaryZoneID
                LEFT JOIN x_config_products_det 
                    ON x_config_products_det.ProductSourceID = IFNULL(__mapping_services.idFlowww, @DefaultZoneID)
                   AND x_config_products_gen.ProductGID = x_config_products_det.ProductGID
            WHERE
                -- x_config_products_det.ProductType IN (1,4) AND 
                diary_det.DiaryID IS NULL
            GROUP BY
                __mig_diary_gen.DiaryID
        ) t;
        """
        cursor.execute(check_det_sql)
        (rows_to_insert_det,) = cursor.fetchone()

        if rows_to_insert_det == 0:
            print("   ⚠ No se han encontrado detalles para insertar en diary_det.")
        else:
            print(f"   [diary_gen] Se van a insertar {rows_to_insert_det} registros en diary_det.")
            insert_det_sql = f"""
            INSERT INTO
                diary_det
                (
                    DiaryGID,
                    DiaryZoneID,
                    __MigDiaryID,
                    __MigDiaryGID
                )
            SELECT
                diary_gen.DiaryGID,
                __mig_diary_gen.DiaryZoneID,
                __mig_diary_gen.DiaryID,
                __mig_diary_gen.DiaryGID
            FROM
                {mig_table} AS __mig_diary_gen
                INNER JOIN diary_gen ON diary_gen.__MigDiaryGID = __mig_diary_gen.DiaryGID
                LEFT JOIN diary_det ON diary_det.__MigDiaryID = __mig_diary_gen.DiaryID
                INNER JOIN x_config_products_gen 
                    ON x_config_products_gen.ProductGClinicID = __mig_diary_gen.DiaryGClinicID
                LEFT JOIN __mapping_services 
                    ON __mapping_services.id = __mig_diary_gen.DiaryZoneID
                LEFT JOIN x_config_products_det 
                    ON x_config_products_det.ProductSourceID = IFNULL(__mapping_services.idFlowww, @DefaultZoneID)
                   AND x_config_products_gen.ProductGID = x_config_products_det.ProductGID
            WHERE
                -- x_config_products_det.ProductType IN (1,4) and
                diary_det.DiaryID IS NULL
            GROUP BY
                __mig_diary_gen.DiaryID;
            """
            cursor.execute(insert_det_sql)
            conn.commit()
            print(f"   ✔ Insertados {cursor.rowcount} registros en diary_det.")

        # 8) UPDATE de diary_gen concatenando ProductDesc a DiaryGComments
        print("   [diary_gen] Actualizando DiaryGComments con ProductDesc (si aplica)...")
        update_comments_sql = f"""
        UPDATE
            diary_gen
            INNER JOIN (
                SELECT
                    __mig_diary_gen.DiaryGID,
                    __mig_diary_gen.ProductDesc
                FROM
                    diary_det
                    INNER JOIN x_config_products_det 
                        ON x_config_products_det.ProductID = diary_det.DiaryZoneID
                    INNER JOIN {mig_table} AS __mig_diary_gen
                        ON __mig_diary_gen.DiaryGID = diary_det.__MigDiaryGID
                WHERE
                    x_config_products_det.ProductSourceID = @DefaultZoneID
                GROUP BY
                    diary_det.DiaryGID
            ) AS tmp ON tmp.DiaryGID = diary_gen.__MigDiaryGID
        SET
            diary_gen.DiaryGComments = CONCAT(
                tmp.ProductDesc,
                CHAR(10),
                diary_gen.DiaryGComments
            );
        """
        cursor.execute(update_comments_sql)
        conn.commit()

        # 9) Inserción dental opcional
        if is_dental:
            print("   [diary_gen] is_dental=True → comprobando datos para diary_det_dental...")
            check_dental_sql = f"""
            SELECT COUNT(*) FROM (
                SELECT
                    __mig_diary_gen.DentalID
                FROM
                    {mig_table} AS __mig_diary_gen
                    INNER JOIN diary_det ON diary_det.__MigDiaryID = __mig_diary_gen.DiaryID
                    LEFT JOIN x_config_dental_pathologies 
                        ON x_config_dental_pathologies.PathologyID = __mig_diary_gen.DentalPathologyID
                GROUP BY
                    __mig_diary_gen.DentalID
            ) t;
            """
            cursor.execute(check_dental_sql)
            (rows_to_insert_dental,) = cursor.fetchone()

            if rows_to_insert_dental == 0:
                print("   ⚠ No se han encontrado registros para insertar en diary_det_dental.")
            else:
                print(f"   [diary_gen] Se van a insertar {rows_to_insert_dental} registros en diary_det_dental.")
                insert_dental_sql = f"""
                INSERT INTO
                    diary_det_dental
                    (
                        DentalDiaryID,
                        DentalPathologyID,
                        DentalPieceStart,
                        DentalPieceEnd,
                        DentalSurfaces,
                        DentalNotes,
                        __MigDentalID
                    )
                SELECT
                    diary_det.DiaryID,
                    IFNULL(x_config_dental_pathologies.PathologyID,0),
                    __mig_diary_gen.DentalPieceStart,
                    __mig_diary_gen.DentalPieceEnd,
                    __mig_diary_gen.DentalSurfaces,
                    __mig_diary_gen.DentalNotes,
                    __mig_diary_gen.DentalID
                FROM
                    {mig_table} AS __mig_diary_gen
                    INNER JOIN diary_det ON diary_det.__MigDiaryID = __mig_diary_gen.DiaryID
                    LEFT JOIN x_config_dental_pathologies 
                        ON x_config_dental_pathologies.PathologyID = __mig_diary_gen.DentalPathologyID
                GROUP BY
                    __mig_diary_gen.DentalID;
                """
                cursor.execute(insert_dental_sql)
                conn.commit()
                print(f"   ✔ Insertados {cursor.rowcount} registros en diary_det_dental.")
        else:
            print("   [diary_gen] is_dental=False → se omite inserción en diary_det_dental.")

        
          #  🔚 Paso final: resolución de solapamientos (overlaps)
        if context.get("resolve_overlaps", True):
            print("   [diary_gen_overlaps] Iniciando proceso de resolución de solapamientos...")
            try:
                resolve_diary_overlaps(cursor, conn, context)
            except Exception as e:
                print("   ❌ Error en diary_gen_overlaps:", e)
                if stop_on_error:
                    raise
        else:
            print("   [diary_gen_overlaps] Omitido (resolve_overlaps=False en MIGRATION_CONTEXT).")

        return True

    finally:
        cursor.close()
        conn.close()
