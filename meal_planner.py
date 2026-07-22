"""
meal_planner.py
Distribución diaria de kcal + selección/escalado de comidas dentro de un margen.
"""
import random
import json
import os
from food_db import scale_food, by_category, get
from phase_engine import classify_day_type

MARGIN_KCAL = 150
MAX_ATTEMPTS = 5
EQUIVALENCIA_MAX_DIF = 200  # diferencia máxima aceptable de kcal entre Opción A y B
SCALE_MIN, SCALE_MAX = 0.5, 2.2
PROTEIN_SCALE_MAX = 3.5  # tope propio de proteína — más alto para nunca cortar el piso
PROTEIN_MAX_GRAMOS_PORCION = 320  # tope absoluto — nunca una sola porción más grande que esto
CARB_SCALE_MAX = 3.0     # tope propio de carb — absorbe más del hueco antes de recurrir a grasa
CARB_SCALE_MAX_ALTA_DEMANDA = 4.5  # días clave/fondo: el carb absorbe TODO antes que usar grasa

# reparto simple de kcal/proteína entre comidas del día (ajustable)
MEAL_SPLIT = {"desayuno": 0.25, "almuerzo": 0.35, "merienda": 0.10, "cena": 0.30}

# Matriz de combinaciones aprobadas por el coach (proteína -> carbs compatibles).
# Generada desde el Excel que Joey marca a mano — si una proteína no aparece
# ahí, no se restringe (se permite cualquier carb de su categoría).
COMBINACIONES_PATH = os.path.join(os.path.dirname(__file__), "data", "combinaciones.json")
try:
    with open(COMBINACIONES_PATH, encoding="utf-8") as f:
        COMBINACIONES = json.load(f)
except FileNotFoundError:
    COMBINACIONES = {}

# Regla especial: las legumbres/habichuelas NUNCA se eligen como el carb
# principal — solo como acompañante fijo cuando el carb principal es arroz
# blanco (ej. 150g arroz + 60g habichuelas + proteína), igual que en la vida real.
HABICHUELAS_NOMBRE = "legumbres/habichuelas cocidas"
ARROZ_BLANCO_NOMBRE = "arroz blanco cocido"
HABICHUELAS_SIDE_G = 60

# Carbs tipo pan/víveres de panadería — cuando el carb principal es uno de
# estos, se prefiere queso como extra en vez de aceite/aguacate.
# Prioridad de selección de proteína (pescado > pollo > pavo > res magra >
# huevos > procesados) — no prohíbe procesados, pero los hace mucho menos
# frecuentes en el azar, favoreciendo fuentes frescas.
# Nivel de costo por proteína — las Opciones A/B siguen siendo económicas
# por defecto; el nivel premium se usa solo para la nueva Opción Premium.
PROTEINA_COSTO = {
    "pechuga de pollo horneada": "economico", "huevo grande": "economico",
    "jamón de pavo": "economico", "salchicha de pollo (bravo)": "economico",
    "salami dominicano (frito)": "economico", "atún en agua enlatado (escurrido)": "economico",
    "pavo molido (cocido)": "economico",
    "carne molida de res (95/5)": "balanceado", "filete de cerdo horneado": "balanceado",
    "tilapia (cocida)": "balanceado",
    "salmón horneado": "premium", "camarones (cocidos)": "premium", "mero/basa horneado": "premium",
}
CARB_COSTO = {
    "quinoa cocida": "premium",
    "arroz integral cocido": "balanceado",
}
COSTO_DEFAULT_CARB = "economico"


def _costo_proteina(nombre):
    return PROTEINA_COSTO.get(nombre.lower(), "balanceado")


def _costo_carb(nombre):
    return CARB_COSTO.get(nombre.lower(), COSTO_DEFAULT_CARB)


PROTEINA_PESO_PRIORIDAD = {
    "tilapia (cocida)": 5, "salmón horneado": 5, "camarones (cocidos)": 5,
    "mero/basa horneado": 5, "atún en agua enlatado (escurrido)": 5,
    "pechuga de pollo horneada": 4,
    "pavo molido (cocido)": 3,
    "carne molida de res (95/5)": 2, "filete de cerdo horneado": 2,
    "huevo grande": 2,
    "jamón de pavo": 1, "salchicha de pollo (bravo)": 1, "salami dominicano (frito)": 1,
}
PROTEINA_PESO_DEFAULT = 3


def _elegir_proteina_priorizada(candidatos):
    pesos = [PROTEINA_PESO_PRIORIDAD.get(c["nombre"].lower(), PROTEINA_PESO_DEFAULT) for c in candidatos]
    return random.choices(candidatos, weights=pesos, k=1)[0]


CARBS_TIPO_PAN = {
    "pan integral", "pan nature's own (thick cut)", "bagel mini (mitad)",
    "tortilla maria estilo burrito", "corn flakes",
}

# Mapa de qué alimentos aplican a qué comida del día (desayuno/almuerzo/cena),
# marcado por el coach. Si un alimento no aparece aquí, se permite en
# cualquier comida por defecto (ej. frutas, restaurante, suplementos).
ALIMENTOS_POR_COMIDA_PATH = os.path.join(os.path.dirname(__file__), "data", "alimentos_por_comida.json")
try:
    with open(ALIMENTOS_POR_COMIDA_PATH, encoding="utf-8") as f:
        ALIMENTOS_POR_COMIDA = json.load(f)
except FileNotFoundError:
    ALIMENTOS_POR_COMIDA = {}

