"""
main.py
Orquestador del SmartFuel Nutrition Bot.
Corre cada sábado a las 12:00PM: lee preferencias + TrainingPeaks de cada
atleta, arma el plan nutricional de la semana, genera el PDF y lo envía
por correo.

Variables de entorno esperadas (configurar en Railway):
    TP_EMAIL           - email de la cuenta de coach en TrainingPeaks
    TP_PASSWORD        - contraseña de esa cuenta
    RESEND_API_KEY     - API key de tu cuenta de Resend (para el correo)
    EMAIL_FROM         - remitente verificado en Resend (ej. info@joeycycling.com)
    PREFS_CSV_URL      - link del CSV publicado del Google Form/Sheet
"""
import os
import sys
import time
import traceback
from datetime import datetime

import schedule
from playwright.sync_api import sync_playwright

from tp_auth import login_and_get_page
from trainingpeaks_client import (
    get_athlete_ftp, get_weight_history, get_planned_workouts_week,
    get_athlete_settings, extract_ftp, extract_age, extract_gender,
)
from prefs_loader import fetch_preferences_csv
from phase_engine import (
    update_phase, protein_floor_g, protein_ceiling_g, protein_floor_g_por_tipo_dia,
    get_initial_deficit_pct, objetivo_label,
    compute_tdee, compute_daily_kcal, classify_day_type, adjust_pct_for_day_type,
)
from workout_kcal import estimate_week_kcal
from meal_planner import build_daily_meal_plan, build_shopping_list
from food_db import load_food_db
from phase_store import get_phase_state, save_phase_state, append_historial_entry
from pdf_builder import build_weekly_pdf
from email_sender import send_weekly_plan_email

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "generated_pdfs")
os.makedirs(OUTPUT_DIR, exist_ok=True)


