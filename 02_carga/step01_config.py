# config.py
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


# Carpeta base del proyecto (ajusta a tu ruta real)
BASE_DIR = Path(__file__).resolve().parent

# ==============
# CONFIG MYSQL
# ==============

MYSQL_CONFIG = {
    # Credenciales en el fichero .env (ver .env.example)
    "host": os.getenv("MYSQL_HOST"),
    "database": os.getenv("MYSQL_DATABASE"),
    "port": int(os.getenv("MYSQL_PORT", "3306")),
    "user": os.getenv("MYSQL_USER"),
    "password": os.getenv("MYSQL_PASSWORD"),
    # MUY IMPORTANTE: mismo charset que la BBDD
    "charset": "latin1",
    # Para mysql-connector-python:
    "use_unicode": True,
    "autocommit": False,
    # Forzar collation correcto en la sesión
    "client_flags": [],
    "connection_timeout": 30,
}

# Si quieres asegurarte de que la collation de la sesión es la correcta,
# luego en db.py lanzaremos: SET NAMES 'latin1' COLLATE 'latin1_spanish_ci';

SESSION_SQL_INIT = "SET NAMES 'latin1' COLLATE 'latin1_spanish_ci';"


# ==============
# CONTEXTO DE MIGRACIÓN
# ==============

MIGRATION_CONTEXT = {
    # SystemKey o identificador del cliente en Flowww
    "system_key": os.getenv("FLOWWW_SYSTEM_KEY"),  #### <<- AJUSTAR

    # Clínicas a procesar (si aplica)
    "clinic_ids": [1], #### <<- AJUSTAR según el caso
    
    # Es multicentro ?
    "multicenter": False, #### <<- AJUSTAR según el caso
    
    # Es dental (si aplica)
    "is_dental": False,  #### <<- AJUSTAR según el caso
    
    # El producto tiene cabina predefinida?
    "default_product_cabin": False,   #### <<- AJUSTAR según el caso
    
    # Producto por defecto en diary_gen (producto "migrado" creado manualmente en Flowww)
    "default_diary_product": 1466,   #### <<- AJUSTAR según el caso
    
     # Resolver overlaps de agenda?
    "resolve_overlaps": True,   #### <<- AJUSTAR según el caso
    
    # gift_vouchers se facturan o no (x_config_paymethods.Pay_MethodInvoice=-1 o x_config_paymethods.Pay_MethodInvoice=0)
    "gift_vouchers_invoiced": True,   #### <<- AJUSTAR según el caso
    
     # Realizar reset de la base de datos antes de subir información
    "reset_database": False,   #### <<- AJUSTAR según el caso

    # Si quieres que el script maestro se pare en el primer error crítico
    "stop_on_error": True,

    # Ruta de ficheros de entrada (Excel, CSV, etc. si los usas)
    "input_folder": BASE_DIR / "input",

    # Carpeta de logs (te la recomiendo para registrar cada paso)
    "log_folder": BASE_DIR / "logs",

    # Carpeta donde podrías guardar scripts SQL auxiliares si los ejecutas desde Python
    "sql_folder": BASE_DIR / "sql",

}

# ==============
# CONCEPTOS / TABLAS DE MIGRACIÓN
# ==============
# Aquí definimos qué conceptos se migran, de qué tabla __mig_* vienen,
# a qué tabla final van y, opcionalmente, de qué fichero de entrada salen.

