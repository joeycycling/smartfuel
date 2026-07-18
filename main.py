"""
main.py
Orquestador del SmartFuel Nutrition Bot.
Corre cada sábado a las 12:00PM: lee preferencias + TrainingPeaks de cada
atleta, arma el plan nutricional de la semana, genera el PDF y lo envía
por correo.

Variables de entorno esperadas (configurar en Railway):
    TP_EMAIL           - email de la cuenta de coach en TrainingPeaks
    TP_PASSWORD        - contraseña de esa cuenta
    EMAIL_USER         - info@joeycycling.com
    EMAIL_PASSWORD     - contraseña del buzón de GoDaddy
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
from phase_engine import update_phase, protein_floor_g, compute_initial_kcal
from workout_kcal import estimate_week_kcal
from meal_planner import build_daily_targets, build_daily_meal_plan
from food_db import load_food_db
from phase_store import get_phase_state, save_phase_state
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
        avg_daily_training_kcal = sum(daily_burn.values()) / len(daily_burn) if daily_burn else 0

        # 3. Fase / kcal semanal — si es atleta nuevo (sin fase previa), el
        # punto de partida se calcula con Mifflin-St Jeor + actividad diaria
        # + promedio de entreno, en vez de un estimado genérico.
        altura_cm = athlete_prefs.get("altura_cm")
        if not altura_cm:
            altura_cm = 170  # fallback si el atleta no puso su altura en el form
            print(f"  [AVISO] {athlete_name} no tiene altura válida en el sheet, usando 170cm por defecto.")

        objetivo = athlete_prefs.get("objetivo")

        default_kcal = compute_initial_kcal(
            athlete_weight_kg, altura_cm, age, gender,
            athlete_prefs.get("actividad_diaria"),
            avg_daily_training_kcal,
        )

        phase_state = get_phase_state(athlete_id, default_kcal=default_kcal)
        phase_state, reason = update_phase(weight_history, phase_state, objetivo=objetivo)
        save_phase_state(athlete_id, phase_state)
        print(f"  Fase {phase_state['fase_actual']} | {phase_state['kcal_actual']} kcal | {reason}")

        # 4. Distribución diaria de kcal
        daily_targets = build_daily_targets(daily_burn, phase_state["kcal_actual"])

        # 5. Plan de comidas por día
        protein_floor = protein_floor_g(athlete_weight_lb)
        sessions_by_day = {d["dia"]: d["sesiones"] for d in planned_workouts}
        daily_plans = {}
        for dia in daily_targets:
            plan, diff = build_daily_meal_plan(
                daily_targets[dia], protein_floor, db, athlete_prefs,
                day_sessions=sessions_by_day.get(dia, [])
            )
            daily_plans[dia] = plan

        # 6. PDF
        week_label = datetime.now().strftime("%d de %B, %Y")
        pdf_filename = f"{athlete_name.replace(' ', '_')}_{datetime.now().strftime('%Y%m%d')}.pdf"
        pdf_path = os.path.join(OUTPUT_DIR, pdf_filename)
        build_weekly_pdf(
            pdf_path, athlete_name, week_label,
            daily_targets, daily_plans, daily_burn, phase_state,
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
