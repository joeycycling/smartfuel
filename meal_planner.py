"""
meal_planner.py
Distribución diaria de kcal + selección/escalado de comidas dentro de un margen.
"""
import random
from food_db import scale_food, by_category

MARGIN_KCAL = 150
MAX_ATTEMPTS = 5
SCALE_MIN, SCALE_MAX = 0.5, 2.2

# reparto simple de kcal/proteína entre comidas del día (ajustable)
MEAL_SPLIT = {"desayuno": 0.25, "almuerzo": 0.35, "merienda": 0.10, "cena": 0.30}


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


def build_meal(categoria_proteina, categoria_carb, target_kcal, target_protein_g, db, prefs):
    """
    Arma una comida simple (proteína + carb), escalando cantidades para
    acercarse al target de kcal/proteína de ese slot.
    """
    proteinas = _pick_candidates(db, categoria_proteina, prefs)
    carbs = _pick_candidates(db, categoria_carb, prefs)
    if not proteinas or not carbs:
        return None

    proteina = random.choice(proteinas)
    carb = random.choice(carbs)

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


def build_daily_meal_plan(target_kcal, protein_floor_g_val, db, prefs,
                           has_workout=False, no_puede_cocinar=False):
    """
    Arma desayuno/almuerzo/merienda/cena para un día, reintentando
    combinaciones hasta caer dentro del margen (±150 kcal) o agotar intentos.
    Devuelve (mejor_plan, diferencia_kcal_real).
    """
    best_plan = None
    best_diff = float("inf")

    for _ in range(MAX_ATTEMPTS):
        plan = {}
        for slot, pct in MEAL_SPLIT.items():
            categoria_proteina = "restaurante" if (no_puede_cocinar and slot in ("almuerzo", "cena")) else "proteina"
            categoria_carb = "carbohidrato"
            meal = build_meal(
                categoria_proteina, categoria_carb,
                target_kcal * pct, protein_floor_g_val * pct,
                db, prefs
            )
            if meal:
                plan[slot] = meal

        if not plan:
            continue

        total_kcal = sum(m["kcal_total"] for m in plan.values())
        diff = abs(total_kcal - target_kcal)

        if diff < best_diff:
            best_plan, best_diff = plan, diff

        if diff <= MARGIN_KCAL:
            break

    return best_plan, best_diff