# Platos compuestos (recetas completas con macros ya calculados) — se usan
# como una TERCERA opción posible en almuerzo/cena, junto a las combinaciones
# simples de proteína+carb. No las reemplazan.
PLATOS_PATH = os.path.join(os.path.dirname(__file__), "data", "platos_compuestos.json")
try:
    with open(PLATOS_PATH, encoding="utf-8") as f:
        PLATOS_COMPUESTOS = json.load(f)
except FileNotFoundError:
    PLATOS_COMPUESTOS = []

PLATO_SCALE_MIN, PLATO_SCALE_MAX = 0.6, 1.6
PROB_PLATO_COMPUESTO = 0.4  # probabilidad de que la Opción B sea un plato compuesto


def build_daily_targets(daily_burn, weekly_avg_kcal):
    """
    daily_burn: {dia: kcal_quemadas_ese_dia}
    Redistribuye el promedio semanal según el gasto relativo de cada día.
    """
    avg_daily_burn = sum(daily_burn.values()) / len(daily_burn)
    return {
        day: round(weekly_avg_kcal + (burn - avg_daily_burn))
        for day, burn in daily_burn.items()
    }


def _pick_candidates(db, categoria, prefs, slot=None):
    """Filtra alimentos de una categoría respetando preferencias/alergias del atleta
    y la comida del día (si el alimento tiene reglas marcadas en la bitácora)."""
    candidates = by_category(db, categoria)
    excluded = set(x.lower() for x in prefs.get("alimentos_evitar", []))
    allergens = set(x.lower() for x in prefs.get("alergias", []))
    result = [
        c for c in candidates
        if not any(e in c["nombre"].lower() for e in excluded if e)
        and not any(a in c["nombre"].lower() for a in allergens if a)
    ]
    if slot:
        result = [
            c for c in result
            if slot in ALIMENTOS_POR_COMIDA.get(c["nombre"].lower(), [slot])
        ]
    return result


def _clamp_scale(amount, base_amount):
    if base_amount == 0:
        return 0
    factor = amount / base_amount
    factor = max(SCALE_MIN, min(SCALE_MAX, factor))
    return round(base_amount * factor, 1)


EXTRA_SCALE_MIN, EXTRA_SCALE_MAX = 0.05, 1.2


def _clamp_scale_extra(amount, base_amount):
    """
    Clamp separado para el componente "extra" (grasa saludable/lácteo que
    se agrega para llenar kcal faltantes). Usa un rango mucho más bajo
    que _clamp_scale porque son toppings (ej. aguacate, aceite), no una
    porción completa — sin esto, alimentos muy densos en kcal (aceite,
    aguacate) terminaban forzados a un mínimo irreal (ej. 50ml de aceite).
    """
    if base_amount == 0:
        return 0
    factor = amount / base_amount
    factor = max(EXTRA_SCALE_MIN, min(EXTRA_SCALE_MAX, factor))
    return round(base_amount * factor, 1)


