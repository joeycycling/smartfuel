"""
feedback_loader.py
Lee el form semanal de feedback de los atletas (aparte del form de
preferencias inicial) y lo aplica como ajustes de OPCIONES de comida —
nunca kcal/macros, eso sigue siendo automático vía el algoritmo de peso.

Ajustes que sí aplica solo:
    - Alimentos que el atleta pide QUITAR -> se suman a alimentos_evitar
    - Alimentos que el atleta pide AGREGAR -> se marcan como preferidos
      (si ya existen en la base; si no, se listan para que el coach los
      agregue a la base de alimentos)
    - "Quiero más variedad" -> excluye los alimentos usados la semana
      pasada, para forzar combinaciones distintas esta semana
"""
import csv
import io
import urllib.request

from prefs_loader import parse_free_text_list


def fetch_feedback_csv(csv_url):
    """Descarga el CSV publicado del form de feedback semanal."""
    with urllib.request.urlopen(csv_url, timeout=15) as response:
        raw = response.read().decode("utf-8")
    return parse_feedback_csv(raw)


def parse_feedback_csv(csv_text):
    """
    Devuelve un dict {email_lowercase: feedback_dict} con la respuesta
    MÁS RECIENTE de cada atleta (Google Forms acumula todas las
    respuestas históricas, solo nos interesa la última de cada quien).
    """
    reader = csv.DictReader(io.StringIO(csv_text))
    por_email = {}

    for row in reader:
        email = None
        agregar = quitar = variedad = None
        for header, value in row.items():
            h = header.strip().lower()
            if "correo" in h or "email" in h:
                email = (value or "").strip().lower()
            elif "agregar" in h:
                agregar = value
            elif "quitar" in h or "evitar" in h or "quites" in h:
                quitar = value
            elif "variedad" in h:
                variedad = (value or "").strip().lower() in ("si", "sí", "yes")

        if not email:
            continue

        # Como el CSV viene ordenado por fecha de respuesta, la última
        # fila de cada email sobreescribe a la anterior — así siempre
        # queda la más reciente al final del loop.
        por_email[email] = {
            "alimentos_agregar": parse_free_text_list(agregar),
            "alimentos_quitar": parse_free_text_list(quitar),
            "quiere_variedad": bool(variedad),
        }

    return por_email
