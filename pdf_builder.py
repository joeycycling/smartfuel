"""
pdf_builder.py
Genera el PDF semanal del plan SmartFuel:
  1. Portada estilo "Planificación Alimenticia" (datos del atleta + historial de fases)
  2. Un bloque por día con kcal objetivo, resumen del entreno, y comidas (2 opciones c/u)
  3. Hoja de referencia "Training Fuel" (pre/intra/post-entreno)
"""
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

from meal_planner import PRE_WORKOUT_OPTIONS, POST_WORKOUT_OPTIONS, BIKE_CHO_PER_HOUR

DIAS_ES = ["lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo"]
DIAS_DISPLAY = {
    "lunes": "LUNES", "martes": "MARTES", "miercoles": "MIÉRCOLES",
    "jueves": "JUEVES", "viernes": "VIERNES", "sabado": "SÁBADO", "domingo": "DOMINGO",
}

BRAND_ORANGE = colors.HexColor("#E8722C")
BRAND_DARK = colors.HexColor("#1B2A4A")

UNIT_SYMBOL = {"gramos": "g", "ml": "ml", "unidad": "ud"}


def cm_to_feet_inches(cm):
    """Convierte cm a formato pies'pulgadas" (ej. 180 -> 5'11")."""
    if not cm:
        return "—"
    total_inches = cm / 2.54
    feet = int(total_inches // 12)
    inches = round(total_inches - feet * 12)
    if inches == 12:
        feet += 1
        inches = 0
    return f"{feet}'{inches}\""


def _componentes_str(meal):
    parts = []
    for c in meal["componentes"]:
        if c["unidad"] == "porcion":
            parts.append(c["nombre"])
            continue
        symbol = UNIT_SYMBOL.get(c["unidad"], c["unidad"])
        parts.append(f"{c['nombre']} {c['cantidad']}{symbol}")
    return ", ".join(parts)


def _meal_macros(meal):
    """Suma proteína/carbos/grasa de los componentes de una comida."""
    p = sum(c.get("proteina_g", 0) for c in meal["componentes"])
    c_ = sum(c.get("carbohidratos_g", 0) for c in meal["componentes"])
    f = sum(c.get("grasa_g", 0) for c in meal["componentes"])
    return p, c_, f


# Tips cortos que rotan al pie de cada hoja de día, para que no se vea tan plano
DAILY_TIPS = [
    "Hidrátate bien durante el día, no solo durante el entreno.",
    "Prioriza dormir 7-8 horas — la recuperación también es parte del plan.",
    "Si tienes hambre entre comidas, una fruta es mejor opción que saltarte una comida.",
    "La sal también se pierde sudando — no le tengas miedo en comidas post-entreno largo.",
    "Consistencia > perfección. Un día que no cuadre exacto no arruina la semana.",
    "Mastica despacio — ayuda a la digestión antes y después de entrenar.",
    "Si un día no puedes seguir el plan al pie de la letra, prioriza llegar a la proteína del día.",
]


def _styles():
    styles = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("SmartFuelTitle", parent=styles["Title"],
                                 textColor=BRAND_ORANGE, fontSize=26, spaceAfter=2),
        "subtitle": ParagraphStyle("SmartFuelSubtitle", parent=styles["Normal"],
                                    textColor=BRAND_DARK, fontSize=12, spaceAfter=16),
        "section_header": ParagraphStyle("SectionHeader", parent=styles["Heading2"],
                                          textColor=BRAND_ORANGE, fontSize=14, spaceBefore=14, spaceAfter=6),
        "day_header": ParagraphStyle("DayHeader", parent=styles["Heading2"],
                                      textColor=colors.white, fontSize=13, leading=16),
        "slot_label": ParagraphStyle("SlotLabel", parent=styles["Normal"], fontSize=9,
                                      textColor=BRAND_DARK, fontName="Helvetica-Bold"),
        "slot_value": ParagraphStyle("SlotValue", parent=styles["Normal"], fontSize=9, leading=12),
        "cover_label": ParagraphStyle("CoverLabel", parent=styles["Normal"], fontSize=11,
                                       textColor=BRAND_ORANGE, fontName="Helvetica-Bold"),
        "cover_value": ParagraphStyle("CoverValue", parent=styles["Normal"], fontSize=11,
                                       textColor=BRAND_DARK),
        "small_note": ParagraphStyle("SmallNote", parent=styles["Normal"], fontSize=8,
                                      textColor=colors.HexColor("#666666")),
    }


