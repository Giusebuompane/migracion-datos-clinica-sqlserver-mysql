# step04_load_data.py
import importlib
from pathlib import Path

from step01_config import MIGRATION_ENTITIES, MIGRATION_CONTEXT


def log(msg: str):
    print(msg)


def run_entity_loader(entity_key: str, entity_cfg: dict) -> bool:
    """
    Importa y ejecuta el script indicado en entity_cfg["script_file"].
    Se espera que el módulo tenga una función run(entity_config, context).
    """
    script_file = entity_cfg.get("script_file")
    if not script_file:
        log(f"❌ La entidad '{entity_key}' no tiene 'script_file' definido en MIGRATION_ENTITIES.")
        return False

    module_name = Path(script_file).stem  # "load_diary_gen.py" -> "load_diary_gen"

    try:
        module = importlib.import_module(module_name)
    except ModuleNotFoundError:
        log(f"❌ No se ha encontrado el módulo '{module_name}.py' para la entidad '{entity_key}'.")
        return False

    if not hasattr(module, "run"):
        log(f"❌ El módulo '{module_name}.py' no tiene la función run(entity_config, context).")
        return False

    try:
        log(f"▶ Ejecutando loader: {module_name}.run(...)")
        module.run(entity_cfg, MIGRATION_CONTEXT)
        log(f"✔ Loader {module_name} ejecutado correctamente.")
        return True
    except Exception as e:
        log(f"❌ Error ejecutando {module_name}.run para '{entity_key}': {e}")
        return False


def main():
    log("==== INICIO VOLCADO DE DATOS (STEP 4) ====")

    # Ordenar conceptos por 'order'
    entities_sorted = sorted(
        MIGRATION_ENTITIES.items(),
        key=lambda kv: kv[1].get("order", 9999)
    )

    for key, cfg in entities_sorted:
        label = cfg.get("label", key)

        if not cfg.get("enabled", False):
            log(f"⏭ {key} ({label}) está deshabilitado (enabled=False). Se omite.")
            continue

        log("")
        log(f"=== Procesando entidad: {key} ({label}) ===")

        ok = run_entity_loader(key, cfg)
        if not ok:
            log(f"⚠ Se ha producido un error con la entidad '{key}'.")
            # Si quieres parar en el primer error, descomenta:
            # break

    log("")
    log("==== FIN VOLCADO DE DATOS (STEP 4) ====")


if __name__ == "__main__":
    main()
