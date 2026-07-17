"""
pdf_builder.py
Genera el PDF semanal del plan SmartFuel: un bloque por día con kcal objetivo,
resumen del entreno, y el desglose de comidas con cantidades.
"""
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

DIAS_ES = ["lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo"]
DIAS_DISPLAY = {
    "lunes": "LUNES", "martes": "MARTES", "miercoles": "MIÉRCOLES",
    "jueves": "JUEVES", "viernes": "VIERNES", "sabado": "SÁBADO", "domingo": "DOMINGO",
}

BRAND_ORANGE = colors.HexColor("#E8722C")
BRAND_DARK = colors.HexColor("#1B2A4A")

UNIT_SYMBOL = {"gramos": "g", "ml": "ml", "unidad": "ud"}


def _componentes_str(meal):
    parts = []
    for c in meal["componentes"]:
        if c["unidad"] == "porcion":
            parts.append(c["nombre"])
            continue
        symbol = UNIT_SYMBOL.get(c["unidad"], c["unidad"])
        parts.append(f"{c['nombre']} {c['cantidad']}{symbol}")
    return ", ".join(parts)


def build_weekly_pdf(output_path, athlete_name, week_label, daily_targets,
                      daily_plans, daily_burn=None, phase_info=None):
    """
    daily_targets: {dia: kcal_objetivo}
    daily_plans: {dia: {slot: meal_dict}}  (viene de meal_planner.build_daily_meal_plan)
    daily_burn: {dia: kcal_quemadas_estimadas} (opcional, para mostrar contexto)
    phase_info: dict con fase_actual/kcal_actual (opcional)
    """
    doc = SimpleDocTemplate(
        output_path, pagesize=letter,
        topMargin=0.6 * inch, bottomMargin=0.6 * inch,
        leftMargin=0.6 * inch, rightMargin=0.6 * inch,
    )
    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "SmartFuelTitle", parent=styles["Title"],
        textColor=BRAND_ORANGE, fontSize=22, spaceAfter=2,
    )
    subtitle_style = ParagraphStyle(
        "SmartFuelSubtitle", parent=styles["Normal"],
        textColor=BRAND_DARK, fontSize=11, spaceAfter=16,
    )
    day_header_style = ParagraphStyle(
        "DayHeader", parent=styles["Heading2"],
        textColor=colors.white, fontSize=13, leading=16,
    )
    slot_label_style = ParagraphStyle(
        "SlotLabel", parent=styles["Normal"], fontSize=9,
        textColor=BRAND_DARK, fontName="Helvetica-Bold",
    )
    slot_value_style = ParagraphStyle(
        "SlotValue", parent=styles["Normal"], fontSize=9, leading=12,
    )

    story = []
    story.append(Paragraph("SMARTFUEL", title_style))
    story.append(Paragraph(
        f"{athlete_name} &nbsp;|&nbsp; Semana del {week_label}", subtitle_style
    ))

    if phase_info:
        story.append(Paragraph(
            f"Fase {phase_info.get('fase_actual')} — "
            f"{phase_info.get('kcal_actual')} kcal promedio/día",
            subtitle_style
        ))

    for dia in DIAS_ES:
        if dia not in daily_targets:
            continue

        kcal_obj = daily_targets[dia]
        burn = (daily_burn or {}).get(dia, 0)
        entreno_txt = f"Entreno: ~{burn} kcal estimadas" if burn else "Día de descanso"

        header_data = [[
            Paragraph(f"{DIAS_DISPLAY.get(dia, dia.upper())} — {kcal_obj} kcal", day_header_style),
            Paragraph(entreno_txt, ParagraphStyle(
                "EntrenoTxt", parent=styles["Normal"], textColor=colors.white,
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

        plan = daily_plans.get(dia) or {}
        main_slots = ["desayuno", "almuerzo", "merienda", "cena"]
        slot_display = {
            "desayuno": "Desayuno", "almuerzo": "Almuerzo", "merienda": "Merienda",
            "cena": "Cena",
        }

        rows = []
        for slot in main_slots:
            meal = plan.get(slot)
            if not meal:
                continue
            opcion_a = meal.get("opcion_a")
            opcion_b = meal.get("opcion_b")
            valor_kcal = f"{opcion_a['kcal_total']:.0f} kcal" if opcion_a else ""
            texto = f"<b>A:</b> {_componentes_str(opcion_a)}" if opcion_a else ""
            if opcion_b and opcion_b is not opcion_a:
                texto += f"<br/><b>B:</b> {_componentes_str(opcion_b)}"
            rows.append([
                Paragraph(slot_display.get(slot, slot), slot_label_style),
                Paragraph(texto, slot_value_style),
                Paragraph(valor_kcal, slot_value_style),
            ])

        if rows:
            meal_table = Table(rows, colWidths=[1.5 * inch, 4.3 * inch, 0.9 * inch])
            meal_table.setStyle(TableStyle([
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#DDDDDD")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.white, colors.HexColor("#F7F7F7")]),
            ]))
            story.append(meal_table)
        else:
            story.append(Paragraph("(sin plan armado para este día)", slot_value_style))

        # Bloque de fuel de entreno de bici (pre / intra / post), si aplica
        fuel_rows = []
        if plan.get("pre_entreno"):
            fuel_rows.append([
                Paragraph("Antes de entrenar", slot_label_style),
                Paragraph(_componentes_str(plan["pre_entreno"]), slot_value_style),
                Paragraph(f"{plan['pre_entreno']['kcal_total']:.0f} kcal", slot_value_style),
            ])
        if plan.get("intra_entreno"):
            fuel_rows.append([
                Paragraph("Durante el entreno", slot_label_style),
                Paragraph(plan["intra_entreno"]["texto"], slot_value_style),
                Paragraph("", slot_value_style),
            ])
        if plan.get("post_entreno"):
            fuel_rows.append([
                Paragraph("Después de entrenar", slot_label_style),
                Paragraph(_componentes_str(plan["post_entreno"]), slot_value_style),
                Paragraph(f"{plan['post_entreno']['kcal_total']:.0f} kcal", slot_value_style),
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

        story.append(Spacer(1, 14))

    doc.build(story)
    return output_path