def build_meal(categoria_proteina, categoria_carb, target_kcal, target_protein_g, db, prefs,
                exclude_names=None, slot=None, dia_alta_demanda=False):
    """
    Arma una comida simple (proteína + carb), escalando cantidades para
    acercarse al target de kcal/proteína de ese slot.
    exclude_names: set opcional de nombres a evitar (para generar una
    segunda opción distinta a la primera).
    slot: "desayuno"/"almuerzo"/"cena" — filtra alimentos según la bitácora
    de qué aplica a qué comida (ej. no carne molida en desayuno).
    dia_alta_demanda: True en días clave/fondo — evita usar grasa como
    relleno de kcal (deja el carb absorber más) para favorecer la
    reposición de glucógeno y no concentrar grasa en días de mucho volumen.
    """
    exclude_names = exclude_names or set()

    proteinas = _pick_candidates(db, categoria_proteina, prefs, slot=slot)
    proteinas_libres = [p for p in proteinas if p["nombre"] not in exclude_names] or proteinas
    carbs = _pick_candidates(db, categoria_carb, prefs, slot=slot)
    carbs_libres = [c for c in carbs if c["nombre"] not in exclude_names] or carbs

    if not proteinas_libres or not carbs_libres:
        return None

    proteina = _elegir_proteina_priorizada(proteinas_libres)

    # Filtrar carbs por la matriz de combinaciones aprobadas para esta proteína
    # (si no hay entrada para esta proteína en la matriz, no se restringe).
    compatibles = COMBINACIONES.get(proteina["nombre"].lower())
    carbs_candidatos = carbs_libres
    if compatibles:
        filtrados = [c for c in carbs_libres if c["nombre"].lower() in compatibles]
        carbs_candidatos = filtrados or carbs_libres

    # Las habichuelas/legumbres nunca son el carb principal — solo acompañante del arroz.
    solo_no_habichuelas = [c for c in carbs_candidatos if c["nombre"].lower() != HABICHUELAS_NOMBRE]
    carbs_candidatos = solo_no_habichuelas or carbs_candidatos

    carb = random.choice(carbs_candidatos)

    protein_amount = (target_protein_g / proteina["proteina_g"]) * proteina["cantidad_base"] \
        if proteina["proteina_g"] else proteina["cantidad_base"]
    # La proteína tiene su propio tope (más alto que el de carbs) y NUNCA se
    # recorta por debajo de lo que hace falta para el piso — antes el mismo
    # tope de 2.2x que se usa para carbs cortaba la proteína antes de llegar
    # al objetivo en días de piso alto, causando déficit real de proteína.
    protein_amount = max(protein_amount, proteina["cantidad_base"] * SCALE_MIN)
    protein_amount = min(protein_amount, proteina["cantidad_base"] * PROTEIN_SCALE_MAX)
    if proteina["unidad_medida"] == "gramos":
        protein_amount = min(protein_amount, PROTEIN_MAX_GRAMOS_PORCION)
    proteina_scaled = scale_food(proteina, protein_amount)

    remaining_kcal = max(target_kcal - proteina_scaled["kcal"], 0)
    carb_amount = (remaining_kcal / carb["kcal"]) * carb["cantidad_base"] if carb["kcal"] else 0
    carb_amount = max(carb_amount, carb["cantidad_base"] * SCALE_MIN)
    carb_cap = CARB_SCALE_MAX_ALTA_DEMANDA if dia_alta_demanda else CARB_SCALE_MAX
    carb_amount = min(carb_amount, carb["cantidad_base"] * carb_cap)
    carb_scaled = scale_food(carb, carb_amount)

    componentes = [proteina_scaled, carb_scaled]
    total_kcal = proteina_scaled["kcal"] + carb_scaled["kcal"]

    # Habichuelas/legumbres como acompañante fijo del arroz blanco (nunca solas),
    # solo si esa combinación está aprobada para esta proteína.
    if carb["nombre"].lower() == ARROZ_BLANCO_NOMBRE and (not compatibles or HABICHUELAS_NOMBRE in compatibles):
        habichuelas = get(db, HABICHUELAS_NOMBRE)
        if habichuelas:
            habichuelas_scaled = scale_food(habichuelas, HABICHUELAS_SIDE_G)
            componentes.append(habichuelas_scaled)
            total_kcal += habichuelas_scaled["kcal"]

    # Si aún falta bastante (ej. días de fondo largo), agregar un tercer
    # componente. Si el carb principal es tipo pan/tortilla (víveres de
    # panadería), preferir queso (lácteo) antes que aceite/aguacate — es
    # una combinación más natural y menos densa en grasa por bocado.
    # En días de alta demanda (clave/fondo) NUNCA se usa grasa como relleno
    # — se prioriza reponer glucógeno, no concentrar grasa.
    still_missing = target_kcal - total_kcal
    if still_missing > MARGIN_KCAL:
        if dia_alta_demanda:
            extras = _pick_candidates(db, "carbohidrato", prefs, slot=slot)
            extras = [e for e in extras if e["nombre"] != carb["nombre"]] or extras
        elif carb["nombre"].lower() in CARBS_TIPO_PAN:
            extras = _pick_candidates(db, "lacteo", prefs, slot=slot) or _pick_candidates(db, "grasa_saludable", prefs, slot=slot)
        else:
            extras = _pick_candidates(db, "grasa_saludable", prefs, slot=slot) or _pick_candidates(db, "lacteo", prefs, slot=slot)
        if extras:
            extra = random.choice(extras)
            extra_amount = (still_missing / extra["kcal"]) * extra["cantidad_base"] if extra["kcal"] else 0
            extra_amount = _clamp_scale_extra(extra_amount, extra["cantidad_base"])
            extra_scaled = scale_food(extra, extra_amount)
            componentes.append(extra_scaled)
            total_kcal += extra_scaled["kcal"]

    total_proteina = sum(c.get("proteina_g", 0) for c in componentes)

    return {
        "componentes": componentes,
        "kcal_total": round(total_kcal, 1),
        "proteina_g_total": round(total_proteina, 1),
    }


def _plato_permitido(plato, prefs, slot):
    if slot not in plato.get("slots", ["almuerzo", "cena"]):
        return False
    alergias = set(x.lower() for x in prefs.get("alergias", []))
    if any(a.lower() in alergias for a in plato.get("alergenos", [])):
        return False
    evitar = set(x.lower() for x in prefs.get("alimentos_evitar", []))
    nombre_lower = plato["nombre"].lower()
    if any(e and e in nombre_lower for e in evitar):
        return False
    return True


PROTEINA_KEYWORDS = (
    "pollo", "carne", "pavo", "salmón", "salmon", "camarones", "pescado",
    "cerdo", "res guisada", "res (", "atún", "tilapia", "mero", "basa",
)


def _es_ingrediente_proteina(nombre_ingrediente):
    n = nombre_ingrediente.lower()
    return any(k in n for k in PROTEINA_KEYWORDS)


