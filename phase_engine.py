"""
phase_engine.py
Calcula fase / kcal semanal en base a tendencia de peso (leída de TrainingPeaks).
"""
from statistics import mean
from datetime import datetime, timedelta
import random

MIN_WEEKS_BETWEEN_CHANGES = 2
KCAL_STEP = (100, 200)  # rango de ajuste en kcal

# Rango de cambio de peso semanal objetivo, según el objetivo del atleta.
# La misma lógica de "ajustar según el ritmo" sirve para los 3 casos —
# solo cambia hacia dónde apunta el rango.
OBJETIVO_RANGES = {
    "bajar de peso": (-0.007, -0.005),
    "mantenimiento": (-0.0015, 0.0015),
    "aumento de masa muscular": (0.0015, 0.004),
}
DEFAULT_OBJETIVO = "bajar de peso"

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
    phase_state: {"atleta_id", "fase_actual", "kcal_actual", "fecha_ultimo_cambio"}
    weight_entries: historial de peso ordenado cronológicamente (más antiguo -> más reciente).
    objetivo: "bajar de peso" / "mantenimiento" / "aumento de masa muscular"
              (viene de la columna "Objetivo" del sheet de preferencias).
    Devuelve (nuevo_phase_state, razon_texto).
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
    step = random.randint(*KCAL_STEP)

    if weekly_change_pct < target_min_pct:
        new_kcal = phase_state["kcal_actual"] + step
        reason = f"por debajo del ritmo objetivo ({weekly_change_pct:.2%}/semana) -> subir kcal"
    elif weekly_change_pct > target_max_pct:
        new_kcal = phase_state["kcal_actual"] - step
        reason = f"por encima del ritmo objetivo ({weekly_change_pct:.2%}/semana) -> bajar kcal"
    else:
        new_kcal = phase_state["kcal_actual"]
        reason = f"dentro del rango objetivo ({weekly_change_pct:.2%}/semana) -> mantener"

    if new_kcal != phase_state["kcal_actual"]:
        new_state = {
            "atleta_id": phase_state["atleta_id"],
            "fase_actual": phase_state["fase_actual"] + 1,
            "kcal_actual": new_kcal,
            "fecha_ultimo_cambio": datetime.now().date(),
        }
        return new_state, reason

    return phase_state, reason


def protein_floor_g(weight_lb, g_per_lb=1.0):
    """Piso de proteína diario: 1g por lb de peso corporal (fijo, no baja con las kcal)."""
    return round(weight_lb * g_per_lb, 1)


# ---------------------------------------------------------------------------
# TDEE inicial para atletas nuevos (sin fase previa todavía)
# ---------------------------------------------------------------------------

# Factor de actividad NO relacionado al entreno (trabajo/día a día) —
# el gasto del entreno se suma aparte con el promedio real de kcal
# quemadas en bici/run/gym/etc, para no duplicar el conteo.
OCCUPATIONAL_ACTIVITY_FACTOR = {
    "Trabajo de escritorio": 1.2,
    "De pie o caminando bastante": 1.375,
    "Trabajo físico": 1.55,
}
DEFAULT_ACTIVITY_FACTOR = 1.3  # si no se sabe el nivel de actividad diaria

# Ajuste inmediato sobre el TDEE de arranque, según objetivo — para no
# esperar 2 semanas de tendencia antes de aplicar el primer déficit/superávit
# (igual que tu metodología real, donde la Fase 1 ya arranca ajustada).
INITIAL_ADJUSTMENT_BY_OBJETIVO = {
    "bajar de peso": -0.15,
    "mantenimiento": 0.0,
    "aumento de masa muscular": 0.10,
}


def compute_bmr_mifflin(weight_kg, height_cm, age, gender):
    """
    Ecuación de Mifflin-St Jeor:
    Hombres: BMR = 10*peso + 6.25*altura - 5*edad + 5
    Mujeres: BMR = 10*peso + 6.25*altura - 5*edad - 161
    """
    base = 10 * weight_kg + 6.25 * height_cm - 5 * age
    gender = (gender or "m").lower()
    return base + 5 if gender.startswith("m") else base - 161


def compute_initial_kcal(weight_kg, height_cm, age, gender, actividad_diaria,
                          avg_daily_training_kcal=0, objetivo=None):
    """
    Punto de partida de kcal para un atleta SIN fase previa:
    TDEE = BMR (Mifflin-St Jeor) x factor de actividad ocupacional
           + promedio diario de kcal quemadas en entreno
    Luego se aplica un ajuste inmediato según objetivo (ej. -15% si es
    "bajar de peso"), para no esperar 2 semanas al primer ajuste de fase.

    El entreno se suma aparte (no dentro del factor de actividad) porque
    ya lo calculamos de forma específica por sesión en workout_kcal.py —
    meterlo también en el factor de actividad lo contaría dos veces.
    """
    bmr = compute_bmr_mifflin(weight_kg, height_cm, age, gender)
    factor = OCCUPATIONAL_ACTIVITY_FACTOR.get(actividad_diaria, DEFAULT_ACTIVITY_FACTOR)
    tdee = bmr * factor + avg_daily_training_kcal

    objetivo_key = (objetivo or "").strip().lower()
    ajuste = INITIAL_ADJUSTMENT_BY_OBJETIVO.get(objetivo_key, INITIAL_ADJUSTMENT_BY_OBJETIVO["bajar de peso"])

    return round(tdee * (1 + ajuste))
