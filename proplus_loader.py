"""
proplus_loader.py
Lee el sheet (más simple que el de preferencias) de atletas del plan
PRO+ — los que reciben solo la recomendación de nutrición para su
entreno (Training Fuel) cada semana, no el plan de comidas completo.

El sheet solo necesita 3 columnas: nombre, email, y el ID de TrainingPeaks
del atleta (para que el bot lea sus entrenos planificados de la semana).
No hace falta nada de edad/peso/altura/preferencias — eso solo lo usa el
plan completo.
"""
import csv
import io
import urllib.request


def normalize_header(header):
    """Detecta la columna por palabra clave, igual que prefs_loader.py,
    para no depender del texto exacto del encabezado en el sheet.
    Nombre/email se revisan primero para que "id" (columna del ID de
    TrainingPeaks, sin importar si el encabezado dice "ID", "ID Atleta"
    o "ID de TrainingPeaks") no se confunda con otra columna."""
    h = header.lower()
    if "nombre" in h:
        return "nombre"
    if "email" in h or "correo" in h:
        return "email"
    if "id" in h:
        return "id_atleta"
    return header


def load_proplus_from_csv(csv_text):
    """
    csv_text: contenido crudo del CSV publicado del sheet PRO+.
    Devuelve una lista de dicts {"nombre", "email", "id_atleta"}, uno
    por atleta, saltando filas sin ID de TrainingPeaks (no hay forma de
    generarle nada sin eso).
    """
    reader = csv.DictReader(io.StringIO(csv_text))
    results = []
    for row in reader:
        parsed = {}
        for header, value in row.items():
            if header is None:
                continue
            campo = normalize_header(header.strip())
            parsed[campo] = (value or "").strip()

        if not parsed.get("id_atleta"):
            continue

        results.append({
            "nombre": parsed.get("nombre") or "Atleta",
            "email": parsed.get("email") or "",
            "id_atleta": parsed.get("id_atleta"),
        })

    return results


def fetch_proplus_csv(csv_url):
    """Descarga el CSV publicado del sheet PRO+ y devuelve la lista ya parseada."""
    with urllib.request.urlopen(csv_url, timeout=15) as response:
        raw = response.read().decode("utf-8")
    return load_proplus_from_csv(raw)
