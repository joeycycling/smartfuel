"""
prefs_loader.py
Lee y parsea las respuestas del Google Form de preferencias (exportado como CSV
o vía Google Sheets API — misma estructura de columnas).

Maneja el caso de campos de casillas múltiples (checkboxes) donde una opción
puede contener comas dentro de su propio texto (ej. "Embutidos (jamón,
salchicha, salami)"), por lo que NO se puede hacer un split(",") simple.
"""
import csv
import io
import re
import urllib.request
from datetime import datetime


def parse_height_to_cm(raw):
    """
    Convierte una altura en formato pies/pulgadas (ej. "5'11", 5'11"",
    "5 11", "5.11", "5-11") a centímetros. Si solo hay un número, se
    asume que son pies enteros (ej. "6" -> 6 pies 0 pulgadas).
    Devuelve None si no se puede parsear.
    """
    if not raw:
        return None
    numbers = re.findall(r"\d+", raw)
    if not numbers:
        return None
    feet = int(numbers[0])
    inches = int(numbers[1]) if len(numbers) > 1 else 0
    return round((feet * 12 + inches) * 2.54, 1)


def parse_free_text_list(raw):
    """
    Convierte un campo de texto libre con varios alimentos separados por
    coma (ej. "tilapia, atún, quinoa") en una lista de términos limpios,
    para poder excluirlos uno por uno (antes se comparaba el string
    completo como si fuera un solo término).
    """
    if not raw:
        return []
    return [term.strip() for term in raw.replace(" y ", ",").split(",") if term.strip()]


def parse_manual_date(raw):
    """
    Parsea la fecha de arranque manual del sheet, probando los formatos
    más comunes (MM/DD/YYYY, DD/MM/YYYY, YYYY-MM-DD). Devuelve un date
    o None si no se puede parsear.
    """
    if not raw:
        return None
    raw = raw.strip()
    formats = ["%m/%d/%Y", "%d/%m/%Y", "%Y-%m-%d", "%m/%d/%y", "%d/%m/%y"]
    for fmt in formats:
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def parse_timestamp_date(raw):
    """
    Extrae solo la fecha del Timestamp automático de Google Forms
    (ej. "7/6/2026 20:48:23" -> date(2026, 7, 6)). Se usa como fallback
    de fecha_inicio cuando no hay fecha de arranque manual — es más
    preciso que "hoy", porque refleja cuándo el atleta llenó el form.
    """
    if not raw:
        return None
    date_part = raw.strip().split(" ")[0]
    for fmt in ["%m/%d/%Y", "%d/%m/%Y", "%Y-%m-%d"]:
        try:
            return datetime.strptime(date_part, fmt).date()
        except ValueError:
            continue
    return None

# Listas de opciones conocidas por pregunta, en el mismo texto exacto
# que aparece en el form. El orden importa: opciones más largas primero,
# para evitar que una opción corta (ej. "Pavo") se detecte dentro de otra
# más larga por error de substring.
KNOWN_OPTIONS = {
    "deportes": ["Ciclismo", "Running", "Natación", "Gimnasio", "GYM"],
    "alergias": ["Lactosa", "Gluten", "Mariscos", "Frutos secos", "Huevo", "Ninguna"],
    "proteinas": [
        "Embutidos (jamón, salchicha, salami)",
        "Salmón / pescado",
        "Camarones / mariscos",
        "Pollo", "Res", "Cerdo", "Huevos", "Atún", "Pavo",
    ],
    "carbohidratos": [
        "Arroz blanco", "Arroz integral", "Guineo / plátano",
        "Batata", "Papa", "Yuca", "Avena", "Pasta", "Pan", "Tortilla", "Quinoa",
    ],
    "lacteos": [
        "Queso feta", "Queso ricotta", "Queso de freír",
        "Yogurt griego", "Leche de almendra", "Leche regular", "Ninguno",
    ],
    "frutas": [
        "Fresas", "Blueberries", "Uvas", "Mandarina", "Piña", "Melón",
        "Guineo", "Kiwi", "Sandía", "Lechoza", "Mango", "Guayaba", "Naranja",
    ],
    "restaurantes": [
        "Pica pollo", "Chicharrón de pollo", "Subway", "McDonald's", "KFC",
        "Pollo a la brasa", "Otro",
    ],
}

