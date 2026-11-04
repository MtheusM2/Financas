import json
import smtplib
from email.message import EmailMessage

from app.core.config import get_settings
from app.core.tracing import logger

# Usado pelos testes quando EMAIL_BACKEND=memory.
outbox: list[dict] = []


def send_email(to: str, subject: str, body: str) -> None:
    settings = get_settings()
    if settings.email_backend == "memory":
        outbox.append({"to": to, "subject": subject, "body": body})
        return
    if settings.email_backend == "file":  # somente nos testes de ponta a ponta
        with open(settings.email_file, "a", encoding="utf-8") as file:
            file.write(json.dumps({"to": to, "body": body}) + "\n")
        return
    message = EmailMessage()
    message["From"] = settings.smtp_from or settings.smtp_user
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as smtp:
        smtp.starttls()
        smtp.login(settings.smtp_user, settings.smtp_password)
        smtp.send_message(message)
    logger.info("email enviado")