def _build_cover_page(athlete_name, athlete_info, st):
    """
    Portada estilo tu PDF original: datos del atleta + tabla de historial
    de fases (peso/kcal en cada cambio), con la etiqueta de objetivo en
    vez de números de fase.
    """
    story = [
        Paragraph("SMARTFUEL", st["title"]),
        Paragraph("PLANIFICACIÓN ALIMENTICIA", st["subtitle"]),
        Spacer(1, 10),
    ]

    info_rows = [
        [Paragraph("NOMBRE:", st["cover_label"]), Paragraph(athlete_name, st["cover_value"])],
        [Paragraph("EDAD:", st["cover_label"]), Paragraph(str(athlete_info.get("edad", "—")), st["cover_value"])],
        [Paragraph("ESTATURA:", st["cover_label"]), Paragraph(cm_to_feet_inches(athlete_info.get("estatura_cm")), st["cover_value"])],
        [Paragraph("PESO INICIAL:", st["cover_label"]),
         Paragraph(f"{athlete_info.get('peso_inicial_lb', '—')} lbs ({athlete_info.get('fecha_inicio', '—')})", st["cover_value"])],
        [Paragraph("PESO ACTUAL:", st["cover_label"]),
         Paragraph(f"<b>{athlete_info.get('peso_actual_lb', '—')} lbs</b> ({athlete_info.get('fecha_actual', '—')})", st["cover_value"])],
    ]
    info_table = Table(info_rows, colWidths=[1.8 * inch, 3.5 * inch])
    info_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F2F2F2")),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#CCCCCC")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(info_table)
    story.append(Spacer(1, 20))

    header = ["FASE", "FECHA", "PESO", "KCAL", "COMENTARIOS"]
    hist_cell_style = ParagraphStyle("HistCell", parent=getSampleStyleSheet()["Normal"], fontSize=8, leading=10)
    hist_header_style = ParagraphStyle("HistHeader", parent=getSampleStyleSheet()["Normal"],
                                        fontSize=8, leading=10, textColor=colors.white, fontName="Helvetica-Bold")
    hist_rows = [[Paragraph(h, hist_header_style) for h in header]]
    for entry in athlete_info.get("historial", []):
        hist_rows.append([
            Paragraph(entry.get("objetivo_label", ""), hist_cell_style),
            Paragraph(str(entry.get("fecha", "")), hist_cell_style),
            Paragraph(f"{entry.get('peso_lb', '')} lbs", hist_cell_style),
            Paragraph(f"{entry.get('kcal', '')} kcal", hist_cell_style),
            Paragraph(entry.get("razon", ""), hist_cell_style),
        ])

    hist_table = Table(hist_rows, colWidths=[1.1 * inch, 0.75 * inch, 0.7 * inch, 0.7 * inch, 2.45 * inch])
    hist_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), BRAND_DARK),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#DDDDDD")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F7F7F7")]),
    ]))
    story.append(hist_table)
    story.append(PageBreak())
    return story


def _section_banner(text, st):
    """Barra de sección con el mismo estilo de marca que los headers de día."""
    t = Table([[Paragraph(text, ParagraphStyle(
        "BannerText", parent=getSampleStyleSheet()["Heading2"],
        textColor=colors.white, fontSize=12, leading=15,
    ))]], colWidths=[6.7 * inch])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), BRAND_DARK),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    return t