def build_composed_dish(target_kcal, prefs, slot, target_protein_g=None, costo_filter=None):
    """
    Elige un plato compuesto (receta completa) de la lista aprobada para
    ESE slot específico (desayuno/almuerzo/cena) y lo escala como receta
    completa (todos los ingredientes juntos, no cada uno por separado).
    costo_filter: si se indica ("economico"/"balanceado"/"premium"), solo
    considera platos de ese nivel de costo.
    El factor de escalado usa el que sea MAYOR entre "llegar al kcal
    objetivo" y "llegar al piso de proteína" — el piso de proteína nunca
    se sacrifica por quedar exacto en kcal (el margen diario ya tolera
    algo de excedente).
    Devuelve None si no hay ningún plato compatible con las preferencias.
    """
    candidatos = [p for p in PLATOS_COMPUESTOS if _plato_permitido(p, prefs, slot)]
    if costo_filter:
        candidatos = [p for p in candidatos if p.get("costo") == costo_filter] or candidatos
    if not candidatos:
        return None

    plato = random.choice(candidatos)
    factor_kcal = target_kcal / plato["kcal_base"] if plato["kcal_base"] else 1
    factor_protein = 0
    if target_protein_g and plato.get("proteina_g"):
        factor_protein = target_protein_g / plato["proteina_g"]

    factor = max(factor_kcal, factor_protein)
    factor = max(PLATO_SCALE_MIN, min(PLATO_SCALE_MAX, factor))

    componentes = []
    for ing in plato["ingredientes"]:
        cantidad_escalada = round(ing["cantidad"] * factor, 1)
        if ing["unidad"] == "ud":
            cantidad_escalada = max(1, round(cantidad_escalada))
        elif ing["unidad"] == "g" and _es_ingrediente_proteina(ing["nombre"]):
            # Mismo tope que en las comidas simples: nunca una sola porción
            # de proteína más grande que esto, aunque la receta escale.
            cantidad_escalada = min(cantidad_escalada, PROTEIN_MAX_GRAMOS_PORCION)
        unidad_map = {"g": "gramos", "ml": "ml", "ud": "unidad"}
        componentes.append({
            "nombre": ing["nombre"], "cantidad": cantidad_escalada,
            "unidad": unidad_map.get(ing["unidad"], ing["unidad"]),
        })

    return {
        "nombre_plato": plato["nombre"],
        "componentes": componentes,
        "kcal_total": round(plato["kcal_base"] * factor, 1),
        "proteina_g_total": round(plato.get("proteina_g", 0) * factor, 1),
    }


# Recomendación de carbohidratos por hora durante el entreno de bici,
# según intensidad (mismas bandas del PDF original "Training Fuel Trial 4").
BIKE_CHO_PER_HOUR = {
    "suave": (40, 50),
    "moderado": (50, 70),
    "intervalos": (70, 80),
    "fondo": (90, 100),
}


INTENSIDAD_ORDEN = {"suave": 0, "moderado": 1, "intervalos": 2, "fondo": 3}


def bike_intra_workout_recommendation(bike_sessions):
    """
    Genera el texto de recomendación de carbohidratos durante el entreno
    de bici, usando la banda de la sesión MÁS EXIGENTE del día (si hay
    varias sesiones de bici), no siempre "moderado" a la fuerza.
    Esto es informativo (no se descuenta del kcal objetivo del día,
    igual que en el PDF original donde el "fuel" de entreno es aparte
    del plan base de comidas).
    """
    total_min = sum(s.get("duration_min", 0) for s in bike_sessions)
    intensidad_mas_exigente = max(
        (s.get("intensidad", "moderado") for s in bike_sessions),
        key=lambda i: INTENSIDAD_ORDEN.get(i, 1),
        default="moderado",
    )
    lo, hi = BIKE_CHO_PER_HOUR.get(intensidad_mas_exigente, BIKE_CHO_PER_HOUR["moderado"])
    hours = total_min / 60
    lo_total = round(lo * hours)
    hi_total = round(hi * hours)
    return {
        "texto": (
            f"{lo}-{hi}g de carbohidratos por hora ({intensidad_mas_exigente}) "
            f"(~{lo_total}-{hi_total}g en total para los {round(hours,1)}h de bici) — "
            f"bebida isotónica, gel o fruta de fácil digestión"
        ),
    }


# Opciones fijas de pre-entreno (15-35min antes), tal cual tu PDF original:
# simples, priorizando carbohidratos de fácil digestión, no una comida completa.
PRE_WORKOUT_OPTIONS = [
    {
        "nombre": "45g Corn Flakes + 100ml Leche de Almendra",
        "kcal": 174, "proteina_g": 4, "carbohidratos_g": 38, "grasa_g": 1,
    },
    {
        "nombre": "2 Rice Cakes + 50g Guineo + 20g Mermelada/Miel",
        "kcal": 170, "proteina_g": 3, "carbohidratos_g": 39, "grasa_g": 1,
    },
    {
        "nombre": "½ Bagel (o 1 mini) + 15g Mermelada/Miel",
        "kcal": 164, "proteina_g": 5, "carbohidratos_g": 36, "grasa_g": 1,
    },
]


# Opciones fijas de merienda — snacks reales, no comidas completas
# (antes salían cosas como "camarones + batata" como merienda, que no aplica).
MERIENDA_OPTIONS = [
    {"nombre": "Yogurt griego con fruta y miel", "kcal": 220, "proteina_g": 18, "carbohidratos_g": 30, "grasa_g": 2, "alergenos": ["lactosa"]},
    {"nombre": "Batido de proteína con fruta", "kcal": 200, "proteina_g": 26, "carbohidratos_g": 20, "grasa_g": 2, "alergenos": []},
    {"nombre": "Puñado de almendras con fruta", "kcal": 230, "proteina_g": 6, "carbohidratos_g": 25, "grasa_g": 12, "alergenos": ["frutos secos"]},
    {"nombre": "Tostada integral con aguacate", "kcal": 210, "proteina_g": 5, "carbohidratos_g": 24, "grasa_g": 10, "alergenos": ["gluten"]},
    {"nombre": "Queso con galletas integrales", "kcal": 200, "proteina_g": 10, "carbohidratos_g": 18, "grasa_g": 9, "alergenos": ["lactosa", "gluten"]},
    {"nombre": "Hummus con vegetales", "kcal": 180, "proteina_g": 6, "carbohidratos_g": 20, "grasa_g": 8, "alergenos": []},
    {"nombre": "Barra de proteína", "kcal": 200, "proteina_g": 20, "carbohidratos_g": 22, "grasa_g": 6, "alergenos": ["lactosa"]},
    {"nombre": "Fruta con mantequilla de maní", "kcal": 210, "proteina_g": 6, "carbohidratos_g": 25, "grasa_g": 10, "alergenos": ["frutos secos"]},
]
MERIENDA_SCALE_MIN, MERIENDA_SCALE_MAX = 0.5, 2.0


