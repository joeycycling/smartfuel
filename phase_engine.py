"""
phase_engine.py
Motor de fase basado en % de déficit/superávit — cada día calcula su propio
TDEE real (con su propio gasto de entreno) y le aplica el mismo % consistente,
en vez de repartir un total semanal fijo entre días con desviaciones relativas.

Esto evita 2 problemas del diseño anterior:
1. Un día de mucho entreno se quedaba con un déficit absoluto enorme
   (porque solo recibía el "extra sobre el promedio", no su TDEE real).
2. El menú alterno "si no entrenas" salía muy bajo (restaba el gasto de
   entreno de un target ya distorsionado, en vez de aplicar el mismo %
   de déficit sobre el TDEE sin entrenar).
"""
from statistics import mean
from datetime import datetime, timedelta

MIN_WEEKS_BETWEEN_CHANGES = 2
PCT_STEP = 0.02  # ajuste de 2 puntos porcentuales cada vez que toca reevaluar

# Rango de cambio de peso semanal objetivo, según el objetivo del atleta.
OBJETIVO_RANGES = {
    "bajar de peso": (-0.007, -0.005),
    "mantenimiento": (-0.0015, 0.0015),
    "aumento de masa muscular": (0.0015, 0.004),
}
DEFAULT_OBJETIVO = "bajar de peso"

# Ajuste inicial de % al arrancar (Fase 1, antes de tener tendencia de peso).
INITIAL_DEFICIT_PCT = {
    "bajar de peso": -0.15,
    "mantenimiento": 0.0,
    "aumento de masa muscular": 0.10,
}

# Límites de seguridad del % — para nunca comprometer el rendimiento del
# atleta con un déficit demasiado agresivo, ni un superávit exagerado.
DEFICIT_BOUNDS = {
    "bajar de peso": (-0.25, -0.05),
    "mantenimiento": (-0.05, 0.05),
    "aumento de masa muscular": (0.05, 0.20),
}

# Etiqueta legible para mostrar en el PDF en vez de "Fase 1, 2, 3..."
OBJETIVO_DISPLAY = {
    "bajar de peso": "Bajar de Peso",
    "mantenimiento": "Mantenimiento",
    "aumento de masa muscular": "Aumento de Masa",
}


def objetivo_label(objetivo):
    key = (objetivo or "").strip().lower()
    return OBJETIVO_DISPLAY.get(key, OBJETIVO_DISPLAY[DEFAULT_OBJETIVO])


def _get_range(objetivo):
    if not objetivo:
        return OBJETIVO_RANGES[DEFAULT_OBJETIVO]
    return OBJETIVO_RANGES.get(objetivo.strip().lower(), OBJETIVO_RANGES[DEFAULT_OBJETIVO])


def _get_bounds(objetivo):
    key = (objetivo or "").strip().lower()
    return DEFICIT_BOUNDS.get(key, DEFICIT_BOUNDS[DEFAULT_OBJETIVO])


def get_initial_deficit_pct(objetivo):
    key = (objetivo or "").strip().lower()
    return INITIAL_DEFICIT_PCT.get(key, INITIAL_DEFICIT_PCT[DEFAULT_OBJETIVO])


def moving_average(weight_entries, weeks_back_start, weeks_back_end):
    """
    weight_entries: lista de dicts [{"fecha": date, "peso_lb": float}, ...]
    ordenada de más antigua a más reciente.
    Devuelve el promedio de peso en la ventana de semanas atrás
    [min(weeks_back_start, weeks_back_end), max(...)] desde la fecha
    más reciente del historial.
    """
    if not weight_entries:
        return None
    now = weight_entries[-1]["fecha"]
    lower = min(weeks_back_start, weeks_back_end)
    upper = max(weeks_back_start, weeks_back_end)
    window = [
        e["peso_lb"] for e in weight_entries
        if timedelta(weeks=lower) <= (now - e["fecha"]) <= timedelta(weeks=upper)
    ]
    if not window:
        return None
    return mean(window)


def weeks_since(fecha):
    return (datetime.now().date() - fecha).days / 7


def update_phase(weight_entries, phase_state, objetivo=None):
    """
    phase_state: {"atleta_id", "deficit_pct", "fecha_ultimo_cambio", ...}
    weight_entries: historial de peso ordenado cronológicamente (más antiguo -> más reciente).
    objetivo: "bajar de peso" / "mantenimiento" / "aumento de masa muscular".
    Devuelve (nuevo_phase_state, razon_texto).

    Ajusta el % de déficit/superávit (no un número de kcal) — el mismo %
    se le aplica después al TDEE específico de cada día individualmente.
    """
    if weeks_since(phase_state["fecha_ultimo_cambio"]) < MIN_WEEKS_BETWEEN_CHANGES:
        return phase_state, "aún no toca reevaluar (menos de 2 semanas desde el último cambio)"

    avg_now = moving_average(weight_entries, weeks_back_start=0, weeks_back_end=2)
    avg_prev = moving_average(weight_entries, weeks_back_start=2, weeks_back_end=4)

    if avg_now is None or avg_prev is None or avg_prev == 0:
        return phase_state, "datos insuficientes de peso para evaluar tendencia"

    weeks_elapsed = max(weeks_since(phase_state["fecha_ultimo_cambio"]), 1)
    weekly_change_pct = ((avg_now - avg_prev) / avg_prev) / weeks_elapsed

    target_min_pct, target_max_pct = _get_range(objetivo)
    lo_bound, hi_bound = _get_bounds(objetivo)
    current_pct = phase_state["deficit_pct"]

    if weekly_change_pct < target_min_pct:
        # perdiendo/subiendo más rápido de lo objetivo -> menos déficit (o más superávit)
        new_pct = round(min(current_pct + PCT_STEP, hi_bound), 4)
        reason = f"por debajo del ritmo objetivo ({weekly_change_pct:.2%}/semana) -> subir % (menos déficit)"
    elif weekly_change_pct > target_max_pct:
        # ritmo más lento / estancamiento -> más déficit (o menos superávit)
        new_pct = round(max(current_pct - PCT_STEP, lo_bound), 4)
        reason = f"por encima del ritmo objetivo ({weekly_change_pct:.2%}/semana) -> bajar % (más déficit)"
    else:
        new_pct = current_pct
        reason = f"dentro del rango objetivo ({weekly_change_pct:.2%}/semana) -> mantener"

    if new_pct != current_pct:
        new_state = {
            "atleta_id": phase_state["atleta_id"],
            "fase_actual": phase_state.get("fase_actual", 1) + 1,
            "deficit_pct": new_pct,
            "fecha_ultimo_cambio": datetime.now().date(),
            "fecha_inicio": phase_state["fecha_inicio"],
            "peso_inicial_lb": phase_state["peso_inicial_lb"],
            "historial": phase_state.get("historial", []),
        }
        return new_state, reason

    return phase_state, reason