def _build_training_fuel_page(daily_plans, daily_burn, st):
    """
    Hoja de referencia de Training Fuel (pre/intra/post-entreno), con las
    opciones fijas + la recomendación específica de esta semana para cada
    día de bici (grs/hora reales según su entreno planificado).
    """
    story = [
        Paragraph("SMARTFUEL", st["title"]),
        Paragraph("TRAINING FUEL — Referencia de nutrición para tus entrenos", st["subtitle"]),
        Spacer(1, 4),
    ]

    story.append(_section_banner("PRE-ENTRENO &nbsp;·&nbsp; 15-35min antes", st))
    story.append(Spacer(1, 4))
    story.append(Paragraph("Carbohidratos fáciles de digerir + algo de proteína. Elige una opción:", st["small_note"]))
    story.append(Spacer(1, 4))
    rows = [["Opción", "PRO", "CHO", "GRASA", "KCAL"]]
    for opt in PRE_WORKOUT_OPTIONS:
        rows.append([opt["nombre"], f"{opt['proteina_g']}g", f"{opt['carbohidratos_g']}g",
                     f"{opt['grasa_g']}g", f"{opt['kcal']}kcal"])
    t = Table(rows, colWidths=[3.9 * inch, 0.6 * inch, 0.6 * inch, 0.7 * inch, 0.9 * inch])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), BRAND_ORANGE),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ALIGN", (1, 0), (-1, -1), "CENTER"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#DDDDDD")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F7F7F7")]),
        ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(t)
    story.append(Spacer(1, 16))

    story.append(_section_banner("INTRA-ENTRENO &nbsp;·&nbsp; durante la bici", st))
    story.append(Spacer(1, 4))
    rows = [["Intensidad", "CHO por hora"]]
    for banda, (lo, hi) in BIKE_CHO_PER_HOUR.items():
        rows.append([banda.capitalize(), f"{lo}-{hi}g/hr"])
    t = Table(rows, colWidths=[3.35 * inch, 3.35 * inch])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), BRAND_ORANGE),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ALIGN", (1, 0), (-1, -1), "CENTER"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#DDDDDD")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F7F7F7")]),
        ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(t)

    personal_rows = []
    personal_label_style = ParagraphStyle(
        "PersonalLabel", parent=getSampleStyleSheet()["Normal"], fontSize=9,
        textColor=BRAND_DARK, fontName="Helvetica-Bold",
    )
    personal_value_style = ParagraphStyle(
        "PersonalValue", parent=getSampleStyleSheet()["Normal"], fontSize=9, leading=12,
    )
    for dia in DIAS_ES:
        plan = daily_plans.get(dia) or {}
        if plan.get("intra_entreno"):
            personal_rows.append([
                Paragraph(DIAS_DISPLAY.get(dia, dia.upper()), personal_label_style),
                Paragraph(plan["intra_entreno"]["texto"], personal_value_style),
            ])

    if personal_rows:
        story.append(Spacer(1, 10))
        story.append(Paragraph("TU RECOMENDACIÓN ESPECÍFICA ESTA SEMANA", ParagraphStyle(
            "MiniHeader", parent=getSampleStyleSheet()["Normal"], fontSize=9,
            textColor=BRAND_ORANGE, fontName="Helvetica-Bold", spaceAfter=4,
        )))
        t = Table(personal_rows, colWidths=[1.2 * inch, 5.5 * inch])
        t.setStyle(TableStyle([
            ("BOX", (0, 0), (-1, -1), 0.75, BRAND_ORANGE),
            ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#FFD9B3")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.HexColor("#FFF3EA"), colors.white]),
        ]))
        story.append(t)

    story.append(Spacer(1, 16))
    story.append(_section_banner("POST-ENTRENO &nbsp;·&nbsp; recuperación", st))
    story.append(Spacer(1, 4))
    story.append(Paragraph("Snack simple de recuperación, no una comida completa. Elige una opción:", st["small_note"]))
    story.append(Spacer(1, 4))
    rows = [["Opción", "PRO", "CHO", "GRASA", "KCAL"]]
    for opt in POST_WORKOUT_OPTIONS:
        rows.append([opt["nombre"], f"{opt['proteina_g']}g", f"{opt['carbohidratos_g']}g",
                     f"{opt['grasa_g']}g", f"{opt['kcal']}kcal"])
    t = Table(rows, colWidths=[3.9 * inch, 0.6 * inch, 0.6 * inch, 0.7 * inch, 0.9 * inch])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), BRAND_ORANGE),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ALIGN", (1, 0), (-1, -1), "CENTER"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#DDDDDD")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F7F7F7")]),
        ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(t)

    return story


