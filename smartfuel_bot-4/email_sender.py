"""
email_sender.py
Envía el PDF semanal por correo usando el SMTP estándar de GoDaddy
Workspace Email (mismo servidor para cualquier buzón @tudominio.com).

Variables de entorno esperadas:
    EMAIL_USER      - ej. info@joeycycling.com
    EMAIL_PASSWORD  - contraseña del buzón (no la de la cuenta GoDaddy general)
"""
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication

SMTP_HOST = "smtpout.secureserver.net"
SMTP_PORT = 465  # SSL directo (alternativa: 587 con STARTTLS si 465 falla)


def send_weekly_plan_email(athlete_name, athlete_email, pdf_path, week_label):
    """
    Envía el PDF del plan semanal al correo del atleta.
    """
    user = os.environ["EMAIL_USER"]
    password = os.environ["EMAIL_PASSWORD"]

    msg = MIMEMultipart()
    msg["From"] = user
    msg["To"] = athlete_email
    msg["Subject"] = f"Tu plan SmartFuel de la semana — {week_label}"

    body = (
        f"Hola {athlete_name},\n\n"
        f"Aquí tienes tu plan nutricional de la semana, con las cantidades "
        f"y porciones ajustadas a tus entrenamientos de cada día.\n\n"
        f"Cualquier duda, escríbeme.\n\n"
        f"Joey Martí\n"
        f"Cycling Coach — CircuitCycling"
    )
    msg.attach(MIMEText(body, "plain"))

    with open(pdf_path, "rb") as f:
        part = MIMEApplication(f.read(), _subtype="pdf")
        part.add_header(
            "Content-Disposition", "attachment",
            filename=os.path.basename(pdf_path)
        )
        msg.attach(part)

    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as server:
        server.login(user, password)
        server.sendmail(user, athlete_email, msg.as_string())
