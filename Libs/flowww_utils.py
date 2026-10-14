import pandas as pd
import re
import html
import unicodedata
import os
import base64

# =====================================================
# DICCIONARIO CANÓNICO DE CAMPOS (ES / EN / MIXTO)
# =====================================================
FIELD_SYNONYMS = {
    # IDENTIDAD
    "client_id": ["client id", "id cliente", "id", "codigo cliente"],
    "first_name": ["first name", "nombre", "name"],
    "last_name": ["last name", "surname", "apellidos", "apellido"],
    "dni": ["dni", "nif", "documento", "document", "custom fields"],

    # CONTACTO
    "email": ["email", "e-mail", "correo", "mail"],
    "mobile": ["mobile", "movil", "móvil", "cell", "telefono movil"],
    "phone": ["phone", "telefono", "tel", "fijo"],

    # FECHAS
    "birth_date": ["birth", "dob", "fecha nacimiento", "nacimiento"],
    "created_date": ["created", "creation", "alta", "fecha alta"],

    # SEXO
    "gender": ["gender", "sexo"],

    # DIRECCIÓN
    "street": ["street", "address", "direccion", "dirección"],
    "city": ["city", "poblacion", "población", "municipio"],
    "province": ["province", "state", "provincia"],
    "postal_code": ["post code", "postcode", "postal code", "cp", "codigo postal"],
    "country": ["country", "pais", "país"],
}

# =====================================================
# HELPERS DE TEXTO
# =====================================================
def normalizar_header(h: str) -> str:
    h = unicodedata.normalize("NFD", str(h)).encode("ascii", "ignore").decode()
    h = h.lower()
    for ch in ["_", "-", ".", "/", "\\", ":", ";", "(", ")", "[", "]"]:
        h = h.replace(ch, " ")
    return " ".join(h.split())

def detectar_columna(df: pd.DataFrame, synonyms: list[str]) -> str | None:
    headers_norm = {normalizar_header(c): c for c in df.columns}
    for syn in synonyms:
        syn_norm = normalizar_header(syn)
        for h_norm, real in headers_norm.items():
            if syn_norm and syn_norm in h_norm:
                return real
    return None

def detectar_campo(df: pd.DataFrame, field_key: str) -> str | None:
    candidates = []
    for syn in FIELD_SYNONYMS.get(field_key, []):
        col = detectar_columna(df, [syn])
        if col:
            candidates.append(col)

    if not candidates:
        return None

    # 🔴 PARCHE GENÉRICO: email real > flags marketing
    if field_key == "email":
        for c in candidates:
            cn = c.lower()
            if not any(x in cn for x in ["opt", "marketing", "consent"]):
                return c

    return candidates[0]


# =====================================================
# LECTURA FLEXIBLE
# =====================================================
def leer_archivo_flexible(path: str) -> pd.DataFrame:
    ext = path.lower().split(".")[-1]

    try:
        with open(path, "rb") as f:
            head = f.read(2048).lstrip().lower()
        if head.startswith(b"<html") or b"<table" in head:
            tablas = pd.read_html(path)
            return max(tablas, key=lambda d: d.size).fillna("")
    except Exception:
        pass

    if ext == "csv":
        for sep in [",", ";"]:
            try:
                return pd.read_csv(
                    path, sep=sep, dtype=str, encoding="utf-8-sig", engine="python"
                ).fillna("")
            except Exception:
                pass
        return pd.read_csv(path, sep=None, dtype=str, engine="python").fillna("")

    return pd.read_excel(path, dtype=str).fillna("")

# =====================================================
# LIMPIEZAS
# =====================================================
def limpiar_texto(s) -> str:
    s = "" if s is None else str(s).strip()
    return "" if s.lower() in ("nan", "none", "null") else s

def limpiar_telefono(s) -> str:
    s = limpiar_texto(s)
    for ch in [" ", "-", ".", "(", ")", "+"]:
        s = s.replace(ch, "")
    return s

def normalizar_fecha_yyyy_mm_dd(s) -> str:
    s = limpiar_texto(s)
    dt = pd.to_datetime(s, errors="coerce", dayfirst=True)
    return "" if pd.isna(dt) else dt.strftime("%Y-%m-%d")

_email_re = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
def normalizar_email(s) -> str:
    s = limpiar_texto(s).lower().replace(" ", "")
    return s if s and _email_re.match(s) else ""