SPORT_DISPLAY = {"bike": "bici", "run": "running", "swim": "natación", "gym": "gym", "walk": "caminata"}


def _sesiones_resumen(sessions):
    partes = []
    for s in sessions:
        sport = SPORT_DISPLAY.get(s.get("sport"), s.get("sport", ""))
        partes.append(f"{sport} {s.get('intensidad', '')} ({s.get('duration_min', 0)}min)")
    return ", ".join(partes)


def _build_day_explanation(kcal_obj, avg_semanal, sessions):
    """
    Genera el texto explicando por qué el día tiene esas kcal específicas
    (comparado contra el promedio semanal y el entreno planificado de ese día).
    """
    diff = kcal_obj - avg_semanal
    if not sessions:
        return (
            f"Hoy es día de <b>descanso</b>, por eso tus kcal ({kcal_obj:.0f}) están por debajo "
            f"del promedio semanal ({avg_semanal:.0f}) — sin entreno, tu cuerpo gasta menos energía "
            f"y no necesita el extra de los días que sí entrenas."
        )

    resumen = _sesiones_resumen(sessions)
    if diff > 50:
        return (
            f"Hoy tienes <b>más kcal</b> que el promedio semanal ({kcal_obj:.0f} vs {avg_semanal:.0f} kcal) "
            f"porque tu entreno de hoy ({resumen}) exige más energía de lo habitual — "
            f"ese extra es para rendir bien durante la sesión y recuperar después."
        )
    elif diff < -50:
        return (
            f"Hoy tienes <b>menos kcal</b> que el promedio semanal ({kcal_obj:.0f} vs {avg_semanal:.0f} kcal) "
            f"porque tu entreno de hoy ({resumen}) es más corto o suave que el resto de la semana."
        )
    else:
        return (
            f"Hoy tu entreno ({resumen}) tiene un esfuerzo similar al promedio de la semana, "
            f"por eso tus kcal ({kcal_obj:.0f}) se mantienen cerca del promedio semanal ({avg_semanal:.0f})."
        )


