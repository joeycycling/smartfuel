"""
phase_store.py
Guarda/lee el estado de fase de cada atleta (fase actual, kcal, fecha del
último cambio) en un archivo JSON local.

*** ADVERTENCIA IMPORTANTE ***
Railway borra el sistema de archivos en cada redeploy. Esto significa que
si usas Railway y redepliegas el servicio, este archivo se resetea y el
bot "olvida" en qué fase iba cada atleta (empezaría de fase 1 otra vez).

Esto sirve para probar el bot HOY, pero antes de dejarlo en producción
de forma permanente, hay que mover este estado a algo persistente:
- Un volumen de Railway (Railway Volumes, se puede montar en /data)
- O una pestaña más en el Google Sheet (Historial_Fases), leyendo/escribiendo
  con la API de Google Sheets
"""
import json
import os
from datetime import date, datetime

STORE_PATH = os.path.join(os.path.dirname(__file__), "phase_state.json")


def _load_all():
    if not os.path.exists(STORE_PATH):
        return {}
    with open(STORE_PATH, "r") as f:
        raw = json.load(f)
    # convertir fecha de string a date
    for athlete_id, state in raw.items():
        state["fecha_ultimo_cambio"] = datetime.fromisoformat(
            state["fecha_ultimo_cambio"]
        ).date()
    return raw


def _save_all(all_states):
    serializable = {}
    for athlete_id, state in all_states.items():
        s = dict(state)
        s["fecha_ultimo_cambio"] = s["fecha_ultimo_cambio"].isoformat()
        serializable[athlete_id] = s
    with open(STORE_PATH, "w") as f:
        json.dump(serializable, f, indent=2)


def get_phase_state(athlete_id, default_kcal=2000):
    """
    Devuelve el phase_state del atleta, o crea uno inicial (fase 1) si no existe.
    """
    all_states = _load_all()
    if athlete_id in all_states:
        return all_states[athlete_id]

    return {
        "atleta_id": athlete_id,
        "fase_actual": 1,
        "kcal_actual": default_kcal,
        "fecha_ultimo_cambio": date.today(),
    }


def save_phase_state(athlete_id, phase_state):
    all_states = _load_all()
    all_states[athlete_id] = phase_state
    _save_all(all_states)
