import asyncio
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from config import settings


async def send_email(to: str, subject: str, body_html: str) -> None:
    """Надсилає email асинхронно (SMTP в thread pool).
    Якщо SMTP не налаштований — мовчки пропускає.
    """
    if not settings.smtp_user:
        return
    try:
        await asyncio.to_thread(_send_sync, to, subject, body_html)
    except Exception as e:
        # Не падаємо через email — тільки логуємо
        print(f"[email] Помилка надсилання на {to}: {e}")


def _send_sync(to: str, subject: str, body_html: str) -> None:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = settings.smtp_from
    msg["To"]      = to
    msg.attach(MIMEText(body_html, "html"))

    context = ssl.create_default_context()
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
        server.starttls(context=context)
        server.login(settings.smtp_user, settings.smtp_password)
        server.sendmail(settings.smtp_from, to, msg.as_string())