def build_weekly_pdf(output_path, athlete_name, week_label, daily_targets,
                      daily_plans, daily_burn=None, phase_info=None, athlete_info=None,
                      sessions_by_day=None):
    """
    daily_targets: {dia: kcal_objetivo}
    daily_plans: {dia: {slot: meal_dict}}  (viene de meal_planner.build_daily_meal_plan)
    daily_burn: {dia: kcal_quemadas_estimadas} (opcional, para mostrar contexto)
    phase_info: dict con kcal_actual/objetivo_label (opcional)
    athlete_info: dict con edad, estatura_cm, peso_inicial_lb, fecha_inicio,
                  peso_actual_lb, fecha_actual, historial (para la portada)
    sessions_by_day: {dia: [sesiones]} (para explicar el por qué de las kcal)
    """
    sessions_by_day = sessions_by_day or {}
    doc = SimpleDocTemplate(
        output_path, pagesize=letter,
        topMargin=0.6 * inch, bottomMargin=0.6 * inch,
        leftMargin=0.6 * inch, rightMargin=0.6 * inch,
    )
    st = _styles()
    story = []

    if athlete_info:
        story.extend(_build_cover_page(athlete_name, athlete_info, st))

    context_line = f"Semana del {week_label}"
    if phase_info:
        context_line += f" &nbsp;·&nbsp; Fase {phase_info.get('objetivo_label', '')} ({phase_info.get('kcal_actual')} kcal prom/día)"

    dias_presentes = [d for d in DIAS_ES if d in daily_targets]
    for idx, dia in enumerate(dias_presentes):
        kcal_obj = daily_targets[dia]
        burn = (daily_burn or {}).get(dia, 0)
        entreno_txt = f"Entreno: ~{burn} kcal estimadas" if burn else "Día de descanso"

        header_left = Paragraph(
            f"<font size=8 color='#B8C2D9'>SMARTFUEL &nbsp;·&nbsp; {context_line}</font>"
            f"<br/><font size=14>{DIAS_DISPLAY.get(dia, dia.upper())} — {kcal_obj} kcal</font>",
            ParagraphStyle("HeaderLeft", parent=getSampleStyleSheet()["Normal"], textColor=colors.white, leading=16),
        )
        header_data = [[
            header_left,
            Paragraph(entreno_txt, ParagraphStyle(
                "EntrenoTxt", parent=getSampleStyleSheet()["Normal"], textColor=colors.white,
                fontSize=9, alignment=2,
            )),
        ]]
        header_table = Table(header_data, colWidths=[4.2 * inch, 2.5 * inch])
        header_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), BRAND_DARK),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 10),
            ("RIGHTPADDING", (0, 0), (-1, -1), 10),
            ("TOPPADDING", (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ]))
        story.append(header_table)
        story.append(Spacer(1, 10))

        plan = daily_plans.get(dia) or {}
        main_slots = ["desayuno", "almuerzo", "merienda", "cena"]
        slot_display = {
            "desayuno": "Desayuno", "almuerzo": "Almuerzo", "merienda": "Merienda",
            "cena": "Cena",
        }
        slot_colors = {
            "desayuno": colors.HexColor("#F2C14E"), "almuerzo": colors.HexColor("#5B8CE0"),
            "merienda": colors.HexColor("#6FBF73"), "cena": colors.HexColor("#8E6FBF"),
        }

        # --- Resumen de macros del día (suma de las Opciones A) ---
        tot_p = tot_c = tot_f = 0
        for slot in main_slots:
            meal = plan.get(slot)
            if meal and meal.get("opcion_a"):
                p, c_, f = _meal_macros(meal["opcion_a"])
                tot_p += p; tot_c += c_; tot_f += f

        stat_labels = ["KCAL", "PROTEÍNA", "CARBOHIDRATOS", "GRASA"]
        stat_values = [f"{kcal_obj:.0f}", f"{tot_p:.0f}g", f"{tot_c:.0f}g", f"{tot_f:.0f}g"]
        stat_row = Table([
            [Paragraph(v, ParagraphStyle("StatVal", parent=getSampleStyleSheet()["Normal"],
                                          fontSize=15, fontName="Helvetica-Bold", textColor=BRAND_ORANGE, alignment=1))
             for v in stat_values],
            [Paragraph(l, ParagraphStyle("StatLbl", parent=getSampleStyleSheet()["Normal"],
                                          fontSize=7, textColor=colors.HexColor("#666666"), alignment=1))
             for l in stat_labels],
        ], colWidths=[1.675 * inch] * 4)
        stat_row.setStyle(TableStyle([
            ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#DDDDDD")),
            ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#EEEEEE")),
            ("TOPPADDING", (0, 0), (-1, 0), 8), ("BOTTOMPADDING", (0, 0), (-1, 0), 2),
            ("TOPPADDING", (0, 1), (-1, 1), 0), ("BOTTOMPADDING", (0, 1), (-1, 1), 8),
        ]))
        story.append(stat_row)
        story.append(Spacer(1, 10))

        # Explicación de por qué el día tiene esas kcal específicas
        avg_semanal = (phase_info or {}).get("kcal_actual", kcal_obj)
        explicacion = _build_day_explanation(kcal_obj, avg_semanal, sessions_by_day.get(dia, []))
        expl_table = Table([[Paragraph(explicacion, st["slot_value"])]], colWidths=[6.7 * inch])
        expl_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F2F2F2")),
            ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#CCCCCC")),
            ("LEFTPADDING", (0, 0), (-1, -1), 10), ("RIGHTPADDING", (0, 0), (-1, -1), 10),
            ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ]))
        story.append(expl_table)
        story.append(Spacer(1, 10))

        rows = []
        row_slot_order = []
        for slot in main_slots:
            meal = plan.get(slot)
            if not meal:
                continue
            opcion_a = meal.get("opcion_a")
            opcion_b = meal.get("opcion_b")
            valor_kcal = f"{opcion_a['kcal_total']:.0f} kcal" if opcion_a else ""
            texto = f"<b>A:</b> {_componentes_str(opcion_a)}" if opcion_a else ""
            if opcion_b and opcion_b is not opcion_a:
                if opcion_b.get("nombre_plato"):
                    texto += f"<br/><b>B: {opcion_b['nombre_plato']}</b> — {_componentes_str(opcion_b)}"
                else:
                    texto += f"<br/><b>B:</b> {_componentes_str(opcion_b)}"
            rows.append([
                Paragraph(slot_display.get(slot, slot), st["slot_label"]),
                Paragraph(texto, st["slot_value"]),
                Paragraph(valor_kcal, st["slot_value"]),
            ])
            row_slot_order.append(slot)

        if rows:
            meal_table = Table(rows, colWidths=[1.5 * inch, 4.3 * inch, 0.9 * inch])
            meal_style = [
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#DDDDDD")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.white, colors.HexColor("#F7F7F7")]),
            ]
            for i, slot in enumerate(row_slot_order):
                meal_style.append(("LINEBEFORE", (0, i), (0, i), 3, slot_colors.get(slot, BRAND_ORANGE)))
            meal_table.setStyle(TableStyle(meal_style))
            story.append(meal_table)
        else:
            story.append(Paragraph("(sin plan armado para este día)", st["slot_value"]))

        fuel_rows = []
        if plan.get("pre_entreno"):
            fuel_rows.append([
                Paragraph("Antes de entrenar", st["slot_label"]),
                Paragraph(_componentes_str(plan["pre_entreno"]), st["slot_value"]),
                Paragraph(f"{plan['pre_entreno']['kcal_total']:.0f} kcal", st["slot_value"]),
            ])
        if plan.get("intra_entreno"):
            fuel_rows.append([
                Paragraph("Durante el entreno", st["slot_label"]),
                Paragraph(plan["intra_entreno"]["texto"], st["slot_value"]),
                Paragraph("", st["slot_value"]),
            ])
        if plan.get("post_entreno"):
            fuel_rows.append([
                Paragraph("Después de entrenar", st["slot_label"]),
                Paragraph(_componentes_str(plan["post_entreno"]), st["slot_value"]),
                Paragraph(f"{plan['post_entreno']['kcal_total']:.0f} kcal", st["slot_value"]),
            ])

        if fuel_rows:
            story.append(Spacer(1, 6))
            fuel_table = Table(fuel_rows, colWidths=[1.5 * inch, 4.3 * inch, 0.9 * inch])
            fuel_table.setStyle(TableStyle([
                ("GRID", (0, 0), (-1, -1), 0.5, BRAND_ORANGE),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.HexColor("#FFF3EA"), colors.white]),
            ]))
            story.append(fuel_table)

        story.append(Spacer(1, 12))
        tip = DAILY_TIPS[idx % len(DAILY_TIPS)]
        story.append(Paragraph(f"Tip: {tip}", ParagraphStyle(
            "TipFooter", parent=getSampleStyleSheet()["Normal"], fontSize=8,
            textColor=colors.HexColor("#888888"), fontName="Helvetica-Oblique",
        )))

        story.append(PageBreak())

    story.extend(_build_training_fuel_page(daily_plans, daily_burn, st))

    doc.build(story)
    return output_path