def normalizar_sexo_explicito(s) -> str:
    s = limpiar_texto(s).lower()
    if s in ("f", "female", "mujer", "femenino"):
        return "F"
    if s in ("m", "male", "hombre", "masculino"):
        return "M"
    return ""

def separar_apellidos(last_name: str) -> tuple[str, str]:
    t = limpiar_texto(last_name).split()
    if not t:
        return "", ""
    if len(t) == 1:
        return t[0], ""
    return t[0], " ".join(t[1:])

import re

def extraer_dni(texto):
    """
    Extrae DNI, NIE, CIF, pasaportes y documentos extranjeros.

    Ejemplos:
    - DNI: 52593565V
    - NIE: X6152682K
    - Documento extranjero: YA9821028
    - Documento extranjero: Y80118137F
    - CIF/documento: E2412267
    """
    s = limpiar_texto(texto).upper()
    if s == "":
        return ""

    patrones = [
        r"\b[XYZ]\d{7,8}[A-Z]\b",             # NIE estándar o tipo NIE largo
        r"\b\d{8}[A-Z]\b",                    # DNI estándar
        r"\b\d{7}[A-Z]\b",                    # DNI con 7 dígitos
        r"\b[A-Z]{1,3}\d{5,9}[A-Z0-9]?\b",    # Pasaportes/docs extranjeros
        r"\b\d{6,12}\b",                      # Documentos solo numéricos
    ]

    for patron in patrones:
        m = re.search(patron, s)
        if m:
            return m.group(0)

    return ""