# Mapeo encabezado exacto del CSV -> nombre interno de campo
HEADER_MAP = {
    "Timestamp": "timestamp",
    "Nombre Completo": "nombre",
    "Email": "email",
    "País/ciudad de residencia": "pais_ciudad",
    "¿Entrenas con medidor de potencia?": "tiene_potometro",
    "¿Que deportes practicas?": "deportes",
    "¿Cual es tu horario de entreno?": "horario_entreno",
    "¿Qué tan sedentario o activo es tu día fuera del entreno?": "actividad_diaria",
    "¿Tienes alguna alergia o intolerancia alimenticia?": "alergias",
    "¿Sigues alguna dieta particular?": "dieta_especial",
    "¿Hay alimentos que NO consumes por preferencia personal?": "alimentos_evitar",
    "¿Qué proteínas sí comes?": "proteinas_preferidas",
    "¿Qué carbohidratos prefieres?": "carbs_preferidos",
    "¿Qué lácteos consumes?": "lacteos_consume",
    "¿Cuáles son tus frutas favoritas?": "frutas_preferidas",
    "¿Consumes alcohol regularmente?": "consume_alcohol",
    "¿Prefieres variedad en tus comidas o repetir lo mismo varios días?": "prefiere_variedad",
    "¿Usas proteína en polvo?": "usa_proteina_polvo",
    "¿Usas isotónico o bebida deportiva específica?": "usa_isotonico",
    "¿Cuántas comidas prefieres al día?": "comidas_por_dia",
    "¿Cocinas tú o alguien cocina por ti?": "cocina_propia",
    "¿Cuánto tiempo tienes disponible para preparar tus comidas en un día típico?": "tiempo_prep",
    "¿Qué restaurantes o cadenas de comida rápida frecuentas?": "restaurantes_frecuentes",
    "¿Qué sueles pedir en esos lugares?": "pedidos_habituales",
    "¿Hay algún restaurante que definitivamente evitas?": "restaurantes_evitar",
    "¿Hay algo más sobre tu alimentación o relación con la comida que el coach deba saber?": "notas_adicionales",
    "Objetivo": "objetivo",  # bajar de peso / mantenimiento / aumento de masa muscular
    "ID_Atleta": "id_atleta",  # columna manual que agrega el coach
}

MULTISELECT_FIELDS = {
    "deportes": "deportes",
    "alergias": "alergias",
    "proteinas_preferidas": "proteinas",
    "carbs_preferidos": "carbohidratos",
    "lacteos_consume": "lacteos",
    "frutas_preferidas": "frutas",
    "restaurantes_frecuentes": "restaurantes",
}


def parse_multiselect(raw_text, option_key):
    """
    Detecta qué opciones conocidas aparecen en el texto crudo del checkbox,
    en vez de hacer split(",") (que rompería opciones con comas internas).
    Si queda texto libre sin match (ej. respuesta de "Otro"), se agrega
    tal cual con el prefijo "Otro: " en vez de perderse.
    """
    if not raw_text:
        return []
    options = sorted(KNOWN_OPTIONS[option_key], key=len, reverse=True)
    remaining = raw_text
    found = []
    for opt in options:
        if opt in remaining:
            found.append(opt)
            remaining = remaining.replace(opt, "")

    leftover = remaining.strip(" ,").strip()
    if leftover:
        found.append(f"Otro: {leftover}")

    return found


def normalize_header(header):
    """
    Convierte un encabezado de columna del CSV a su nombre interno de campo.
    Usa el mapeo exacto cuando existe; para las preguntas de marca y el ID
    de TrainingPeaks detecta por palabra clave, así no depende del texto
    exacto que se haya usado al redactarlas/nombrarlas en el sheet.
    """
    if header in HEADER_MAP:
        return HEADER_MAP[header]

    h = header.lower()

    if "trainingpeaks" in h and "id" in h:
        return "id_atleta"

    if "marca" in h or h.startswith("si respondiste"):
        if "prote" in h:
            return "marca_proteina_polvo"
        if "isot" in h or "deportiva" in h:
            return "marca_isotonico"

    if "altura" in h or "estatura" in h or ("height" in h):
        return "altura_cm"

    if "peso" in h:
        return "peso_inicial_lb"

    if "fecha" in h and ("arranque" in h or "inicio" in h):
        return "fecha_inicio_manual"

    return header


def fetch_preferences_csv(csv_url):
    """
    Descarga el CSV publicado del Google Form/Sheet en vivo y devuelve
    la lista de preferencias ya parseadas (mismo formato que
    load_preferences_from_csv).
    """
    with urllib.request.urlopen(csv_url, timeout=15) as response:
        raw = response.read().decode("utf-8")
    return load_preferences_from_csv(raw)


def load_preferences_from_csv(csv_text):
    """
    csv_text: contenido crudo del CSV publicado del Google Form.
    Devuelve una lista de dicts, uno por atleta (una fila = una respuesta).
    """
    reader = csv.DictReader(io.StringIO(csv_text))
    results = []
    for row in reader:
        parsed = {}
        for header, value in row.items():
            field = normalize_header(header)
            parsed[field] = value

        for internal_field, option_key in MULTISELECT_FIELDS.items():
            raw = parsed.get(internal_field, "")
            parsed[internal_field] = parse_multiselect(raw, option_key)

        parsed["tiene_potometro"] = parsed.get("tiene_potometro", "").strip().lower() == "si"
        parsed["usa_proteina_polvo"] = parsed.get("usa_proteina_polvo", "").strip().lower() == "si"
        parsed["usa_isotonico"] = parsed.get("usa_isotonico", "").strip().lower() == "si"
        parsed["altura_cm"] = parse_height_to_cm(parsed.get("altura_cm"))
        parsed["fecha_inicio_manual"] = parse_manual_date(parsed.get("fecha_inicio_manual"))
        parsed["fecha_inicio_timestamp"] = parse_timestamp_date(parsed.get("timestamp"))
        parsed["alimentos_evitar"] = parse_free_text_list(parsed.get("alimentos_evitar"))
        try:
            parsed["peso_inicial_lb"] = float(parsed.get("peso_inicial_lb")) if parsed.get("peso_inicial_lb") else None
        except ValueError:
            parsed["peso_inicial_lb"] = None

        results.append(parsed)
    return results
