"""
trainingpeaks_client.py
Cliente para leer datos reales de TrainingPeaks (peso, FTP, entrenos planificados)
reusando la misma sesión autenticada de Playwright que ya usa el Comments Bot.

Todas las funciones reciben un objeto `page` de Playwright ya autenticado
(la misma sesión/cookies que usa tp-bot) y hacen fetch() autenticado
via page.evaluate(), igual que el patrón existente.
"""
import json
from datetime import datetime, timedelta

BASE_TPAPI = "https://tpapi.trainingpeaks.com"

# Type IDs del endpoint consolidatedtimedmetrics (confirmados con datos reales)
METRIC_TYPE_WEIGHT = 9
METRIC_TYPE_BMI = 14
METRIC_TYPE_PERCENT_FAT = 2
METRIC_TYPE_MUSCLE_MASS = 57

KG_TO_LB = 2.20462

# IDs de tipo de entreno confirmados con datos reales de la cuenta
# (sacados de los workouts que Joey abrió: Swim, Bike, Run, Gym, Walking).
# 7 = "Día libre" (descanso) -> None, se excluye de las sesiones.
WORKOUT_TYPE_MAP = {
    1: "swim",       # Lap Swimming
    2: "bike",       # pth. ... (nomenclatura de bici de Joey)
    3: "run",        # Run @...
    4: "gym",        # Transition (T1) - breve, se trata como gym para el cálculo de kcal
    5: "gym",        # sf. ... - sin confirmar del todo, fallback a gym
    7: None,         # Día libre - se excluye, no genera sesión
    9: "gym",        # Fortalecimiento / X-Train
    10: "gym",       # Fuerza (Biceps-triceps-hombros, etc.)
    13: "walk",      # Walking
    100: "gym",      # Other - fallback
}


def _fetch_json(page, url):
    """
    Hace un fetch autenticado (misma sesión del navegador) y devuelve el JSON parseado.
    Usa page.evaluate() igual que el Comments Bot.
    """
    script = f"""
        async () => {{
            const res = await fetch("{url}", {{ credentials: "include" }});
            if (!res.ok) throw new Error("HTTP " + res.status);
            return await res.json();
        }}
    """
    return page.evaluate(script)


# ---------------------------------------------------------------------------
# FTP y zonas
# ---------------------------------------------------------------------------

def get_athlete_settings(page, athlete_id):
    """
    GET /fitness/v1/athletes/{athleteId}/settings
    Devuelve el JSON completo (zonas de potencia, FC, velocidad, perfil).
    """
    url = f"{BASE_TPAPI}/fitness/v1/athletes/{athlete_id}/settings"
    return _fetch_json(page, url)


def extract_ftp(settings_json):
    """
    Extrae el FTP (umbral de potencia) del JSON de settings.
    settings_json["powerZones"][0]["threshold"]
    """
    power_zones = settings_json.get("powerZones") or []
    if not power_zones:
        return None
    return power_zones[0].get("threshold")


def extract_hr_threshold(settings_json):
    """Extrae el umbral de FC, por si se necesita para zonas de running."""
    hr_zones = settings_json.get("heartRateZones") or []
    if not hr_zones:
        return None
    return hr_zones[0].get("threshold")


def extract_age(settings_json):
    """Extrae la edad del atleta (para el cálculo de TDEE/Mifflin-St Jeor)."""
    return settings_json.get("age")


def extract_gender(settings_json):
    """Extrae el género del atleta ('m'/'f'), para el cálculo de TDEE."""
    return settings_json.get("gender")


def get_athlete_ftp(page, athlete_id):
    """Atajo: obtiene settings y devuelve directo el FTP."""
    settings = get_athlete_settings(page, athlete_id)
    return extract_ftp(settings)


# ---------------------------------------------------------------------------
# Peso histórico
# ---------------------------------------------------------------------------

def get_consolidated_metrics(page, athlete_id, start_date, end_date):
    """
    GET /metrics/v3/athletes/{athleteId}/consolidatedtimedmetrics/{start}/{end}
    start_date/end_date: strings "YYYY-MM-DD"
    Devuelve la lista cruda (un objeto por día, con 'details' de todas las métricas).
    """
    url = f"{BASE_TPAPI}/metrics/v3/athletes/{athlete_id}/consolidatedtimedmetrics/{start_date}/{end_date}"
    return _fetch_json(page, url)


def extract_weight_history(consolidated_metrics, metric_type=METRIC_TYPE_WEIGHT):
    """
    Filtra el historial de peso (type 9) del JSON crudo de consolidatedtimedmetrics.
    Devuelve una lista de dicts {"fecha": date, "peso_kg": float, "peso_lb": float},
    ordenada cronológicamente (más antiguo -> más reciente), lista para pasarle
    directo a phase_engine.update_phase().
    """
    entries = []
    for day in consolidated_metrics:
        for detail in day.get("details", []):
            if detail.get("type") == metric_type:
                value = detail.get("value")
                if value is None:
                    continue
                fecha_str = detail.get("time") or day.get("timeStamp")
                fecha = datetime.fromisoformat(fecha_str).date()
                entries.append({
                    "fecha": fecha,
                    "peso_kg": float(value),
                    "peso_lb": round(float(value) * KG_TO_LB, 2),
                })

    entries.sort(key=lambda e: e["fecha"])
    return entries