def _merienda_permitida(item, prefs):
    alergias = set(x.lower() for x in prefs.get("alergias", []))
    if any(a.lower() in alergias for a in item.get("alergenos", [])):
        return False
    evitar = set(x.lower() for x in prefs.get("alimentos_evitar", []))
    if any(e and e in item["nombre"].lower() for e in evitar):
        return False
    return True


def build_merienda(target_kcal, prefs, exclude_names=None):
    """Elige una opción fija de merienda (snack real) y la escala al kcal del slot."""
    exclude_names = exclude_names or set()
    candidatos = [o for o in MERIENDA_OPTIONS if _merienda_permitida(o, prefs)]
    libres = [o for o in candidatos if o["nombre"] not in exclude_names] or candidatos
    if not libres:
        return None

    opcion = random.choice(libres)
    factor = target_kcal / opcion["kcal"] if opcion["kcal"] else 1
    factor = max(MERIENDA_SCALE_MIN, min(MERIENDA_SCALE_MAX, factor))

    return {
        "nombre_plato": opcion["nombre"],
        "componentes": [{
            "nombre": opcion["nombre"], "cantidad": 1, "unidad": "porcion",
            "kcal": round(opcion["kcal"] * factor, 1),
            "proteina_g": round(opcion["proteina_g"] * factor, 1),
            "carbohidratos_g": round(opcion["carbohidratos_g"] * factor, 1),
            "grasa_g": round(opcion["grasa_g"] * factor, 1),
        }],
        "kcal_total": round(opcion["kcal"] * factor, 1),
        "proteina_g_total": round(opcion["proteina_g"] * factor, 1),
    }


def build_premium_option(categoria_proteina, categoria_carb, target_kcal, target_protein_g,
                          db, prefs, slot, exclude_names=None):
    """
    Arma la Opción Premium de una comida: primero intenta un plato compuesto
    marcado como "premium" (ej. Salmón con Vegetales, Shrimp Stir Fry); si no
    hay ninguno disponible para ese slot/preferencias, arma una combinación
    simple usando solo proteínas/carbs de nivel premium (ej. salmón, camarones,
    quinoa), sin las restricciones económicas de las Opciones A/B normales.
    """
    plato_premium = build_composed_dish(target_kcal, prefs, slot, target_protein_g=target_protein_g, costo_filter="premium")
    if plato_premium:
        return plato_premium

    exclude_names = exclude_names or set()
    proteinas = _pick_candidates(db, categoria_proteina, prefs, slot=slot)
    premium_proteinas = [p for p in proteinas if _costo_proteina(p["nombre"]) == "premium"] or proteinas
    carbs = _pick_candidates(db, categoria_carb, prefs, slot=slot)
    premium_carbs = [c for c in carbs if _costo_carb(c["nombre"]) in ("premium", "balanceado")] or carbs

    if not premium_proteinas or not premium_carbs:
        return None

    proteina = random.choice(premium_proteinas)
    carb = random.choice(premium_carbs)

    protein_amount = (target_protein_g / proteina["proteina_g"]) * proteina["cantidad_base"] \
        if proteina["proteina_g"] else proteina["cantidad_base"]
    protein_amount = max(protein_amount, proteina["cantidad_base"] * SCALE_MIN)
    protein_amount = min(protein_amount, proteina["cantidad_base"] * PROTEIN_SCALE_MAX)
    if proteina["unidad_medida"] == "gramos":
        protein_amount = min(protein_amount, PROTEIN_MAX_GRAMOS_PORCION)
    proteina_scaled = scale_food(proteina, protein_amount)

    remaining_kcal = max(target_kcal - proteina_scaled["kcal"], 0)
    carb_amount = (remaining_kcal / carb["kcal"]) * carb["cantidad_base"] if carb["kcal"] else 0
    carb_amount = max(carb_amount, carb["cantidad_base"] * SCALE_MIN)
    carb_amount = min(carb_amount, carb["cantidad_base"] * CARB_SCALE_MAX)
    carb_scaled = scale_food(carb, carb_amount)

    componentes = [proteina_scaled, carb_scaled]
    total_kcal = proteina_scaled["kcal"] + carb_scaled["kcal"]
    total_proteina = sum(c.get("proteina_g", 0) for c in componentes)

    return {
        "componentes": componentes,
        "kcal_total": round(total_kcal, 1),
        "proteina_g_total": round(total_proteina, 1),
    }


def build_pre_entreno():
    """
    Elige una de las opciones fijas y simples de pre-entreno (carbo-priority),
    en vez de armar una comida completa con proteína como las demás.
    """
    opcion = random.choice(PRE_WORKOUT_OPTIONS)
    return {
        "componentes": [{
            "nombre": opcion["nombre"], "cantidad": 1, "unidad": "porcion",
            "kcal": opcion["kcal"], "proteina_g": opcion["proteina_g"],
            "carbohidratos_g": opcion["carbohidratos_g"], "grasa_g": opcion["grasa_g"],
        }],
        "kcal_total": opcion["kcal"],
    }


