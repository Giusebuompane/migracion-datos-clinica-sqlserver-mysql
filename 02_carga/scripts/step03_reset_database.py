# step03_reset_db.py
import os
import subprocess
import zipfile
from datetime import datetime
from pathlib import Path

from step02_db import get_connection
from step01_config import MYSQL_CONFIG, BASE_DIR


# Carpeta de backups: /backup dentro del proyecto
BACKUP_DIR = BASE_DIR / "backup"


# DROP por separado
SQL_DROP_PROC = "DROP PROCEDURE IF EXISTS _fResetDB"

# CREATE PROCEDURE completo en UNA sola sentencia
SQL_CREATE_PROC = """
CREATE PROCEDURE `_fResetDB`(IN sDBSource varchar(255), IN sType enum ('C', 'P', 'CP', 'N'))
    COMMENT 'Resetea una base de datos'
BEGIN
    DECLARE done BOOL DEFAULT FALSE;
    DECLARE sTruncateCommand VARCHAR(512);
    DECLARE truncate_cur
        CURSOR FOR
        SELECT CONCAT('TRUNCATE TABLE `', sDBSource, '`.`', table_name, '`')
        FROM INFORMATION_SCHEMA.TABLES
        WHERE table_schema = sDBSource
          AND engine IN ('InnoDB', 'MyISAM', 'MEMORY', 'HEAP')
          AND ((TABLE_NAME NOT LIKE 'x_%'
            AND TABLE_NAME NOT LIKE 'y_%'
            AND TABLE_NAME NOT LIKE 'z_%'
            AND TABLE_NAME NOT LIKE '__mapping%'
            AND NOT FIND_IN_SET(TABLE_NAME, @Exclude))
            OR FIND_IN_SET(TABLE_NAME, @Include));

    DECLARE CONTINUE HANDLER FOR SQLSTATE '02000' SET done = TRUE;

    SET @Exclude = 'registry,sessions,messages,chargebee_hierarchy,x_config_services';
    SET @Clients =
            ',clients,clients_cards,clients_ccc,clients_crm,clients_merge,clients_merge_history,clients_referers,clients_visits';
    SET @Products =
            ',stock,x_config_products_con,x_config_products_det,x_config_products_fam,x_config_products_gen,x_config_products_gen_inh,x_config_products_inc,x_config_products_pack,x_config_products_points,x_config_products_rel,x_config_products_vat,x_config_products_zc,x_config_protocols';
    SET @Include = '';

    IF sType = 'C' THEN
        SET @Exclude = CONCAT(@Exclude, @Clients);
        SET @Include = CONCAT(@Include, @Products);
    ELSEIF sType = 'CP' THEN
        SET @Exclude = CONCAT(@Exclude, @Clients);
        SET @Exclude = CONCAT(@Exclude, @Products);
    ELSEIF sType = 'P' THEN
        SET @Include = CONCAT(@Include, @Clients);
        SET @Exclude = CONCAT(@Exclude, @Products);
    ELSEIF sType = 'N' THEN
        SET @Include = CONCAT(@Include, @Products);
    END IF;

    SET FOREIGN_KEY_CHECKS = 0;

    OPEN truncate_cur;
    truncate_loop:
    LOOP
        FETCH truncate_cur INTO sTruncateCommand;
        SET @TruncateCommand = sTruncateCommand;

        IF done THEN
            CLOSE truncate_cur;
            LEAVE truncate_loop;
        END IF;

        PREPARE truncate_command_stmt FROM @TruncateCommand;
        EXECUTE truncate_command_stmt;
        DEALLOCATE PREPARE truncate_command_stmt;
    END LOOP;

    SET FOREIGN_KEY_CHECKS = 1;

END
"""


def create_backup() -> Path | None:
    """
    Realiza un backup completo de la base de datos usando mysqldump.
    Devuelve la ruta ZIP si ok, o None si falla.
    """
    db_name = MYSQL_CONFIG["database"]
    host = MYSQL_CONFIG["host"]
    port = MYSQL_CONFIG.get("port", 3306)
    user = MYSQL_CONFIG["user"]
    password = MYSQL_CONFIG["password"]

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d%H%M%S")
    base_filename = f"backup_{db_name}_{ts}"
    sql_path = BACKUP_DIR / f"{base_filename}.sql"
    zip_path = BACKUP_DIR / f"{base_filename}.zip"

    print(f"Creando backup en: {zip_path}")

    cmd = [
        "mysqldump",
        "-h", host,
        "-P", str(port),
        "-u", user,
        f"-p{password}",
        db_name,
    ]

    try:
        with open(sql_path, "w", encoding="latin1") as f_out:
            result = subprocess.run(
                cmd, stdout=f_out, stderr=subprocess.PIPE, text=True
            )
    except FileNotFoundError:
        print("❌ No se encuentra mysqldump.")
        return None

    if result.returncode != 0:
        print("❌ Error en mysqldump:")
        print(result.stderr)
        if sql_path.exists():
            sql_path.unlink()
        return None

    try:
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(sql_path, arcname=sql_path.name)
        sql_path.unlink()
    except Exception as e:
        print("❌ Error comprimiendo backup ZIP:", e)
        return None

    print(f"✔ Backup creado correctamente: {zip_path}")
    return zip_path


def reset_database():
    db_name = MYSQL_CONFIG["database"]

    # PREGUNTA INTERACTIVA
    print("¿Deseas realizar un backup completo antes de limpiar la base de datos? (y/n): ", end="")
    answer = input().strip().lower()

    while answer not in ("y", "n"):
        print("Respuesta no válida. Por favor responde 'y' o 'n': ", end="")
        answer = input().strip().lower()

    if answer == "y":
        print("=== BACKUP PREVIO A RESETEO ===")
        backup_path = create_backup()
        if backup_path is None:
            print("❌ El backup ha fallado. No se realizará el reseteo.")
            return
        print("Backup OK. Continuando con el reseteo...")
    else:
        print("ℹ Se ha elegido no realizar backup. Continuando con el reseteo...")

    # === RESETEO ===
    print("Conectando a MySQL para ejecutar el reseteo...")

    conn = get_connection()
    cursor = conn.cursor()

    try:
        print("Eliminando _fResetDB (si existe)...")
        cursor.execute(SQL_DROP_PROC)

        print("Creando _fResetDB...")
        cursor.execute(SQL_CREATE_PROC)

        print("Ejecutando CALL _fResetDB...")
        cursor.execute(f"CALL _fResetDB('{db_name}', 'P')")
        conn.commit()

        print("✔ Base de datos reseteada correctamente.")

    except Exception as e:
        print("❌ ERROR realizando el reseteo:")
        print(e)

    finally:
        cursor.close()
        conn.close()


if __name__ == "__main__":
    reset_database()
