import sys
import importlib
import traceback
from pathlib import Path
from datetime import datetime

from step01_config import MIGRATION_ENTITIES, MIGRATION_CONTEXT


class Tee:
    """
    Escribe simultáneamente en varios streams (por ejemplo, stdout y un fichero).
    """
    def __init__(self, *streams):
        self.streams = streams

    def write(self, data):
        for s in self.streams:
            s.write(data)
        self.flush()

    def flush(self):
        for s in self.streams:
            s.flush()


# ==== RUTAS ====
BASE_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = BASE_DIR / "scripts"

# Añadimos /scripts al sys.path para poder importar los loaders y step0X_*
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


def print_header(title: str):
    print("\n" + "=" * 70)
    print(f"🔵 {title}")
    print("=" * 70)


def print_total_time(start_dt: datetime):
    """
    Imprime el tiempo total transcurrido desde start_dt hasta ahora.
    """
    end_dt = datetime.now()
    elapsed = end_dt - start_dt
    secs = elapsed.total_seconds()
    mins = secs / 60 if secs else 0

    print("\n" + "-" * 70)
    print(f"⏱ Tiempo total del proceso: {secs:.1f} segundos (~{mins:.1f} minutos)")
    print("-" * 70)


# ======================
# STEP 2 -> TEST CONEXIÓN
# ======================
def run_step_test_db() -> bool:
    """
    STEP 2: prueba básica de conexión a MySQL usando step02_db.
    Si hay función test_connection() se usa; si no, abre y cierra get_connection().
    """
    print_header("STEP 2 → TEST CONEXIÓN BASE DE DATOS")

    try:
        mod = importlib.import_module("step02_db")

        # Si definimos un test_connection() en step02_db, lo usamos
        if hasattr(mod, "test_connection"):
            ok = mod.test_connection()
            # Si no devuelve nada, consideramos OK
            return True if ok is None else bool(ok)

        # Si no hay test_connection, usamos get_connection() directamente
        if hasattr(mod, "get_connection"):
            conn = mod.get_connection()
            conn.close()
            print("✔ Conexión correcta a MySQL con la configuración de config.py.")
            return True

        print("❌ step02_db.py no tiene ni test_connection() ni get_connection().")
        return False

    except Exception:
        print("❌ ERROR en el test de conexión (STEP 2):")
        traceback.print_exc()
        return False


# =========================
# STEP 3 -> BACKUP + RESET
# =========================
def run_step_reset_db() -> bool:
    """
    STEP 3: Ejecuta el reset de BBDD (step03_reset_database).

    Intenta, por este orden:
    - step03_reset_database.run()
    - step03_reset_database.reset_database()
    """
    print_header("STEP 3 → BACKUP + RESET DE BASE DE DATOS")

    try:
        mod = importlib.import_module("step03_reset_database")

        if hasattr(mod, "run"):
            result = mod.run()
            return True if result is None else bool(result)

        elif hasattr(mod, "reset_database"):
            mod.reset_database()
            return True

        else:
            print("❌ ERROR: step03_reset_database no tiene ni run() ni reset_database().")
            return False

    except Exception:
        print("❌ ERROR ejecutando reset_database (STEP 3):")
        traceback.print_exc()
        return False


# ====================
# LOADERS (STEP 4)
# ====================

def resolve_script_file(script_file: str, context: dict, scripts_dir: Path) -> str:
    """
    Devuelve el script_file correcto según el contexto multicenter.
    Si multicenter=True, exige que exista el *_multi.py.
    """
    if not script_file:
        return script_file

    is_multi = bool(context.get("multicenter", False))
    if not is_multi:
        return script_file

    p = Path(script_file)
    multi_script = f"{p.stem}_multi{p.suffix}"
    multi_path = scripts_dir / multi_script

    if not multi_path.exists():
        raise FileNotFoundError(
            f"❌ Migración configurada como MULTICENTER pero no existe el loader:\n"
            f"   - Esperado: {multi_script}\n"
            f"   - Ruta: {multi_path}\n"
            f"   👉 Crea el loader *_multi.py o desactiva multicenter en step01_config.py"
        )

    return multi_script

def run_loader(entity_key: str, entity_cfg: dict):
    """
    Importa y ejecuta el loader para una entidad dada.

    Se espera un script en /scripts con nombre entity_cfg["script_file"]
    y que dicho script tenga una función:
        run(entity_config: dict, context: dict)

    Devuelve:
        (ok: bool, result: any)
    """
    label = entity_cfg.get("label", entity_key)
    print_header(f"STEP 4 → LOAD {entity_key} ({label})")

    script_file = entity_cfg.get("script_file")
    if not script_file:
        print(f"❌ La entidad '{entity_key}' no tiene 'script_file' en MIGRATION_ENTITIES.")
        return False, None

    try:
        script_file = resolve_script_file(script_file, MIGRATION_CONTEXT, SCRIPTS_DIR)
    except FileNotFoundError as e:
        print(str(e))
        return False, None

    script_name = Path(script_file).stem
    script_path = SCRIPTS_DIR / script_file

    if not script_path.exists():
        print(f"❌ ERROR: No se encuentra el script {script_path}")
        return False, None

    try:
        loader_module = importlib.import_module(script_name)

        if not hasattr(loader_module, "run"):
            print(f"❌ El script {script_name}.py no tiene función run(entity_config, context).")
            return False, None

        # Nuestros loaders tienen firma: run(entity_config, context)
        result = loader_module.run(entity_cfg, MIGRATION_CONTEXT)

        # Interpretamos el resultado para determinar si ha ido OK
        ok = True
        if isinstance(result, dict):
            status = result.get("status")
            if status is not None and str(status).lower() not in ("ok", "success", "done"):
                ok = False
        elif isinstance(result, bool):
            ok = result

        return ok, result

    except Exception:
        print(f"❌ Error ejecutando loader {script_name}:")
        traceback.print_exc()
        return False, None


