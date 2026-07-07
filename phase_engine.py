"""
phase_engine.py
Calcula fase / kcal semanal en base a tendencia de peso (leída de TrainingPeaks).
"""
from statistics import mean
from datetime import datetime, timedelta
import random

TARGET_MIN_PCT = -0.007  # -0.7% semanal
TARGET_MAX_PCT = -0.005  # -0.5% semanal
MIN_WEEKS_BETWEEN_CHANGES = 2
KCAL_STEP = (100, 200)  # rango de ajuste en kcal


def moving_average(weight_entries, weeks_back_start, weeks_back_end):
    """
    weight_entries: lista de dicts [{"fecha": date, "peso_lb": float}, ...]
    ordenada de más antigua a más reciente.
    Devuelve el promedio de peso en la ventana [weeks_back_start, weeks_back_end]
    semanas atrás desde la fecha más reciente del historial.
    """
    if not weight_entries:
        return None
    now = weight_entries[-1]["fecha"]
    window = [
        e["peso_lb"] for e in weight_entries
        if timedelta(weeks=weeks_back_end) <= (now - e["fecha"]) <= timedelta(weeks=weeks_back_start)
        or (weeks_back_start == 0 and (now - e["fecha"]) <= timedelta(weeks=weeks_back_end))
    ]
    if not window:
        return None
    return mean(window)


def weeks_since(fecha):
    return (datetime.now().date() - fecha).days / 7


def update_phase(weight_entries, phase_state):
    """
    phase_state: {"atleta_id", "fase_actual", "kcal_actual", "fecha_ultimo_cambio"}
    weight_entries: historial de peso ordenado cronológicamente (más antiguo -> más reciente).
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

    step = random.randint(*KCAL_STEP)

    if weekly_change_pct < TARGET_MIN_PCT:
        new_kcal = phase_state["kcal_actual"] + step
        reason = f"perdiendo más rápido del objetivo ({weekly_change_pct:.2%}/semana) -> subir kcal"
    elif weekly_change_pct > TARGET_MAX_PCT:
        new_kcal = phase_state["kcal_actual"] - step
        reason = f"ritmo más lento / estancamiento ({weekly_change_pct:.2%}/semana) -> bajar kcal"
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
