from __future__ import annotations

from email.message import EmailMessage
import logging
import os
import smtplib
from collections.abc import Iterable


logger = logging.getLogger(__name__)


def _smtp_port() -> int:
    try:
        return int(os.getenv("SMTP_PORT", "587"))
    except ValueError:
        logger.warning("SMTP_PORT invalido; usando porta 587")
        return 587


def _smtp_timeout() -> float:
    try:
        return float(os.getenv("SMTP_TIMEOUT", "15"))
    except ValueError:
        logger.warning("SMTP_TIMEOUT invalido; usando 15s")
        return 15.0


def _normalize_recipients(recipients: str | Iterable[str]) -> list[str]:
    if isinstance(recipients, str):
        return [recipients.strip()] if recipients.strip() else []
    return [recipient.strip() for recipient in recipients if recipient.strip()]


def send_email(
    recipients: str | Iterable[str],
    subject: str,
    body: str,
    *,
    html: str | None = None,
) -> bool:
    smtp_user = os.getenv("SMTP_USER", "").strip()
    if not smtp_user:
        logger.error(
            "SMTP_USER nao configurado; email NAO enviado. "
            "Defina SMTP_USER e SMTP_PASSWORD no ambiente do servico."
        )
        return False

    to_addrs = _normalize_recipients(recipients)
    if not to_addrs:
        logger.warning("Nenhum destinatario informado; email ignorado.")
        return False

    smtp_host = os.getenv("SMTP_HOST", "smtp.office365.com")
    smtp_password = os.getenv("SMTP_PASSWORD", "")
    smtp_from = os.getenv("SMTP_FROM", smtp_user)
    use_tls = os.getenv("SMTP_TLS", "true").strip().lower() not in {"0", "false", "no", "nao"}

    message = EmailMessage()
    message["From"] = smtp_from
    message["To"] = ", ".join(to_addrs)
    message["Subject"] = subject
    message.set_content(body)
    if html:
        message.add_alternative(html, subtype="html")

    with smtplib.SMTP(smtp_host, _smtp_port(), timeout=_smtp_timeout()) as smtp:
        if use_tls:
            smtp.starttls()
        if smtp_password:
            smtp.login(smtp_user, smtp_password)
        smtp.send_message(message)

    return True