# Opciones fijas de post-entreno, tal cual tu PDF original: snack de
# recuperación simple (proteína + carb), NO una comida completa — así
# sirve igual si el atleta entrena a las 5am antes del desayuno o a las
# 5pm antes de la cena, sin sumar una comida de más.
POST_WORKOUT_OPTIONS = [
    {
        "nombre": "30g Corn Flakes + 1 Scoop Proteína Isopure + ½ Porción de Fruta",
        "kcal": 237, "proteina_g": 28, "carbohidratos_g": 33, "grasa_g": 1,
    },
    {
        "nombre": "120g Yogurt Griego Chobani 0% + 20g Proteína Isopure + 1 Porción de Fruta + 15g Miel",
        "kcal": 237, "proteina_g": 29, "carbohidratos_g": 31, "grasa_g": 1,
    },
]


def build_post_entreno():
    """Elige una de las opciones fijas y simples de post-entreno (snack de recuperación)."""
    opcion = random.choice(POST_WORKOUT_OPTIONS)
    return {
        "componentes": [{
            "nombre": opcion["nombre"], "cantidad": 1, "unidad": "porcion",
            "kcal": opcion["kcal"], "proteina_g": opcion["proteina_g"],
            "carbohidratos_g": opcion["carbohidratos_g"], "grasa_g": opcion["grasa_g"],
        }],
        "kcal_total": opcion["kcal"],
    }