def clean_text_for_flowww_safe(
    text: str,
    *,
    ascii_only: bool = True,
    strip_html: bool = False,
    keep_line_sep: str = " | "
) -> str:
    """
    Limpieza genérica segura para textos Flowww:
    - decodifica HTML
    - limpia caracteres raros
    - normaliza espacios
    - opcionalmente fuerza ASCII
    """
    if text is None:
        return ""

    s = str(text)
    s = html.unescape(s)

    try:
        if any(ch in s for ch in ("Ã", "Â", "ï¿½", "�")):
            s2 = s.encode("latin1", errors="ignore").decode("utf-8", errors="ignore")
            if s2 and len(s2) >= max(1, len(s) // 3):
                s = s2
    except Exception:
        pass

    s = re.sub(r"<\s*br\s*/?>", keep_line_sep, s, flags=re.IGNORECASE)
    if strip_html:
        s = re.sub(r"<[^>]+>", "", s)

    s = re.sub(r"[\t\r\n]+", keep_line_sep, s)
    s = re.sub(r"\s{2,}", " ", s).strip()

    if ascii_only:
        s = unicodedata.normalize("NFD", s)
        s = s.encode("ascii", "ignore").decode("ascii")

    return s.strip(" |").strip()


def normalizar_timestamp_yyyymmddhhmmss(s: str) -> str:
    """
    Normaliza fechas/horas a formatos Flowww-friendly:
    - admite timestamps, fechas y strings
    - devuelve string limpio o vacío
    """
    if s is None or str(s).strip() == "":
        return ""

    try:
        dt = pd.to_datetime(s, errors="coerce", dayfirst=True)
        if pd.isna(dt):
            return ""
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return ""

def decodificar_base64_legible(s: str) -> str:
    """
    Intenta decodificar strings base64 cortos y legibles.
    Si no es base64 válido o no tiene sentido, devuelve el original.
    """
    s = limpiar_texto(s)

    if not s or len(s) > 12:
        return s

    try:
        decoded = base64.b64decode(s).decode("utf-8").strip()
    except Exception:
        return s

    if (
        1 <= len(decoded) <= 10
        and all(c.isalpha() or c in " ÁÉÍÓÚÑáéíóúñ" for c in decoded)
    ):
        return decoded.upper()

    return s

# =====================================================
# UTILIDADES
# =====================================================
def col(df: pd.DataFrame, name: str) -> pd.Series:
    """
    Devuelve df[name] si existe; si no, una Serie vacía alineada al índice.
    (Compatibilidad con scripts antiguos)
    """
    if name in df.columns:
        return df[name]
    return pd.Series([""] * len(df), index=df.index)


# =====================================================
# MAPEOS GENÉRICOS
# =====================================================
def mapear_identidad_generico(df_origen, df_final):
    used_cols = set()

    col_id = detectar_campo(df_origen, "client_id")
    if "ClientID" in df_final.columns and col_id:
        df_final["ClientID"] = df_origen[col_id].map(limpiar_texto)
        used_cols.add(col_id)

    col_name = detectar_campo(df_origen, "first_name")
    if "ClientName" in df_final.columns and col_name:
        df_final["ClientName"] = df_origen[col_name].map(limpiar_texto)
        used_cols.add(col_name)

    col_last = detectar_campo(df_origen, "last_name")
    if col_last:
        ap = df_origen[col_last].map(limpiar_texto).apply(separar_apellidos)

        if "ClientSurname1" in df_final.columns:
            df_final["ClientSurname1"] = ap.apply(lambda x: x[0])
        if "ClientSurname2" in df_final.columns:
            df_final["ClientSurname2"] = ap.apply(lambda x: x[1])

        used_cols.add(col_last)

    col_dni = detectar_campo(df_origen, "dni")
    if "ClientNIF" in df_final.columns and col_dni:
        df_final["ClientNIF"] = df_origen[col_dni].map(extraer_dni)
        used_cols.add(col_dni)

    return used_cols


def mapear_contacto_generico(df_origen, df_final):
    used_cols = set()

    col_email = detectar_campo(df_origen, "email")
    if "ClientEMail" in df_final.columns and col_email:
        df_final["ClientEMail"] = df_origen[col_email].map(normalizar_email)
        used_cols.add(col_email)

    col_mobile = detectar_campo(df_origen, "mobile")
    if "ClientPhone1" in df_final.columns and col_mobile:
        df_final["ClientPhone1"] = df_origen[col_mobile].map(limpiar_telefono)
        used_cols.add(col_mobile)

    col_phone = detectar_campo(df_origen, "phone")
    if "ClientPhone2" in df_final.columns and col_phone:
        df_final["ClientPhone2"] = df_origen[col_phone].map(limpiar_telefono)
        used_cols.add(col_phone)

    return used_cols


def mapear_fechas_y_sexo_generico(df_origen, df_final):
    used_cols = set()

    col_birth = detectar_campo(df_origen, "birth_date")
    if "ClientBirthDate" in df_final.columns and col_birth:
        df_final["ClientBirthDate"] = df_origen[col_birth].map(normalizar_fecha_yyyy_mm_dd)
        used_cols.add(col_birth)

    col_created = detectar_campo(df_origen, "created_date")
    if "ClientDate" in df_final.columns and col_created:
        df_final["ClientDate"] = df_origen[col_created].map(normalizar_fecha_yyyy_mm_dd)
        used_cols.add(col_created)

    col_gender = detectar_campo(df_origen, "gender")
    if "ClientSex" in df_final.columns and col_gender:
        df_final["ClientSex"] = df_origen[col_gender].map(normalizar_sexo_explicito)
        used_cols.add(col_gender)

    # fallback Flowww (no consume columna nueva)
    if "ClientSex" in df_final.columns:
        df_final["ClientSex"] = df_final["ClientSex"].astype(str).str.strip()
        df_final.loc[df_final["ClientSex"].eq(""), "ClientSex"] = "F"

    return used_cols


def mapear_direccion_generico(df_origen, df_final):
    used_cols = set()

    col_street = detectar_campo(df_origen, "street")
    col_city   = detectar_campo(df_origen, "city")
    col_prov   = detectar_campo(df_origen, "province")
    col_cp     = detectar_campo(df_origen, "postal_code")
    col_ctry   = detectar_campo(df_origen, "country")

    if "ClientAddress" in df_final.columns and col_street:
        df_final["ClientAddress"] = df_origen[col_street].map(limpiar_texto)
        used_cols.add(col_street)

    if "ClientCity" in df_final.columns and col_city:
        df_final["ClientCity"] = df_origen[col_city].map(limpiar_texto)
        used_cols.add(col_city)

    if "ClientProvince" in df_final.columns and col_prov:
        df_final["ClientProvince"] = df_origen[col_prov].map(limpiar_texto)
        used_cols.add(col_prov)

    if col_cp:
        if "ClientPostCosde" in df_final.columns:
            df_final["ClientPostCosde"] = df_origen[col_cp].map(limpiar_texto)
            used_cols.add(col_cp)
        if "ClientPostCode" in df_final.columns:
            df_final["ClientPostCode"] = df_origen[col_cp].map(limpiar_texto)
            used_cols.add(col_cp)

    if "ClientCountry" in df_final.columns and col_ctry:
        df_final["ClientCountry"] = df_origen[col_ctry].map(limpiar_texto)
        used_cols.add(col_ctry)

    return used_cols


# =====================================================
# ACTIVE / INACTIVE
# =====================================================
def detectar_active_series(df_origen):
    posibles = ["inactive/active", "active/inactive", "active", "inactive", "status", "estado"]
    true_values = {"1", "true", "yes", "y", "activo", "active", "on"}

    for col_name in df_origen.columns:
        col_norm = col_name.lower()
        if any(p in col_norm for p in posibles):
            return (
                df_origen[col_name]
                .astype(str).str.strip().str.lower()
                .isin(true_values)
            )
    return None

# =====================================================
# DEDUP + AUDITORÍA (IGUAL QUE ANTES)
# =====================================================
def dedup_por_claves(
    df: pd.DataFrame,
    *,
    subset: list[str],
    fecha_col: str | None,
    active_series: pd.Series | None = None,
    stable_tiebreak_cols: list[str] | None = None,
):
    stable_tiebreak_cols = stable_tiebreak_cols or []

    mask_completo = df[subset].apply(
        lambda r: all(str(x).strip() != "" for x in r),
        axis=1
    )

    df_base = df.loc[mask_completo].copy()
    df_rest = df.loc[~mask_completo].copy()

    if active_series is not None:
        df_base["_is_active"] = active_series.reindex(df_base.index).fillna(False)
    else:
        df_base["_is_active"] = False

    if fecha_col and fecha_col in df_base.columns:
        df_base["_fecha_dt"] = pd.to_datetime(df_base[fecha_col], errors="coerce", dayfirst=True)
    else:
        df_base["_fecha_dt"] = pd.NaT

    mask_dup = df_base.duplicated(subset=subset, keep=False)
    df_detected = df_base.loc[mask_dup].copy()

    sort_cols = ["_is_active", "_fecha_dt"]
    sort_asc = [False, True]

    for c in stable_tiebreak_cols:
        if c in df_base.columns:
            sort_cols.append(c)
            sort_asc.append(True)

    df_base = df_base.sort_values(sort_cols, ascending=sort_asc, kind="mergesort")

    df_keep_base = df_base.drop_duplicates(subset=subset, keep="first")
    df_removed = df_base.loc[~df_base.index.isin(df_keep_base.index)].copy()

    df_keep = pd.concat([df_rest, df_keep_base]).sort_index()

    return df_keep, df_removed, df_detected

def export_audit(df, *, reason: str, path: str, filename: str, group_by=None):
    full_path = os.path.join(path, filename)

    if df is None or df.empty:
        pd.DataFrame().to_csv(full_path, sep=";", index=False, encoding="utf-8-sig")
        return

    out = df.copy()
    out["AuditReason"] = reason

    if group_by:
        cols = [c for c in group_by if c in out.columns]
        if cols:
            out = out.sort_values(cols, kind="mergesort")

    out.to_csv(full_path, sep=";", index=False, encoding="utf-8-sig")

# =====================================================
# CONTADORES
# =====================================================
class FlowwwCounters:
    def __init__(self):
        self.total_origen = 0
        self.total_df_final_inicial = 0
        self.eliminados_insuf = 0
        self.eliminados_dni = 0
        self.eliminados_nom = 0
        self.total_final = 0
        self.total_csv_generados = 0

    @property
    def total_eliminados(self):
        return self.total_origen - self.total_final

    def print_resumen(self):
        print("\n=== RESUMEN FINAL CSV ===")
        print("📥 Total registros origen:", self.total_origen)
        print("🧱 Total construido inicial:", self.total_df_final_inicial)
        print("🗑️ Eliminados por datos insuficientes:", self.eliminados_insuf)
        print("🔁 Eliminados duplicados con DNI:", self.eliminados_dni)
        print("🔁 Eliminados duplicados nombre+fecha nac:", self.eliminados_nom)
        print("✅ TOTAL REGISTROS CSV FINAL:", self.total_final)
        print("📉 TOTAL REGISTROS ELIMINADOS:", self.total_eliminados)
        print("📦 Total CSV generados:", self.total_csv_generados)
        print("\n=== CONTEO CSV FINAL ===")
        print("✅ Filas en CSV final (post-eliminaciones):", self.total_final)


