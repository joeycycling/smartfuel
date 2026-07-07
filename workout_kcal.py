"""
workout_kcal.py
Estima el gasto calórico de una sesión planificada (leída de TrainingPeaks).
"""

MET_TABLE = {
    "suave":      {"bike": 6,  "run": 8,  "swim": 6, "gym": 5},
    "moderado":   {"bike": 8,  "run": 10, "swim": 8, "gym": 6},
    "intervalos": {"bike": 10, "run": 12, "swim": 10, "gym": 7},
    "fondo":      {"bike": 9,  "run": 11, "swim": 9,  "gym": 6},
}


def estimate_workout_kcal(sport, intensidad, duration_min, athlete_weight_kg,
                           tiene_potometro=False, ftp_watts=None, planned_if=None):
    """
    Bici + potómetro (+ FTP e IF planificado disponibles):
        usa la fórmula de kJ de trabajo (~1:1 con kcal a ~24% eficiencia metabólica).
    Todo lo demás (run/swim/gym, o bici sin potómetro):
        usa estimado por MET (peso del atleta x MET x horas).
    """
    if sport == "bike" and tiene_potometro and ftp_watts and planned_if:
        planned_power = planned_if * ftp_watts
        kcal = planned_power * (duration_min / 60) * 3.6
    else:
        met = MET_TABLE.get(intensidad, MET_TABLE["moderado"]).get(sport, 7)
        kcal = met * athlete_weight_kg * (duration_min / 60)

    return round(kcal)


def estimate_week_kcal(workouts, athlete_weight_kg, tiene_potometro, ftp_watts):
    """
    workouts: lista de dicts, uno por día:
      {"dia": "lunes", "sesiones": [{"sport":.., "intensidad":.., "duration_min":.., "planned_if":..}, ...]}
    Devuelve dict {dia: kcal_quemadas_ese_dia}
    """
    daily_burn = {}
    for day in workouts:
        total = sum(
            estimate_workout_kcal(
                s["sport"], s["intensidad"], s["duration_min"],
                athlete_weight_kg, tiene_potometro, ftp_watts, s.get("planned_if")
            )
            for s in day["sesiones"]
        )
        daily_burn[day["dia"]] = total
    return daily_burn