def build_daily_meal_plan(target_kcal, protein_floor_g_val, db, prefs,
                           day_sessions=None, no_puede_cocinar=False, protein_ceiling_g_val=None):
    """
    Arma el plan de comidas del día:
    - desayuno/almuerzo/merienda/cena, CADA UNA con 2 opciones (A y B)
      para que el atleta elija según lo que tenga disponible ese día.
    - Si el día tiene sesión de bici, agrega pre_entreno, intra_entreno
      (recomendación de carbos/hora) y post_entreno.

    day_sessions: lista de sesiones planificadas de ese día
        [{"sport":, "intensidad":, "duration_min":, "planned_if":}, ...]
        (viene de workout_kcal / trainingpeaks_client). Puede ser None
        si el día no tiene entreno.

    Devuelve (plan, diferencia_kcal_real) donde diferencia_kcal_real se
    calcula sobre el promedio de las opciones A de cada comida principal.
    """
    day_sessions = day_sessions or []
    bike_sessions = [s for s in day_sessions if s.get("sport") == "bike"]
    dia_alta_demanda = classify_day_type(day_sessions) == "clave"

    # Si hay bici, el pre/post-entreno se elige PRIMERO y se reserva su kcal
    # del presupuesto total del día — así el número que ve el atleta en el
    # header (target_kcal) representa TODO lo que va a comer ese día
    # (comidas principales + fuel de entreno), no las comidas principales
    # aparte y el fuel como un extra no contado.
    pre_entreno = post_entreno = None
    reservado_kcal = 0
    if bike_sessions:
        pre_entreno = build_pre_entreno()
        post_entreno = build_post_entreno()
        reservado_kcal = pre_entreno["kcal_total"] + post_entreno["kcal_total"]

    target_kcal_comidas = max(target_kcal - reservado_kcal, 0)

    best_plan = None
    best_diff = float("inf")

    for _ in range(MAX_ATTEMPTS):
        plan = {}
        total_kcal_opcion_a = 0

        for slot, pct in MEAL_SPLIT.items():
            slot_target_kcal = target_kcal_comidas * pct
            slot_target_protein = protein_floor_g_val * pct

            if slot == "merienda":
                opcion_a = build_merienda(slot_target_kcal, prefs)
                if not opcion_a:
                    continue
                usados = {opcion_a["nombre_plato"]}
                opcion_b = build_merienda(slot_target_kcal, prefs, exclude_names=usados) or opcion_a
                plan[slot] = {"opcion_a": opcion_a, "opcion_b": opcion_b}
                total_kcal_opcion_a += opcion_a["kcal_total"]
                continue

            categoria_proteina = "restaurante" if (no_puede_cocinar and slot in ("almuerzo", "cena")) else "proteina"
            categoria_carb = "carbohidrato"

            opcion_a = build_meal(
                categoria_proteina, categoria_carb,
                slot_target_kcal, slot_target_protein, db, prefs, slot=slot,
                dia_alta_demanda=dia_alta_demanda,
            )
            if not opcion_a:
                continue

            usados = {c["nombre"] for c in opcion_a["componentes"]}
            opcion_b = None

            # A veces la Opción B es un plato compuesto (receta completa)
            # en vez de la combinación simple proteína+carb.
            if slot in ("desayuno", "almuerzo", "cena") and not no_puede_cocinar and random.random() < PROB_PLATO_COMPUESTO:
                opcion_b = build_composed_dish(slot_target_kcal, prefs, slot, target_protein_g=slot_target_protein)

            if not opcion_b:
                opcion_b = build_meal(
                    categoria_proteina, categoria_carb,
                    slot_target_kcal, slot_target_protein, db, prefs,
                    exclude_names=usados, slot=slot, dia_alta_demanda=dia_alta_demanda,
                ) or opcion_a  # si no hay más variedad disponible, repite A

            # Validar que A y B sean equivalentes en kcal (no una comida
            # de 400 y otra de 900 "para elegir") — si se pasa del margen,
            # reintenta un par de veces antes de aceptarla tal cual.
            equivalencia_intentos = 0
            while (
                opcion_b is not opcion_a
                and abs(opcion_b["kcal_total"] - opcion_a["kcal_total"]) > EQUIVALENCIA_MAX_DIF
                and equivalencia_intentos < 2
            ):
                opcion_b = build_meal(
                    categoria_proteina, categoria_carb,
                    slot_target_kcal, slot_target_protein, db, prefs,
                    exclude_names=usados, slot=slot, dia_alta_demanda=dia_alta_demanda,
                ) or opcion_a
                equivalencia_intentos += 1

            opcion_premium = None
            if not no_puede_cocinar:
                opcion_premium = build_premium_option(
                    categoria_proteina, categoria_carb, slot_target_kcal, slot_target_protein,
                    db, prefs, slot, exclude_names=usados,
                )

            plan[slot] = {"opcion_a": opcion_a, "opcion_b": opcion_b, "opcion_premium": opcion_premium}
            total_kcal_opcion_a += opcion_a["kcal_total"]

        if not plan:
            continue

        diff = abs(total_kcal_opcion_a - target_kcal_comidas)
        if diff < best_diff:
            best_plan, best_diff = plan, diff
        if diff <= MARGIN_KCAL:
            break

    if best_plan and bike_sessions:
        best_plan["pre_entreno"] = pre_entreno
        best_plan["intra_entreno"] = bike_intra_workout_recommendation(bike_sessions)
        best_plan["post_entreno"] = post_entreno

    # --- Piso de proteína diario — verificación final (nunca queda por debajo) ---
    # Aunque cada comida ya apunta a su porción del piso, la variedad (platos
    # compuestos, distintas fuentes de proteína) puede dejar el total del día
    # un poco corto. Si pasa, se reparte el faltante ENTRE TODAS las comidas
    # (no se concentra en una sola) — mejor distribución a lo largo del día
    # y evita porciones de proteína excesivamente grandes en una comida.
    if best_plan:
        main_slots_presentes = [s for s in ("desayuno", "almuerzo", "merienda", "cena") if s in best_plan]

        for _intento_piso in range(3):
            total_proteina_dia = sum(best_plan[s]["opcion_a"].get("proteina_g_total", 0) for s in main_slots_presentes)
            if total_proteina_dia >= protein_floor_g_val or not main_slots_presentes:
                break

            faltante_total = protein_floor_g_val - total_proteina_dia
            faltante_por_slot = faltante_total / len(main_slots_presentes)

            for slot_a_reforzar in main_slots_presentes:
                opcion_a_reforzada = best_plan[slot_a_reforzar]["opcion_a"]
                for c in opcion_a_reforzada["componentes"]:
                    if c.get("proteina_g", 0) > 0 and c["unidad"] != "porcion":
                        factor_extra = 1 + (faltante_por_slot / max(c["proteina_g"], 1))
                        nuevo = dict(c)
                        for macro in ("cantidad", "kcal", "proteina_g", "carbohidratos_g", "grasa_g"):
                            if macro in nuevo:
                                nuevo[macro] = round(nuevo[macro] * factor_extra, 1)
                        # Nunca una sola porción de proteína más grande que el tope absoluto
                        if nuevo["unidad"] == "gramos" and nuevo["cantidad"] > PROTEIN_MAX_GRAMOS_PORCION:
                            factor_tope = PROTEIN_MAX_GRAMOS_PORCION / nuevo["cantidad"]
                            for macro in ("cantidad", "kcal", "proteina_g", "carbohidratos_g", "grasa_g"):
                                nuevo[macro] = round(nuevo[macro] * factor_tope, 1)
                        opcion_a_reforzada["componentes"][opcion_a_reforzada["componentes"].index(c)] = nuevo
                        opcion_a_reforzada["kcal_total"] = round(
                            sum(x["kcal"] for x in opcion_a_reforzada["componentes"]), 1
                        )
                        opcion_a_reforzada["proteina_g_total"] = round(
                            sum(x.get("proteina_g", 0) for x in opcion_a_reforzada["componentes"]), 1
                        )
                        break

        # Si el tope de 320g impide llegar al piso repartiendo, como último
        # recurso se agrega un componente de proteína extra a la comida más
        # grande (el piso manda sobre la preferencia de porciones moderadas).
        total_proteina_dia = sum(best_plan[s]["opcion_a"].get("proteina_g_total", 0) for s in main_slots_presentes)
        if total_proteina_dia < protein_floor_g_val and main_slots_presentes:
            faltante_final = protein_floor_g_val - total_proteina_dia
            slot_mas_grande = max(main_slots_presentes, key=lambda s: best_plan[s]["opcion_a"]["kcal_total"])
            proteinas_disponibles = _pick_candidates(db, "proteina", prefs)
            if proteinas_disponibles:
                extra_proteina = random.choice(proteinas_disponibles)
                cantidad_extra = (faltante_final / extra_proteina["proteina_g"]) * extra_proteina["cantidad_base"] \
                    if extra_proteina["proteina_g"] else 0
                if extra_proteina["unidad_medida"] == "gramos":
                    cantidad_extra = min(cantidad_extra, PROTEIN_MAX_GRAMOS_PORCION)
                extra_scaled = scale_food(extra_proteina, cantidad_extra)
                opcion_a_extra = best_plan[slot_mas_grande]["opcion_a"]
                opcion_a_extra["componentes"].append(extra_scaled)
                opcion_a_extra["kcal_total"] = round(sum(x["kcal"] for x in opcion_a_extra["componentes"]), 1)
                opcion_a_extra["proteina_g_total"] = round(
                    sum(x.get("proteina_g", 0) for x in opcion_a_extra["componentes"]), 1
                )

        # Techo de proteína — si se pasa del máximo (proteína usada de
        # relleno en vez de carbs), recorta REPARTIENDO entre varias comidas
        # (no solo una), en varias pasadas si hace falta — igual que el
        # arreglo del piso, para garantizar que de verdad quede por debajo.
        for _intento_techo in range(3):
            total_proteina_dia = sum(best_plan[s]["opcion_a"].get("proteina_g_total", 0) for s in main_slots_presentes)
            if not protein_ceiling_g_val or total_proteina_dia <= protein_ceiling_g_val or not main_slots_presentes:
                break

            exceso_total = total_proteina_dia - protein_ceiling_g_val
            exceso_por_slot = exceso_total / len(main_slots_presentes)

            for slot_a_recortar in main_slots_presentes:
                opcion_a_recorte = best_plan[slot_a_recortar]["opcion_a"]
                for c in opcion_a_recorte["componentes"]:
                    if c.get("proteina_g", 0) > 0 and c["unidad"] != "porcion":
                        factor_recorte = max(1 - (exceso_por_slot / max(c["proteina_g"], 1)), 0.4)
                        nuevo = dict(c)
                        for macro in ("cantidad", "kcal", "proteina_g", "carbohidratos_g", "grasa_g"):
                            if macro in nuevo:
                                nuevo[macro] = round(nuevo[macro] * factor_recorte, 1)
                        opcion_a_recorte["componentes"][opcion_a_recorte["componentes"].index(c)] = nuevo
                        opcion_a_recorte["kcal_total"] = round(
                            sum(x["kcal"] for x in opcion_a_recorte["componentes"]), 1
                        )
                        opcion_a_recorte["proteina_g_total"] = round(
                            sum(x.get("proteina_g", 0) for x in opcion_a_recorte["componentes"]), 1
                        )
                    break

    # Diferencia final real: comidas principales + fuel de entreno (si aplica)
    # contra el objetivo original del día — recalculada al final, después de
    # cualquier ajuste (incluido el refuerzo de proteína del Nivel 3).
    if best_plan:
        main_slots_presentes = [s for s in ("desayuno", "almuerzo", "merienda", "cena") if s in best_plan]
        total_final = sum(best_plan[s]["opcion_a"]["kcal_total"] for s in main_slots_presentes)
        if best_plan.get("pre_entreno"):
            total_final += best_plan["pre_entreno"]["kcal_total"]
        if best_plan.get("post_entreno"):
            total_final += best_plan["post_entreno"]["kcal_total"]
        best_diff = abs(total_final - target_kcal)

    return best_plan, best_diff


