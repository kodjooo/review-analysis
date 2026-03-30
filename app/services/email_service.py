from __future__ import annotations

import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from logging import Logger

from app.core.config import Settings
from app.core.models import EmailMessage


class EmailService:
    def __init__(self, settings: Settings, logger: Logger) -> None:
        self.settings = settings
        self.logger = logger

    def send(self, message: EmailMessage) -> None:
        if not self.settings.smtp_host or not self.settings.smtp_recipients:
            self.logger.warning("SMTP не настроен, отправка письма пропущена.")
            return

        mime_message = MIMEMultipart("alternative")
        mime_message["Subject"] = message.subject
        mime_message["From"] = self.settings.smtp_sender or self.settings.smtp_username
        mime_message["To"] = ", ".join(self.settings.smtp_recipients)
        mime_message.attach(MIMEText(message.plain_text, "plain", "utf-8"))
        mime_message.attach(MIMEText(message.html, "html", "utf-8"))

        with smtplib.SMTP(self.settings.smtp_host, self.settings.smtp_port, timeout=30) as server:
            if self.settings.smtp_use_tls:
                server.starttls()
            if self.settings.smtp_username:
                server.login(self.settings.smtp_username, self.settings.smtp_password)
            server.sendmail(
                from_addr=mime_message["From"],
                to_addrs=self.settings.smtp_recipients,
                msg=mime_message.as_string(),
            )
        self.logger.info("Письмо отправлено получателям: %s", self.settings.smtp_recipients)
