"""
demo_run.py
Demo end-to-end del motor SmartFuel usando datos de ejemplo
(sin conexión real a TrainingPeaks/Sheets todavía).

Corre esto para validar la lógica antes de conectar las fuentes reales:
    python demo_run.py
"""
from datetime import date, timedelta

from food_db import load_food_db
from phase_engine import (
    update_phase, protein_floor_g, objetivo_label, compute_tdee, compute_daily_kcal,
    classify_day_type, adjust_pct_for_day_type,
)
from workout_kcal import estimate_week_kcal
from meal_planner import build_daily_meal_plan, build_shopping_list


def demo():
    db = load_food_db()

    # --- datos de ejemplo (esto luego viene de TrainingPeaks/Sheets) ---
    athlete_weight_lb = 219
    athlete_weight_kg = athlete_weight_lb / 2.2046
    tiene_potometro = True
    ftp_watts = 250
    age, height_cm, gender = 29, 180, "m"
    actividad_diaria = "Trabajo de escritorio"
    objetivo = "bajar de peso"

    phase_state = {
        "atleta_id": "luis_delarosa",
        "fase_actual": 8,
        "deficit_pct": -0.15,
        "fecha_ultimo_cambio": date.today() - timedelta(weeks=3),
        "fecha_inicio": date(2025, 8, 1),
        "peso_inicial_lb": 247,
        "historial": [
            {"fecha": date(2025, 8, 1), "peso_lb": 247, "deficit_pct": -0.15, "kcal_promedio_semana": 2389, "objetivo_label": "Bajar de Peso", "razon": "arranque"},
            {"fecha": date(2025, 9, 3), "peso_lb": 241, "deficit_pct": -0.13, "kcal_promedio_semana": 2168, "objetivo_label": "Bajar de Peso", "razon": "ritmo dentro del objetivo"},
            {"fecha": date(2026, 7, 14), "peso_lb": 219, "deficit_pct": -0.15, "kcal_promedio_semana": 2120, "objetivo_label": "Bajar de Peso", "razon": "ritmo más lento -> bajar % (más déficit)"},
        ],
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
    sessions_by_day = {d["dia"]: d["sesiones"] for d in planned_workouts}

    # --- 1. actualizar fase (% de déficit) ---
    new_phase_state, reason = update_phase(weight_history, phase_state, objetivo=objetivo)
    print(f"Fase: {objetivo_label(objetivo)} | % déficit: {new_phase_state['deficit_pct']:+.0%} | razón: {reason}\n")

    # --- 2. gasto por sesión ---
    daily_burn = estimate_week_kcal(planned_workouts, athlete_weight_kg, tiene_potometro, ftp_watts)
    print("Gasto estimado por día:", daily_burn, "\n")

    # --- 3. TDEE y kcal objetivo POR DÍA (cada día calculado por separado) ---
    daily_targets = {}
    daily_deficit = {}
    for dia, burn in daily_burn.items():
        training_min = sum(s.get("duration_min", 0) for s in sessions_by_day.get(dia, []))
        tdee_dia = compute_tdee(athlete_weight_kg, height_cm, age, gender, actividad_diaria,
                                 training_kcal=burn, training_min=training_min)
        day_type = classify_day_type(sessions_by_day.get(dia, []))
        pct_dia = adjust_pct_for_day_type(new_phase_state["deficit_pct"], day_type, objetivo)
        daily_targets[dia] = compute_daily_kcal(tdee_dia, pct_dia)
        daily_deficit[dia] = round(tdee_dia - daily_targets[dia])
        print(f"  {dia}: tipo={day_type} | % ajustado={pct_dia:+.0%}")

    kcal_promedio_semana = round(sum(daily_targets.values()) / len(daily_targets))
    print("Kcal objetivo por día:", daily_targets)
    print("Déficit estimado por día:", daily_deficit)
    print("Kcal promedio de la semana:", kcal_promedio_semana, "\n")

    # --- 4. plan de comidas por día ---
    protein_floor = protein_floor_g(athlete_weight_lb)
    daily_plans = {}
    alt_plans = {}
    for day in daily_targets:
        plan, diff = build_daily_meal_plan(
            daily_targets[day], protein_floor, db, prefs,
            day_sessions=sessions_by_day.get(day, [])
        )
        daily_plans[day] = plan

        burn_dia = daily_burn.get(day, 0)
        if burn_dia > 0:
            tdee_sin_entrenar = compute_tdee(athlete_weight_kg, height_cm, age, gender, actividad_diaria,
                                              training_kcal=0, training_min=0)
            pct_descanso = adjust_pct_for_day_type(new_phase_state["deficit_pct"], "descanso", objetivo)
            alt_kcal = compute_daily_kcal(tdee_sin_entrenar, pct_descanso)
            alt_plan, _ = build_daily_meal_plan(alt_kcal, protein_floor, db, prefs, day_sessions=[])
            alt_plans[day] = {"kcal": alt_kcal, "plan": alt_plan}

        print(f"--- {day.upper()} (objetivo {daily_targets[day]} kcal, déficit est. {daily_deficit[day]:+d}, diferencia real: {diff:.0f}) ---")
        if not plan:
            print("  (no se pudo armar un plan con los datos disponibles)")
            continue
        unit_symbol = {"gramos": "g", "ml": "ml", "unidad": "ud"}
        for slot in ["desayuno", "almuerzo", "merienda", "cena"]:
            meal = plan.get(slot)
            if not meal:
                continue
            comp_a = ", ".join(f"{c['nombre']} {c['cantidad']}{unit_symbol.get(c['unidad'], c['unidad'])}" for c in meal["opcion_a"]["componentes"])
            print(f"  {slot} A: {comp_a} -> {meal['opcion_a']['kcal_total']} kcal")
            if meal["opcion_b"] is not meal["opcion_a"]:
                comp_b = ", ".join(f"{c['nombre']} {c['cantidad']}{unit_symbol.get(c['unidad'], c['unidad'])}" for c in meal["opcion_b"]["componentes"])
                print(f"  {slot} B: {comp_b} -> {meal['opcion_b']['kcal_total']} kcal")
        if plan.get("pre_entreno"):
            comp = ", ".join(f"{c['nombre']} {c['cantidad']}{unit_symbol.get(c['unidad'], c['unidad'])}" for c in plan["pre_entreno"]["componentes"])
            print(f"  pre_entreno: {comp} -> {plan['pre_entreno']['kcal_total']} kcal")
        if plan.get("intra_entreno"):
            print(f"  intra_entreno: {plan['intra_entreno']['texto']}")
        if plan.get("post_entreno"):
            comp = ", ".join(f"{c['nombre']} {c['cantidad']}{unit_symbol.get(c['unidad'], c['unidad'])}" for c in plan["post_entreno"]["componentes"])
            print(f"  post_entreno: {comp} -> {plan['post_entreno']['kcal_total']} kcal")
        if day in alt_plans:
            print(f"  [ALTERNO sin entrenar: {alt_plans[day]['kcal']} kcal]")
        print()

    # --- 5. generar PDF ---
    from pdf_builder import build_weekly_pdf
    athlete_info = {
        "edad": age,
        "estatura_cm": height_cm,
        "peso_inicial_lb": phase_state["peso_inicial_lb"],
        "fecha_inicio": phase_state["fecha_inicio"],
        "peso_actual_lb": weight_history[-1]["peso_lb"],
        "fecha_actual": weight_history[-1]["fecha"],
        "historial": phase_state["historial"],
    }
    phase_info_for_pdf = {
        "objetivo_label": objetivo_label(objetivo),
        "kcal_actual": kcal_promedio_semana,
        "deficit_pct": new_phase_state["deficit_pct"],
    }
    shopping_list = build_shopping_list(daily_plans, db)
    pdf_path = build_weekly_pdf(
        "demo_plan.pdf",
        athlete_name="Luis De La Rosa",
        week_label="20-26 de Julio",
        daily_targets=daily_targets,
        daily_plans=daily_plans,
        daily_burn=daily_burn,
        phase_info=phase_info_for_pdf,
        athlete_info=athlete_info,
        sessions_by_day=sessions_by_day,
        daily_deficit=daily_deficit,
        alt_plans=alt_plans,
        shopping_list=shopping_list,
    )
    print(f"PDF generado en: {pdf_path}")


if __name__ == "__main__":
    demo()