def orchestrate() -> bool:
    # Marca de inicio de TODO el proceso
    process_start = datetime.now()

    print_header("🚀 INICIO PROCESO DE MIGRACIÓN")

    # ======================
    # STEP 2: Test conexión
    # ======================
    ok_conn = run_step_test_db()
    if not ok_conn:
        print("❌ El proceso se detiene porque ha fallado el test de conexión (STEP 2).")
        print_total_time(process_start)
        return False

    # =========================
    # STEP 3: Backup + Reset
    # =========================
    # Nuevo comportamiento:
    # - MIGRATION_CONTEXT["reset_database"] controla si el reset está habilitado.
    # - Si reset_database=False → no se ejecuta STEP 3, ni se pregunta nada.
    # - Si reset_database=True → se pide confirmación explícita al usuario.
    reset_db_flag = bool(MIGRATION_CONTEXT.get("reset_database", True))

    if reset_db_flag:
        print_header("STEP 3 → BACKUP + RESET DE BASE DE DATOS")
        print("⚠ Según la configuración (reset_database=True), está previsto ejecutar el reset de la base de datos.")
        print("   Este paso normalmente realizará un backup previo (si está implementado)")
        print("   y después vaciará / reseteará tablas de destino antes de la migración.\n")

        answer = input("   ¿Confirmas que quieres ejecutar el reset de la base de datos? (S/N): ").strip().lower()
        if answer in ("s", "si", "y", "yes"):
            ok_reset = run_step_reset_db()
            if not ok_reset:
                print("❌ El proceso se detiene porque falló el reset (STEP 3).")
                print_total_time(process_start)
                return False
        else:
            print("   ➡ STEP 3 omitido: el usuario ha cancelado el reset de la base de datos.")
    else:
        print_header("STEP 3 → BACKUP + RESET DE BASE DE DATOS")
        print("ℹ STEP 3 omitido porque MIGRATION_CONTEXT['reset_database'] = False (no se hará reset).")

    # =========================
    # AVISO ESPECIAL CLIENTES
    # =========================
    clients_cfg = MIGRATION_ENTITIES.get("clients")
    if clients_cfg and not clients_cfg.get("enabled", False):
        print()
        print("⚠ La entidad 'clients' está deshabilitada (enabled=False).")
        print("⚠ Debes cargar los datos de Clientes manualmente ANTES de continuar.")
        input("➡ Pulsa INTRO cuando hayas completado la carga manual de clientes... ")

    # =========================
    # STEP 4: Loaders
    # =========================
    step4_start = datetime.now()
    summary = {}

    enabled_entities = [
        (key, cfg)
        for key, cfg in MIGRATION_ENTITIES.items()
        if cfg.get("enabled", False)
    ]

    enabled_entities.sort(key=lambda x: x[1].get("order", 9999))

    if not enabled_entities:
        print("⚠ No hay entidades habilitadas para migrar (enabled=True).")
        print_total_time(process_start)
        return False

    stop_on_error = bool(MIGRATION_CONTEXT.get("stop_on_error", True))

    for key, cfg in enabled_entities:
        ok, result = run_loader(key, cfg)

        # Guardamos en resumen lo que devuelva el loader si es dict (o el valor bruto)
        if isinstance(result, dict):
            summary[key] = result
        elif result is not None:
            summary[key] = result

        if not ok:
            print(f"⚠ Se ha producido un error con la entidad '{key}'.")
            if stop_on_error:
                print("⛔ Deteniendo migración por stop_on_error=True.")
                print_total_time(process_start)
                return False
            else:
                print("➡ Continuando con la siguiente entidad (stop_on_error=False).")

    # Si hemos llegado hasta aquí, hemos procesado todas las entidades habilitadas
    print_header("✅ MIGRACIÓN COMPLETADA")
    print_total_time(process_start)
    return True


if __name__ == "__main__":
    # Carpeta de logs desde el MIGRATION_CONTEXT
    log_folder = Path(MIGRATION_CONTEXT["log_folder"])
    log_folder.mkdir(parents=True, exist_ok=True)

    loc = MIGRATION_CONTEXT.get("system_key", "loc")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    base_name = f"migration_{loc}_{timestamp}"
    tmp_log_path = log_folder / f"{base_name}_RUNNING.txt"
    success_log_path = log_folder / f"{base_name}_SUCCESS.txt"
    error_log_path = log_folder / f"{base_name}_ERROR.txt"

    original_stdout = sys.stdout
    status_ok = False

    with open(tmp_log_path, "w", encoding="utf-8") as log_file:
        # Tee: consola + fichero
        sys.stdout = Tee(original_stdout, log_file)
        try:
            status_ok = bool(orchestrate())
        except Exception:
            traceback.print_exc()
            status_ok = False
        finally:
            # Restaurar stdout
            sys.stdout = original_stdout

    if status_ok:
        tmp_log_path.rename(success_log_path)
        print(f"[LOG] Log guardado en: {success_log_path}")
    else:
        tmp_log_path.rename(error_log_path)
        print(f"[LOG] Log guardado en: {error_log_path}")
        
    def play_success_sound():
        try:
            import winsound
            winsound.Beep(1200, 300)
            winsound.Beep(1500, 300)
        except Exception:
            # fallback portátil
            print('\a')


    def play_error_sound():
        try:
            import winsound
            winsound.Beep(400, 800)
        except Exception:
            print('\a')


    # Al final del orquestador
    if __name__ == "__main__":
        try:
            main()
            play_success_sound()
        except Exception:
            play_error_sound()
            raise