def process_athlete(page, athlete_prefs, db):
    """
    Corre el pipeline completo para un solo atleta.
    athlete_prefs: dict ya parseado por prefs_loader (una fila del sheet).
    """
    athlete_id = athlete_prefs.get("id_atleta")
    athlete_name = athlete_prefs.get("nombre") or "Atleta"
    athlete_email = athlete_prefs.get("email")

    if not athlete_id:
        print(f"[SKIP] {athlete_name}: sin ID_Atleta (TrainingPeaks) en el sheet, se omite.")
        return

    print(f"--- Procesando {athlete_name} (TP ID {athlete_id}) ---")

    try:
        # 1. Peso + FTP/perfil + entrenos planificados de TrainingPeaks
        weight_history = get_weight_history(page, athlete_id)
        settings = get_athlete_settings(page, athlete_id)
        ftp = extract_ftp(settings)
        age = extract_age(settings) or 30
        gender = extract_gender(settings) or "m"
        planned_workouts = get_planned_workouts_week(page, athlete_id)

        if not weight_history:
            print(f"[SKIP] {athlete_name}: sin historial de peso en TrainingPeaks todavía.")
            return

        athlete_weight_lb = weight_history[-1]["peso_lb"]
        athlete_weight_kg = weight_history[-1]["peso_kg"]

        # 2. Gasto calórico estimado por sesión (usa FTP si tiene potómetro)
        tiene_potometro = athlete_prefs.get("tiene_potometro", False)
        daily_burn = estimate_week_kcal(planned_workouts, athlete_weight_kg, tiene_potometro, ftp)
        sessions_by_day = {d["dia"]: d["sesiones"] for d in planned_workouts}
        training_min_by_day = {
            dia: sum(s.get("duration_min", 0) for s in sesiones)
            for dia, sesiones in sessions_by_day.items()
        }

        altura_cm = athlete_prefs.get("altura_cm")
        if not altura_cm:
            altura_cm = 170  # fallback si el atleta no puso su altura en el form
            print(f"  [AVISO] {athlete_name} no tiene altura válida en el sheet, usando 170cm por defecto.")

        objetivo = athlete_prefs.get("objetivo")

        # 3. Fase = % de déficit/superávit (no un número de kcal fijo).
        # Si es atleta nuevo, arranca en el % inicial según objetivo.
        phase_state = get_phase_state(
            athlete_id, default_deficit_pct=get_initial_deficit_pct(objetivo),
            peso_inicial_lb=athlete_prefs.get("peso_inicial_lb") or athlete_weight_lb,
            fecha_inicio=athlete_prefs.get("fecha_inicio_manual") or athlete_prefs.get("fecha_inicio_timestamp"),
        )
        pct_antes = phase_state["deficit_pct"]
        phase_state, reason = update_phase(weight_history, phase_state, objetivo=objetivo)

        # 4. TDEE y kcal objetivo de CADA día por separado — cada día usa su
        # propio gasto real de entreno, no un promedio semanal repartido.
        # Esto evita que un día de mucho entreno se quede con un déficit
        # absoluto desproporcionado, y que el menú alterno salga muy bajo.
        daily_targets = {}
        daily_deficit = {}
        tdee_by_day = {}
        for dia in daily_burn:
            tdee_dia = compute_tdee(
                athlete_weight_kg, altura_cm, age, gender,
                athlete_prefs.get("actividad_diaria"),
                training_kcal=daily_burn.get(dia, 0),
                training_min=training_min_by_day.get(dia, 0),
            )
            tdee_by_day[dia] = tdee_dia
            day_type = classify_day_type(sessions_by_day.get(dia, []))
            pct_dia = adjust_pct_for_day_type(phase_state["deficit_pct"], day_type, objetivo)
            daily_targets[dia] = compute_daily_kcal(tdee_dia, pct_dia)
            daily_deficit[dia] = round(tdee_dia - daily_targets[dia])

        kcal_promedio_semana = round(sum(daily_targets.values()) / len(daily_targets)) if daily_targets else 0

        # Si es la primera vez (historial vacío) o cambió el %, agrega una
        # fila nueva al historial (igual que las filas F1, F2... de tu PDF)
        if not phase_state.get("historial") or phase_state["deficit_pct"] != pct_antes:
            phase_state = append_historial_entry(
                phase_state, fecha=weight_history[-1]["fecha"], peso_lb=athlete_weight_lb,
                deficit_pct=phase_state["deficit_pct"], kcal_promedio_semana=kcal_promedio_semana,
                objetivo_label=objetivo_label(objetivo), razon=reason,
            )
        save_phase_state(athlete_id, phase_state)
        print(f"  Fase {objetivo_label(objetivo)} | {phase_state['deficit_pct']:+.0%} | ~{kcal_promedio_semana} kcal/día prom | {reason}")

        # 5. Plan de comidas por día
        protein_ceiling = protein_ceiling_g(athlete_weight_lb)
        daily_plans = {}
        alt_plans = {}

        # Límite semanal de carnes procesadas (salami, salchicha, jamón de
        # pavo) — una vez se usan PROCESADOS_MAX_SEMANA veces combinadas,
        # se excluyen el resto de la semana para priorizar proteínas frescas.
        PROCESADOS_NOMBRES = {"salami dominicano (frito)", "salchicha de pollo (bravo)", "jamón de pavo"}
        PROCESADOS_MAX_SEMANA = 3
        procesados_contador = 0
        prefs_semana = dict(athlete_prefs)
        prefs_semana["alimentos_evitar"] = list(athlete_prefs.get("alimentos_evitar", []))

        for dia in daily_targets:
            day_type = classify_day_type(sessions_by_day.get(dia, []))
            protein_floor = protein_floor_g_por_tipo_dia(athlete_weight_kg, day_type)

            plan, diff = build_daily_meal_plan(
                daily_targets[dia], protein_floor, db, prefs_semana,
                day_sessions=sessions_by_day.get(dia, []),
                protein_ceiling_g_val=protein_ceiling,
            )
            daily_plans[dia] = plan

            if plan:
                # El piso de proteína (nunca se viola) a veces necesita más
                # kcal de las que el día tenía presupuestadas — cuando pasa,
                # el header debe mostrar el total REAL, no el objetivo
                # original, para que nunca haya un desfase con las macros
                # sumadas. El déficit también se recalcula sobre el real.
                total_real = sum(
                    plan[s]["opcion_a"]["kcal_total"] for s in ("desayuno", "almuerzo", "merienda", "cena")
                    if s in plan
                )
                if plan.get("pre_entreno"):
                    total_real += plan["pre_entreno"]["kcal_total"]
                if plan.get("post_entreno"):
                    total_real += plan["post_entreno"]["kcal_total"]
                total_real = round(total_real)

                if abs(total_real - daily_targets[dia]) > 0:
                    print(f"  [AVISO] {dia}: kcal ajustadas de {daily_targets[dia]} a {total_real} "
                          f"para cumplir el piso de proteína.")
                daily_targets[dia] = total_real
                daily_deficit[dia] = round(tdee_by_day[dia] - total_real)

                for slot in ("desayuno", "almuerzo", "merienda", "cena"):
                    meal = plan.get(slot, {})
                    opcion_a_dia = meal.get("opcion_a") if meal else None
                    if not opcion_a_dia:
                        continue
                    for c in opcion_a_dia["componentes"]:
                        if c["nombre"].lower() in PROCESADOS_NOMBRES:
                            procesados_contador += 1
                if procesados_contador >= PROCESADOS_MAX_SEMANA:
                    for nombre in PROCESADOS_NOMBRES:
                        if nombre not in [x.lower() for x in prefs_semana["alimentos_evitar"]]:
                            prefs_semana["alimentos_evitar"].append(nombre)

            # Si ese día tiene carga de entreno, arma también un menú
            # alterno por si el atleta no puede entrenar ese día — usa el
            # MISMO % de déficit, aplicado al TDEE de ese día SIN entreno
            # (no resta el gasto de un target ya calculado, evita que
            # salga artificialmente bajo).
            burn_dia = daily_burn.get(dia, 0)
            if burn_dia > 0:
                tdee_sin_entrenar = compute_tdee(
                    athlete_weight_kg, altura_cm, age, gender,
                    athlete_prefs.get("actividad_diaria"), training_kcal=0, training_min=0,
                )
                pct_descanso = adjust_pct_for_day_type(phase_state["deficit_pct"], "descanso", objetivo)
                alt_kcal = compute_daily_kcal(tdee_sin_entrenar, pct_descanso)
                protein_floor_descanso = protein_floor_g_por_tipo_dia(athlete_weight_kg, "descanso")
                alt_plan, _ = build_daily_meal_plan(
                    alt_kcal, protein_floor_descanso, db, prefs_semana, day_sessions=[]
                )
                alt_plans[dia] = {"kcal": alt_kcal, "plan": alt_plan}

        # 6. PDF
        week_label = datetime.now().strftime("%d de %B, %Y")
        pdf_filename = f"{athlete_name.replace(' ', '_')}_{datetime.now().strftime('%Y%m%d')}.pdf"
        pdf_path = os.path.join(OUTPUT_DIR, pdf_filename)

        athlete_info = {
            "edad": age,
            "estatura_cm": altura_cm,
            "peso_inicial_lb": round(phase_state.get("peso_inicial_lb", athlete_weight_lb), 1),
            "fecha_inicio": phase_state["fecha_inicio"],
            "peso_actual_lb": round(athlete_weight_lb, 1),
            "fecha_actual": weight_history[-1]["fecha"],
            "historial": phase_state.get("historial", []),
        }
        phase_info_for_pdf = {
            "objetivo_label": objetivo_label(objetivo),
            "kcal_actual": kcal_promedio_semana,
            "deficit_pct": phase_state["deficit_pct"],
        }

        shopping_list = build_shopping_list(daily_plans, db)

        build_weekly_pdf(
            pdf_path, athlete_name, week_label,
            daily_targets, daily_plans, daily_burn, phase_info_for_pdf,
            athlete_info=athlete_info, sessions_by_day=sessions_by_day,
            daily_deficit=daily_deficit, alt_plans=alt_plans,
            shopping_list=shopping_list,
        )

        # 7. Envío por correo
        if athlete_email:
            send_weekly_plan_email(athlete_name, athlete_email, pdf_path, week_label)
            print(f"  Enviado a {athlete_email}")
        else:
            print(f"  [AVISO] {athlete_name} no tiene email en el sheet, no se envió.")

    except Exception:
        print(f"[ERROR] Falló el procesamiento de {athlete_name}:")
        traceback.print_exc()


def run_weekly_job():
    print(f"\n=== SmartFuel — corrida semanal {datetime.now()} ===")

    csv_url = os.environ["PREFS_CSV_URL"]
    all_prefs = fetch_preferences_csv(csv_url)
    db = load_food_db()

    with sync_playwright() as p:
        page, browser = login_and_get_page(p)
        try:
            for athlete_prefs in all_prefs:
                process_athlete(page, athlete_prefs, db)
        finally:
            browser.close()

    print("=== Corrida semanal terminada ===\n")


if __name__ == "__main__":
    if "--run-now" in sys.argv:
        run_weekly_job()
        print("Corrida manual terminada.")
    else:
        schedule.every().saturday.at("12:00").do(run_weekly_job)
        print("SmartFuel Bot corriendo — esperando al sábado 12:00PM...")
        while True:
            schedule.run_pending()
            time.sleep(60)
