"""
food_db.py
Carga y consulta la base de datos de alimentos de SmartFuel.
"""
import csv
import os

DEFAULT_CSV_PATH = os.path.join(os.path.dirname(__file__), "data", "alimentos.csv")


def load_food_db(csv_path=DEFAULT_CSV_PATH):
    """Carga el CSV de alimentos en un dict indexado por nombre (lowercase)."""
    db = {}
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = row["alimento"].strip()
            db[name.lower()] = {
                "categoria": row["categoria"].strip(),
                "nombre": name,
                "unidad_medida": row["unidad_medida"].strip(),  # "gramos" o "unidad"
                "cantidad_base": float(row["cantidad_base"]),
                "kcal": float(row["kcal"]),
                "proteina_g": float(row["proteina_g"]),
                "carbohidratos_g": float(row["carbohidratos_g"]),
                "grasa_g": float(row["grasa_g"]),
                "notas": row.get("notas", ""),
            }
    return db


def by_category(db, categoria):
    """Devuelve lista de alimentos de una categoría (ej. 'proteina', 'fruta')."""
    return [item for item in db.values() if item["categoria"] == categoria]


def get(db, nombre):
    """Busca un alimento por nombre exacto (case-insensitive)."""
    return db.get(nombre.lower())


def scale_food(item, target_amount):
    """
    Escala un alimento a una cantidad objetivo (gramos o unidades),
    devolviendo sus macros ajustados. Los alimentos por 'unidad'
    (huevos, pan, tortillas, etc.) se redondean a números enteros
    sensatos (mínimo 1) para que la porción tenga sentido real.
    """
    if item["unidad_medida"] == "unidad":
        target_amount = max(1, round(target_amount))

    factor = target_amount / item["cantidad_base"] if item["cantidad_base"] else 0
    return {
        "nombre": item["nombre"],
        "cantidad": round(target_amount, 1),
        "unidad": item["unidad_medida"],
        "kcal": round(item["kcal"] * factor, 1),
        "proteina_g": round(item["proteina_g"] * factor, 1),
        "carbohidratos_g": round(item["carbohidratos_g"] * factor, 1),
        "grasa_g": round(item["grasa_g"] * factor, 1),
    }
