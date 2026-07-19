"""
phase_store.py
Guarda/lee el estado de fase de cada atleta (fase actual, kcal, fecha del
último cambio), el peso/fecha de arranque del programa, y el historial
completo de cambios de fase (para mostrar en el PDF, como la tabla de
fases de tu PDF original).

*** ADVERTENCIA IMPORTANTE ***
Railway borra el sistema de archivos en cada redeploy. Esto significa que
si usas Railway y redepliegas el servicio, este archivo se resetea y el
bot "olvida" en qué fase iba cada atleta (empezaría de fase 1 otra vez,
y el historial/peso inicial también se perdería).

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
    for athlete_id, state in raw.items():
        state["fecha_ultimo_cambio"] = datetime.fromisoformat(state["fecha_ultimo_cambio"]).date()
        state["fecha_inicio"] = datetime.fromisoformat(state["fecha_inicio"]).date()
        for entry in state.get("historial", []):
            entry["fecha"] = datetime.fromisoformat(entry["fecha"]).date()
    return raw


def _save_all(all_states):
    serializable = {}
    for athlete_id, state in all_states.items():
        s = dict(state)
        s["fecha_ultimo_cambio"] = s["fecha_ultimo_cambio"].isoformat()
        s["fecha_inicio"] = s["fecha_inicio"].isoformat()
        s["historial"] = [
            {**entry, "fecha": entry["fecha"].isoformat()} for entry in s.get("historial", [])
        ]
        serializable[athlete_id] = s
    with open(STORE_PATH, "w") as f:
        json.dump(serializable, f, indent=2)


def get_phase_state(athlete_id, default_kcal=2000, peso_inicial_lb=None, fecha_inicio=None):
    """
    Devuelve el phase_state del atleta, o crea uno inicial (fase 1) si no existe.
    Si es la primera vez, guarda el peso inicial y la fecha de arranque —
    estos dos NUNCA cambian después, sin importar cuántas fases pasen.
    peso_inicial_lb / fecha_inicio: si el coach los puso manualmente en el
    sheet, se usan esos; si no, se usa el peso actual de TP y hoy.
    """
    all_states = _load_all()
    if athlete_id in all_states:
        return all_states[athlete_id]

    return {
        "atleta_id": athlete_id,
        "fase_actual": 1,
        "kcal_actual": default_kcal,
        "fecha_ultimo_cambio": date.today(),
        "fecha_inicio": fecha_inicio or date.today(),
        "peso_inicial_lb": peso_inicial_lb,
        "historial": [],
    }


def save_phase_state(athlete_id, phase_state):
    all_states = _load_all()
    all_states[athlete_id] = phase_state
    _save_all(all_states)


def append_historial_entry(phase_state, fecha, peso_lb, kcal, objetivo_label, razon):
    """
    Agrega una fila nueva al historial (solo cuando de verdad cambia la fase/kcal),
    igual que las filas F1, F2, F3... de tu PDF original.
    """
    phase_state.setdefault("historial", []).append({
        "fecha": fecha,
        "peso_lb": peso_lb,
        "kcal": kcal,
        "objetivo_label": objetivo_label,
        "razon": razon,
    })
    return phase_state
