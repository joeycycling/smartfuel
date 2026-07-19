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


def _pick_candidates(db, categoria, prefs):
    """Filtra alimentos de una categoría respetando preferencias/alergias del atleta."""
    candidates = by_category(db, categoria)
    excluded = set(x.lower() for x in prefs.get("alimentos_evitar", []))
    allergens = set(x.lower() for x in prefs.get("alergias", []))
    return [
        c for c in candidates
        if c["nombre"].lower() not in excluded
        and not any(a in c["nombre"].lower() for a in allergens if a)
    ]


def _clamp_scale(amount, base_amount):
    if base_amount == 0:
        return 0
    factor = amount / base_amount
    factor = max(SCALE_MIN, min(SCALE_MAX, factor))
    return round(base_amount * factor, 1)


def build_meal(categoria_proteina, categoria_carb, target_kcal, target_protein_g, db, prefs, exclude_names=None):
    """
    Arma una comida simple (proteína + carb), escalando cantidades para
    acercarse al target de kcal/proteína de ese slot.
    exclude_names: set opcional de nombres a evitar (para generar una
    segunda opción distinta a la primera).
    """
    exclude_names = exclude_names or set()

    proteinas = _pick_candidates(db, categoria_proteina, prefs)
    proteinas_libres = [p for p in proteinas if p["nombre"] not in exclude_names] or proteinas
    carbs = _pick_candidates(db, categoria_carb, prefs)
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
        extras = _pick_candidates(db, "grasa_saludable", prefs) or _pick_candidates(db, "lacteo", prefs)
        if extras:
            extra = random.choice(extras)
            extra_amount = (still_missing / extra["kcal"]) * extra["cantidad_base"] if extra["kcal"] else 0
            extra_amount = _clamp_scale(extra_amount, extra["cantidad_base"])
            extra_scaled = scale_food(extra, extra_amount)
            componentes.append(extra_scaled)
            total_kcal += extra_scaled["kcal"]

    return {
        "componentes": componentes,
        "kcal_total": round(total_kcal, 1),
    }


# Recomendación de carbohidratos por hora durante el entreno de bici,
# según intensidad (mismas bandas del PDF original "Training Fuel Trial 4").
BIKE_CHO_PER_HOUR = {
    "suave": (20, 30),
    "moderado": (30, 50),
    "intervalos": (50, 60),
    "fondo": (70, 80),
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

            opcion_a = build_meal(
                categoria_proteina, categoria_carb,
                slot_target_kcal, slot_target_protein, db, prefs
            )
            if not opcion_a:
                continue

            usados = {c["nombre"] for c in opcion_a["componentes"]}
            opcion_b = build_meal(
                categoria_proteina, categoria_carb,
                slot_target_kcal, slot_target_protein, db, prefs,
                exclude_names=usados,
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
