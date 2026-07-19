"""
meal_planner.py
Distribución diaria de kcal + selección/escalado de comidas dentro de un margen.
"""
import random
import json
import os
from food_db import scale_food, by_category, get

MARGIN_KCAL = 150
MAX_ATTEMPTS = 5
SCALE_MIN, SCALE_MAX = 0.5, 2.2

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
        if c["nombre"].lower() not in excluded
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


def build_meal(categoria_proteina, categoria_carb, target_kcal, target_protein_g, db, prefs, exclude_names=None, slot=None):
    """
    Arma una comida simple (proteína + carb), escalando cantidades para
    acercarse al target de kcal/proteína de ese slot.
    exclude_names: set opcional de nombres a evitar (para generar una
    segunda opción distinta a la primera).
    slot: "desayuno"/"almuerzo"/"cena" — filtra alimentos según la bitácora
    de qué aplica a qué comida (ej. no carne molida en desayuno).
    """
    exclude_names = exclude_names or set()

    proteinas = _pick_candidates(db, categoria_proteina, prefs, slot=slot)
    proteinas_libres = [p for p in proteinas if p["nombre"] not in exclude_names] or proteinas
    carbs = _pick_candidates(db, categoria_carb, prefs, slot=slot)
    carbs_libres = [c for c in carbs if c["nombre"] not in exclude_names] or carbs

    if not proteinas_libres or not carbs_libres:
        return None

    proteina = random.choice(proteinas_libres)

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
    protein_amount = _clamp_scale(protein_amount, proteina["cantidad_base"])
    proteina_scaled = scale_food(proteina, protein_amount)

    remaining_kcal = max(target_kcal - proteina_scaled["kcal"], 0)
    carb_amount = (remaining_kcal / carb["kcal"]) * carb["cantidad_base"] if carb["kcal"] else 0
    carb_amount = _clamp_scale(carb_amount, carb["cantidad_base"])
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
    # componente de grasa saludable en vez de forzar cantidades irreales
    # de proteína/carb.
    still_missing = target_kcal - total_kcal
    if still_missing > MARGIN_KCAL:
        extras = _pick_candidates(db, "grasa_saludable", prefs, slot=slot) or _pick_candidates(db, "lacteo", prefs, slot=slot)
        if extras:
            extra = random.choice(extras)
            extra_amount = (still_missing / extra["kcal"]) * extra["cantidad_base"] if extra["kcal"] else 0
            extra_amount = _clamp_scale_extra(extra_amount, extra["cantidad_base"])
            extra_scaled = scale_food(extra, extra_amount)
            componentes.append(extra_scaled)
            total_kcal += extra_scaled["kcal"]

    return {
        "componentes": componentes,
        "kcal_total": round(total_kcal, 1),
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


def build_composed_dish(target_kcal, prefs, slot):
    """
    Elige un plato compuesto (receta completa) de la lista aprobada para
    ESE slot específico (desayuno/almuerzo/cena) y lo escala como receta
    completa (todos los ingredientes juntos, no cada uno por separado)
    para acercarse al target_kcal de ESE atleta ese día — cada plato sale
    personalizado según lo que requiera, dentro de un rango razonable
    (0.6x-1.6x la porción base) para que siga siendo un plato reconocible.
    Devuelve None si no hay ningún plato compatible con las preferencias.
    """
    candidatos = [p for p in PLATOS_COMPUESTOS if _plato_permitido(p, prefs, slot)]
    if not candidatos:
        return None

    plato = random.choice(candidatos)
    factor = target_kcal / plato["kcal_base"] if plato["kcal_base"] else 1
    factor = max(PLATO_SCALE_MIN, min(PLATO_SCALE_MAX, factor))

    componentes = []
    for ing in plato["ingredientes"]:
        cantidad_escalada = round(ing["cantidad"] * factor, 1)
        if ing["unidad"] == "ud":
            cantidad_escalada = max(1, round(cantidad_escalada))
        unidad_map = {"g": "gramos", "ml": "ml", "ud": "unidad"}
        componentes.append({
            "nombre": ing["nombre"], "cantidad": cantidad_escalada,
            "unidad": unidad_map.get(ing["unidad"], ing["unidad"]),
        })

    return {
        "nombre_plato": plato["nombre"],
        "componentes": componentes,
        "kcal_total": round(plato["kcal_base"] * factor, 1),
    }


# Recomendación de carbohidratos por hora durante el entreno de bici,
# según intensidad (mismas bandas del PDF original "Training Fuel Trial 4").
BIKE_CHO_PER_HOUR = {
    "suave": (40, 50),
    "moderado": (50, 70),
    "intervalos": (70, 80),
    "fondo": (90, 100),
}


def bike_intra_workout_recommendation(total_bike_min):
    """
    Genera el texto de recomendación de carbohidratos durante el entreno
    de bici, sumando todas las sesiones de bici del día.
    Esto es informativo (no se descuenta del kcal objetivo del día,
    igual que en el PDF original donde el "fuel" de entreno es aparte
    del plan base de comidas).
    """
    lo, hi = BIKE_CHO_PER_HOUR.get("moderado", (30, 50))
    hours = total_bike_min / 60
    lo_total = round(lo * hours)
    hi_total = round(hi * hours)
    return {
        "texto": (
            f"{lo}-{hi}g de carbohidratos por hora "
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
                           day_sessions=None, no_puede_cocinar=False):
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

    best_plan = None
    best_diff = float("inf")

    for _ in range(MAX_ATTEMPTS):
        plan = {}
        total_kcal_opcion_a = 0

        for slot, pct in MEAL_SPLIT.items():
            categoria_proteina = "restaurante" if (no_puede_cocinar and slot in ("almuerzo", "cena")) else "proteina"
            categoria_carb = "carbohidrato"
            slot_target_kcal = target_kcal * pct
            slot_target_protein = protein_floor_g_val * pct

            slot_filter = slot if slot != "merienda" else None

            opcion_a = build_meal(
                categoria_proteina, categoria_carb,
                slot_target_kcal, slot_target_protein, db, prefs, slot=slot_filter
            )
            if not opcion_a:
                continue

            usados = {c["nombre"] for c in opcion_a["componentes"]}
            opcion_b = None

            # A veces la Opción B es un plato compuesto (receta completa)
            # en vez de la combinación simple proteína+carb.
            if slot in ("desayuno", "almuerzo", "cena") and not no_puede_cocinar and random.random() < PROB_PLATO_COMPUESTO:
                opcion_b = build_composed_dish(slot_target_kcal, prefs, slot)

            if not opcion_b:
                opcion_b = build_meal(
                    categoria_proteina, categoria_carb,
                    slot_target_kcal, slot_target_protein, db, prefs,
                    exclude_names=usados, slot=slot_filter,
                ) or opcion_a  # si no hay más variedad disponible, repite A

            plan[slot] = {"opcion_a": opcion_a, "opcion_b": opcion_b}
            total_kcal_opcion_a += opcion_a["kcal_total"]

        if not plan:
            continue

        diff = abs(total_kcal_opcion_a - target_kcal)
        if diff < best_diff:
            best_plan, best_diff = plan, diff
        if diff <= MARGIN_KCAL:
            break

    if best_plan and bike_sessions:
        total_bike_min = sum(s["duration_min"] for s in bike_sessions)

        best_plan["pre_entreno"] = build_pre_entreno()
        best_plan["intra_entreno"] = bike_intra_workout_recommendation(total_bike_min)
        best_plan["post_entreno"] = build_post_entreno()

    return best_plan, best_diff