def protein_floor_g(weight_lb, g_per_lb=1.0):
    """Piso de proteína diario: 1g por lb de peso corporal (fijo, no baja con las kcal)."""
    return round(weight_lb * g_per_lb, 1)


def protein_ceiling_g(weight_lb, g_per_lb=1.1):
    """
    Techo máximo de proteína diaria — más allá de esto no aporta beneficio
    real y desplaza carbohidratos que el atleta sí necesita para rendir.
    1.1g/lb ≈ 2.4g/kg, el límite superior del rango recomendado (1.8-2.4g/kg)
    para preservar masa muscular en déficit sin excederse innecesariamente.
    """
    return round(weight_lb * g_per_lb, 1)


# ---------------------------------------------------------------------------
# TDEE — calculado fresco cada vez, por día, con el gasto real de ESE día
# ---------------------------------------------------------------------------

# Factor de actividad NO relacionado al entreno (trabajo/día a día).
OCCUPATIONAL_ACTIVITY_FACTOR = {
    "Trabajo de escritorio": 1.2,
    "De pie o caminando bastante": 1.375,
    "Trabajo físico": 1.55,
}
DEFAULT_ACTIVITY_FACTOR = 1.3  # si no se sabe el nivel de actividad diaria


def compute_bmr_mifflin(weight_kg, height_cm, age, gender):
    """
    Ecuación de Mifflin-St Jeor:
    Hombres: BMR = 10*peso + 6.25*altura - 5*edad + 5
    Mujeres: BMR = 10*peso + 6.25*altura - 5*edad - 161
    """
    base = 10 * weight_kg + 6.25 * height_cm - 5 * age
    gender = (gender or "m").lower()
    return base + 5 if gender.startswith("m") else base - 161


def compute_tdee(weight_kg, height_cm, age, gender, actividad_diaria,
                  training_kcal=0, training_min=0):
    """
    TDEE = (BMR/24 x factor de actividad) x horas SIN entrenar
           + kcal reales del entreno (que ya cubren el gasto de esas horas)
    Se resta la hora de entreno del cálculo de BMR porque las kcal del
    entreno YA representan el gasto completo de esas horas — sumar el BMR
    de esas mismas horas aparte las contaría dos veces.
    Se llama UNA VEZ POR DÍA con el gasto real de ESE día específico —
    nunca con un promedio semanal — para que cada día sea preciso.
    """
    bmr = compute_bmr_mifflin(weight_kg, height_cm, age, gender)
    factor = OCCUPATIONAL_ACTIVITY_FACTOR.get(actividad_diaria, DEFAULT_ACTIVITY_FACTOR)
    training_hours = min(training_min / 60, 24)
    non_training_hours = 24 - training_hours
    bmr_no_entreno = (bmr / 24) * factor * non_training_hours
    return bmr_no_entreno + training_kcal


def compute_daily_kcal(tdee_day, deficit_pct):
    """kcal objetivo de un día específico = su propio TDEE x (1 + % de déficit/superávit)."""
    return round(tdee_day * (1 + deficit_pct))


# ---------------------------------------------------------------------------
# Deficit variable por tipo de día — protege el rendimiento en entrenos
# clave/fondos largos (menos déficit ese día), y carga más el déficit en
# los días de descanso (donde no hay rendimiento que proteger).
# ---------------------------------------------------------------------------
DAY_TYPE_MODIFIER = {
    "descanso": 1.3,   # más déficit — no hay entreno que proteger ese día
    "normal": 1.0,      # el % base, sin cambios
    "clave": 0.4,       # mucho menos déficit — proteger el rendimiento/recuperación
}


def classify_day_type(day_sessions):
    """
    Clasifica el día según su carga de entreno:
    - "descanso": sin ninguna sesión planificada
    - "clave": tiene una sesión de intervalos/fondo, o >=150min de duración
    - "normal": cualquier otro entreno (suave/moderado, más corto)
    """
    if not day_sessions:
        return "descanso"
    for s in day_sessions:
        if s.get("intensidad") in ("intervalos", "fondo") or s.get("duration_min", 0) >= 150:
            return "clave"
    return "normal"


def adjust_pct_for_day_type(base_pct, day_type, objetivo):
    """
    Aplica el modificador de tipo de día al % base, respetando siempre los
    límites de seguridad del objetivo (nunca se pasa del rango seguro aunque
    el modificador lo empuje más allá).
    """
    modifier = DAY_TYPE_MODIFIER.get(day_type, 1.0)
    adjusted = base_pct * modifier
    lo, hi = _get_bounds(objetivo)
    return max(lo, min(hi, adjusted))