# ---------------------------------------------------------------------------
# Lista de compras semanal — suma todos los ingredientes de la Opción A de
# cada día (comidas principales + pre/post-entreno), agrupados por categoría.
# ---------------------------------------------------------------------------
CATEGORIA_DISPLAY = {
    "proteina": "Proteínas", "carbohidrato": "Carbohidratos", "fruta": "Frutas",
    "vegetal": "Vegetales", "lacteo": "Lácteos", "grasa_saludable": "Otros",
    "suplemento": "Otros", "extra": "Otros", "restaurante": "Otros",
}
CATEGORIAS_ORDEN = ["Proteínas", "Carbohidratos", "Frutas", "Vegetales", "Lácteos", "Otros"]


def build_shopping_list(daily_plans, db):
    """
    Suma las cantidades de cada ingrediente usado en la Opción A de todos
    los días de la semana (comidas principales + pre/post-entreno), y las
    agrupa por categoría para armar la lista de compras.
    Los items de "porción" (merienda, pre/post-entreno de la lista fija)
    se cuentan como unidades ("x3 esta semana") en vez de sumar gramos,
    ya que son snacks/platos preparados, no ingredientes sueltos.
    Devuelve un dict {categoria_display: [(nombre, cantidad, unidad), ...]}.
    """
    acumulado = {}
    porciones_contadas = {}

    for plan in (daily_plans or {}).values():
        if not plan:
            continue
        for slot in ("desayuno", "almuerzo", "merienda", "cena", "pre_entreno", "post_entreno"):
            meal = plan.get(slot)
            if not meal:
                continue
            candidato = meal if slot in ("pre_entreno", "post_entreno") else meal.get("opcion_a")
            if not candidato:
                continue
            for c in candidato.get("componentes", []):
                if c["unidad"] == "porcion":
                    porciones_contadas[c["nombre"]] = porciones_contadas.get(c["nombre"], 0) + 1
                else:
                    key = (c["nombre"], c["unidad"])
                    acumulado[key] = acumulado.get(key, 0) + c["cantidad"]

    categorias = {cat: [] for cat in CATEGORIAS_ORDEN}

    for (nombre, unidad), cantidad in acumulado.items():
        item = get(db, nombre)
        cat_display = CATEGORIA_DISPLAY.get(item["categoria"], "Otros") if item else "Otros"
        categorias[cat_display].append((nombre, round(cantidad), unidad))

    for nombre, count in porciones_contadas.items():
        categorias["Otros"].append((f"{nombre} (snack/plato preparado)", count, "porciones"))

    for cat in categorias:
        categorias[cat].sort(key=lambda x: x[0])

    return categorias
