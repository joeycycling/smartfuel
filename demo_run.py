"""
demo_run.py
Demo end-to-end del motor SmartFuel usando datos de ejemplo
(sin conexión real a TrainingPeaks/Sheets todavía).

Corre esto para validar la lógica antes de conectar las fuentes reales:
    python demo_run.py
"""
from datetime import date, timedelta

from food_db import load_food_db
from phase_engine import update_phase, protein_floor_g
from workout_kcal import estimate_week_kcal
from meal_planner import build_daily_targets, build_daily_meal_plan


def demo():
    db = load_food_db()

    # --- datos de ejemplo (esto luego viene de TrainingPeaks/Sheets) ---
    athlete_weight_lb = 219
    athlete_weight_kg = athlete_weight_lb / 2.2046
    tiene_potometro = True
    ftp_watts = 250

    phase_state = {
        "atleta_id": "luis_delarosa",
        "fase_actual": 8,
        "kcal_actual": 2120,
        "fecha_ultimo_cambio": date.today() - timedelta(weeks=3),
    }

    # historial de peso de ejemplo (más antiguo -> más reciente)
    weight_history = [
        {"fecha": date.today() - timedelta(weeks=w), "peso_lb": 219 + (w * 0.4)}
        for w in range(6, -1, -1)
    ]

    prefs = {
        "alimentos_evitar": ["salmón horneado"],
        "alergias": [],
    }

    planned_workouts = [
        {"dia": "lunes", "sesiones": [{"sport": "gym", "intensidad": "moderado", "duration_min": 60}]},
        {"dia": "martes", "sesiones": [{"sport": "bike", "intensidad": "moderado", "duration_min": 90, "planned_if": 0.65}]},
        {"dia": "miercoles", "sesiones": [{"sport": "bike", "intensidad": "suave", "duration_min": 60, "planned_if": 0.55}]},
        {"dia": "jueves", "sesiones": [{"sport": "bike", "intensidad": "intervalos", "duration_min": 75, "planned_if": 0.8}]},
        {"dia": "viernes", "sesiones": []},
        {"dia": "sabado", "sesiones": [{"sport": "bike", "intensidad": "fondo", "duration_min": 180, "planned_if": 0.7}]},
        {"dia": "domingo", "sesiones": [{"sport": "bike", "intensidad": "suave", "duration_min": 60, "planned_if": 0.55}]},
    ]

    # --- 1. actualizar fase ---
    new_phase_state, reason = update_phase(weight_history, phase_state)
    print(f"Fase: {new_phase_state['fase_actual']} | kcal semanal: {new_phase_state['kcal_actual']} | razón: {reason}\n")

    # --- 2. gasto por sesión ---
    daily_burn = estimate_week_kcal(planned_workouts, athlete_weight_kg, tiene_potometro, ftp_watts)
    print("Gasto estimado por día:", daily_burn, "\n")

    # --- 3. distribución diaria ---
    daily_targets = build_daily_targets(daily_burn, new_phase_state["kcal_actual"])
    print("Kcal objetivo por día:", daily_targets, "\n")

    # --- 4. plan de comidas por día ---
    protein_floor = protein_floor_g(athlete_weight_lb)
    for day in daily_targets:
        has_wo = bool(daily_burn.get(day))
        plan, diff = build_daily_meal_plan(
            daily_targets[day], protein_floor, db, prefs, has_workout=has_wo
        )
        print(f"--- {day.upper()} (objetivo {daily_targets[day]} kcal, diferencia real: {diff:.0f}) ---")
        if not plan:
            print("  (no se pudo armar un plan con los datos disponibles)")
            continue
        for slot, meal in plan.items():
            unit_symbol = {"gramos": "g", "ml": "ml", "unidad": "ud"}
            comp_str = ", ".join(
                f"{c['nombre']} {c['cantidad']}{unit_symbol.get(c['unidad'], c['unidad'])}"
                for c in meal["componentes"]
            )
            print(f"  {slot}: {comp_str} -> {meal['kcal_total']} kcal")
        print()


if __name__ == "__main__":
    demo()
