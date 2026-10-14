import os
import sys
from pathlib import Path

# ==============================
# AÑADIR CARPETA RAÍZ AL sys.path
# ==============================
BASE_DIR = Path(__file__).resolve().parent.parent  # carpeta raíz del proyecto
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from step01_config import MYSQL_CONFIG, SESSION_SQL_INIT
import mysql.connector
from mysql.connector import Error


def test_connection() -> bool:
    """
    Intenta conectarse a MySQL usando la configuración de step01_config.py.
    Devuelve True si la conexión es correcta, False si falla.
    """
    print("➡️ test_connection() iniciado...")
    print(f"   Host: {MYSQL_CONFIG.get('host')}")
    print(f"   DB:   {MYSQL_CONFIG.get('database')}")

    # Clonamos la config y añadimos opciones extra
    cfg = dict(MYSQL_CONFIG)
    cfg.setdefault("connection_timeout", 5)

    # 🔴 IMPORTANTE: forzar modo pure Python (evita crashes nativos)
    cfg["use_pure"] = True

    # Opcional: desactivar SSL si el server no lo pide
    # cfg["ssl_disabled"] = True

    try:
        print("   [DEBUG] Antes de mysql.connector.connect()")
        conn = mysql.connector.connect(**cfg)
        print("   [DEBUG] Después de mysql.connector.connect()")

        cursor = conn.cursor()
        print("   [DEBUG] Ejecutando SESSION_SQL_INIT...")
        cursor.execute(SESSION_SQL_INIT)
        cursor.close()
        conn.close()

        print("   ✅ Conexión correcta a MySQL y sesión inicializada.")
        return True

    except Error as e:
        print("   ❌ Error de conexión a MySQL (mysql.connector.Error):")
        print(f"      {e}")
        return False

    except Exception as e:
        print("   ❌ Error inesperado en test_connection():")
        print(f"      {e}")
        return False


def get_connection():
    cfg = dict(MYSQL_CONFIG)
    cfg.setdefault("connection_timeout", 5)
    cfg["use_pure"] = True
    # cfg["ssl_disabled"] = True

    conn = mysql.connector.connect(**cfg)
    cursor = conn.cursor()
    cursor.execute(SESSION_SQL_INIT)
    cursor.close()
    return conn


if __name__ == "__main__":
    print("🔵 Ejecutando test_connection() en step02_db.py directamente...")
    ok = test_connection()
    print(f"🔚 Resultado test_connection(): {ok}")