MIGRATION_ENTITIES = {
    "clients": {
        "label": "Clientes",
        "mig_table": "__mig_clients",
        "target_table": "clients",
        "input_file": "clients.csv",   # o .csv, ajusta luego
        "script_file": "load_clients.py",
        "primary_key": "ClientID",
        "enabled": False,
        "order": 10,
    },
    "clients_crm": {
        "label": "Clientes CRM",
        "mig_table": "__mig_clients_crm",
        "target_table": "clients_crm",
        "input_file": "clients_crm.csv",   # o .csv, ajusta luego
        "script_file": "load_clients_crm.py",
        "primary_key": "ClientCID",
        "enabled": False,
        "order": 11,
    },
    "diary_gen": {
        "label": "Agenda",
        "mig_table": "__mig_diary_gen",
        "target_table": "diary_gen",
        "input_file": "diary_gen.csv",
        "script_file": "load_diary_gen.py",
        "primary_key": "DiaryGID",
        "enabled": False,
        "order": 20,
    },
    "diary_gen_locks": {
        "label": "Bloqueos de agenda",
        "mig_table": "__mig_diary_gen_locks",
        "target_table": "diary_gen_locks",
        "input_file": "diary_gen_locks.csv",
        "script_file": "load_diary_gen_locks.py",
        "primary_key": "DiaryGLockID",   # ajusta al real
        "enabled": False,                # por ejemplo, aún no lo migras
        "order": 30,
    },
    "laser_gen": {
        "label": "Historial tratamientos",
        "mig_table": "__mig_laser_gen",
        "target_table": "laser_gen",
        "input_file": "laser_gen.csv",
        "script_file": "load_laser_gen.py",
        "primary_key": "LaserGID",
        "enabled": False,
        "order": 40,
    },
    "prescriptions": {
        "label": "Historial clínico",
        "mig_table": "__mig_prescriptions",
        "target_table": "prescriptions",
        "input_file": "prescriptions.csv",
        "script_file": "load_prescriptions.py",
        "primary_key": "PrescriptionID",
        "enabled": False,
        "order": 50,
    },
    "budgets_gen": {
        "label": "Presupuestos",
        "mig_table": "__mig_budgets_gen",
        "target_table": "budgets_gen",
        "input_file": "budgets_gen.csv",
        "script_file": "load_budgets_gen.py",
        "primary_key": "BudgetGID",
        "enabled": True,
        "order": 60,
    },
    "files": {
        "label": "Archivos",
        "mig_table": "__mig_files",
        "target_table": "files",
        "input_file": "files.csv",
        "script_file": "load_files.py",
        "primary_key": "FileID",
        "enabled": False,
        "order": 70,
    },
    "pictures": {
        "label": "Imagenes",
        "mig_table": "__mig_pictures",
        "target_table": "pictures",
        "input_file": "pictures.csv",
        "script_file": "load_pictures.py",
        "primary_key": "PictureID",
        "enabled": False,
        "order": 71,
    },
    "vouchers": {
        "label": "Bonos",
        "mig_table": "__mig_vouchers",
        "target_table": "vouchers",
        "input_file": "vouchers.csv",
        "script_file": "load_vouchers.py",
        "primary_key": "VoucherID",
        "enabled": False,
        "order": 80,
    },
    "gift_vouchers": {
        "label": "Cheques Regalo",
        "mig_table": "__mig_gift_vouchers",
        "target_table": "gift_vouchers",
        "input_file": "gift_vouchers.csv",
        "script_file": "load_gift_vouchers.py",
        "primary_key": "GiftVoucherID",
        "enabled": False,
        "order": 81,
    },
    "gift_vouchers_invoiced": {
        "label": "Cheques Regalo",
        "mig_table": "__mig_gift_vouchers_invoiced",
        "target_table": "gift_vouchers",
        "input_file": "gift_vouchers.csv",
        "script_file": "load_gift_vouchers_invoiced.py",
        "primary_key": "GiftVoucherID",
        "enabled": False,
        "order": 82,
    },
    "deferred_uninvoiced": {
        "label": "Deuda no facturada",
        "mig_table": "__mig_deferred_uninvoiced",
        "target_table": "deferred_uninvoiced",
        "input_file": "deferred_uninvoiced.csv",
        "script_file": "load_deferred_uninvoiced.py",
        "primary_key": "DeferredUID",
        "enabled": False,
        "order": 83,
    },
        "advances_gen": {
        "label": "Avances de pago",
        "mig_table": "__mig_advances_gen",
        "target_table": "advances_gen",
        "input_file": "advances_gen.csv",  
        "script_file": "load_advances_gen.py",
        "primary_key": "AdvanceGID",  
        "enabled": False,  
        "order": 90,  
    },
    "clients_tracking": {
        "label": "Seguimiento de clientes",
        "mig_table": "__mig_clients_tracking_gen",
        "target_table": "clients_tracking_gen",
        "input_file": "clients_tracking_gen.csv",  
        "script_file": "load_clients_tracking_gen.py",  
        "primary_key": "TrackGID",  
        "enabled": False,  
        "order": 91,  
    },
    "diary_gen_hidden": {
        "label": "Agenda Oculta",
        "mig_table": "__mig_diary_gen_hidden",
        "target_table": "diary_gen",
        "input_file": "diary_gen_hidden.csv",  
        "script_file": "load_diary_gen_hidden.py",  
        "primary_key": "DiaryGID",  
        "enabled": False,  
        "order": 92,  
    }



    # Aquí irías añadiendo el resto:
    # "tickets_gen": { ... },
    # "tickets_det": { ... },
    # "laser_gen": { ... },
    # etc.
}