def get_weight_history(page, athlete_id, weeks_back=6):
    """
    Atajo: pide el rango de fechas necesario y devuelve el historial de peso
    ya parseado, en el formato que espera phase_engine.py.
    """
    end_date = datetime.now().date()
    start_date = end_date - timedelta(weeks=weeks_back)
    raw = get_consolidated_metrics(
        page, athlete_id,
        start_date.strftime("%Y-%m-%d"),
        end_date.strftime("%Y-%m-%d"),
    )
    return extract_weight_history(raw)


# ---------------------------------------------------------------------------
# Entrenos planificados
# ---------------------------------------------------------------------------

def get_planned_workouts_raw(page, athlete_id, start_date, end_date):
    """
    GET /fitness/v7/athletes/{athleteId}/workouts/{start}/{end}
    start_date/end_date: strings "YYYY-MM-DD"
    """
    url = f"{BASE_TPAPI}/fitness/v7/athletes/{athlete_id}/workouts/{start_date}/{end_date}"
    return _fetch_json(page, url)


def classify_intensity(planned_if, duration_min):
    """
    Clasifica la sesión en una de las bandas que usa workout_kcal.MET_TABLE,
    en base al IF planificado y la duración.
    """
    if duration_min >= 150:
        return "fondo"
    if planned_if is not None and planned_if >= 0.80:
        return "intervalos"
    if planned_if is not None and planned_if >= 0.65:
        return "moderado"
    return "suave"


def compute_planned_if(tss_planned, duration_min):
    """
    IF = sqrt(TSS / (horas * 100)), despejado de la fórmula estándar:
    TSS = (horas * IF^2) * 100
    """
    if not tss_planned or not duration_min:
        return None
    hours = duration_min / 60
    if hours <= 0:
        return None
    try:
        return round((tss_planned / (hours * 100)) ** 0.5, 3)
    except ValueError:
        return None


def extract_planned_workouts_by_day(raw_workouts, start_date, end_date, workout_type_map=None):
    """
    Convierte la lista cruda de workouts de TP al formato que espera
    workout_kcal.estimate_week_kcal():
        [{"dia": "lunes", "sesiones": [{"sport":, "intensidad":, "duration_min":, "planned_if":}, ...]}, ...]

    Solo incluye entrenos PLANIFICADOS (no completados), agrupados por día
    de la semana en español — y SOLO para los días cuya fecha real cae
    dentro de [start_date, end_date]. Si la corrida es de miércoles a
    domingo, no se generan entradas falsas de lunes/martes (que ya pasaron
    y no forman parte de esta corrida).
    """
    workout_type_map = workout_type_map or WORKOUT_TYPE_MAP
    dias_es = ["lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo"]

    dias_en_rango = []
    fecha_cursor = start_date
    while fecha_cursor <= end_date:
        dias_en_rango.append(dias_es[fecha_cursor.weekday()])
        fecha_cursor += timedelta(days=1)

    by_day = {d: [] for d in dias_en_rango}

    for w in raw_workouts:
        tss_planned = w.get("tssPlanned")
        duration_planned = w.get("totalTimePlanned")  # normalmente en horas decimales
        if duration_planned is None:
            continue
        duration_min = duration_planned * 60

        workout_type_id = w.get("workoutTypeValueId")
        sport = workout_type_map.get(workout_type_id, "bike")
        if sport is None:
            continue  # Día libre / descanso - no genera sesión

        planned_if = compute_planned_if(tss_planned, duration_min)
        intensidad = classify_intensity(planned_if, duration_min)

        fecha_str = w.get("workoutDay") or w.get("date")
        if not fecha_str:
            continue
        fecha = datetime.fromisoformat(fecha_str[:10]).date()
        if fecha < start_date or fecha > end_date:
            continue  # fuera del rango de esta corrida (ej. ya pasó)
        dia_semana = dias_es[fecha.weekday()]

        by_day[dia_semana].append({
            "sport": sport,
            "intensidad": intensidad,
            "duration_min": round(duration_min),
            "planned_if": planned_if,
        })

    return [{"dia": d, "sesiones": by_day[d]} for d in dias_en_rango]


def get_planned_workouts_week(page, athlete_id, start_date=None):
    """
    Atajo: pide los entrenos planificados y los devuelve ya parseados en
    el formato de workout_kcal.py.

    - Corrida normal de producción (sábado, vía el scheduler): arma la
      semana COMPLETA que viene, lunes a domingo.
    - Corrida forzada cualquier otro día (--run-now para probar): arma
      SOLO el resto de ESTA semana, de hoy al domingo — nunca salta a la
      semana siguiente, para no mostrar días vacíos de una semana que
      quizás el coach ni ha planificado todavía.
    """
    if start_date is None:
        today = datetime.now().date()
        if today.weekday() == 5:  # sábado — corrida de producción normal
            start_date = today + timedelta(days=2)  # próximo lunes
            end_date = start_date + timedelta(days=6)  # ese domingo
        else:  # corrida forzada cualquier otro día — resto de esta semana
            start_date = today
            dias_hasta_domingo = 6 - today.weekday()  # lunes=0 ... domingo=6
            end_date = today + timedelta(days=dias_hasta_domingo)
    else:
        end_date = start_date + timedelta(days=6)

    raw = get_planned_workouts_raw(
        page, athlete_id,
        start_date.strftime("%Y-%m-%d"),
        end_date.strftime("%Y-%m-%d"),
    )
    return extract_planned_workouts_by_day(raw, start_date, end_date)
