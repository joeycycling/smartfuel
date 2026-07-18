"""
email_sender.py
Envía el PDF semanal por correo usando la API HTTPS de Resend
(https://resend.com), en vez de SMTP tradicional.

*** Por qué no usamos SMTP ***
Railway bloquea por completo los puertos SMTP salientes (25, 465, 587,
2525) en los planes Free/Trial/Hobby — solo el plan Pro los desbloquea.
Confirmado con la documentación oficial de Railway. La solución que
ellos mismos recomiendan es usar un servicio de email con API HTTPS
(Resend, SendGrid, Postmark, etc.), ya que el puerto 443 sí funciona
siempre.

Variables de entorno esperadas:
    RESEND_API_KEY   - API key de tu cuenta de Resend
    EMAIL_FROM       - remitente verificado en Resend
                       (ej. info@joeycycling.com una vez verifiques el
                       dominio ahí, o mientras tanto puedes usar
                       "onboarding@resend.dev" para probar sin verificar nada)
"""
import os
import json
import base64
import urllib.request

RESEND_API_URL = "https://api.resend.com/emails"


def send_weekly_plan_email(athlete_name, athlete_email, pdf_path, week_label):
    """
    Envía el PDF del plan semanal al correo del atleta vía la API de Resend.
    """
    api_key = os.environ["RESEND_API_KEY"]
    from_address = os.environ.get("EMAIL_FROM", "onboarding@resend.dev")

    body_text = (
        f"Hola {athlete_name},\n\n"
        f"Aquí tienes tu plan nutricional de la semana, con las cantidades "
        f"y porciones ajustadas a tus entrenamientos de cada día.\n\n"
        f"Cualquier duda, escríbeme.\n\n"
        f"Joey Martí\n"
        f"Cycling Coach — CircuitCycling"
    )

    with open(pdf_path, "rb") as f:
        pdf_base64 = base64.b64encode(f.read()).decode("utf-8")

    payload = {
        "from": from_address,
        "to": [athlete_email],
        "subject": f"Tu plan SmartFuel de la semana — {week_label}",
        "text": body_text,
        "attachments": [{
            "filename": os.path.basename(pdf_path),
            "content": pdf_base64,
        }],
    }

    req = urllib.request.Request(
        RESEND_API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    with urllib.request.urlopen(req, timeout=30) as response:
        if response.status not in (200, 201):
            raise Exception(f"Resend devolvió status {response.status}")
