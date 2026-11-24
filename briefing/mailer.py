"""SMTP(기본: 네이버) 로 PDF 첨부 메일 발송."""
from __future__ import annotations

import logging
import os
import smtplib
import ssl
from email.message import EmailMessage
from pathlib import Path

log = logging.getLogger(__name__)


def mail_config() -> dict | None:
    cfg = {
        "host": os.getenv("SMTP_HOST", "smtp.naver.com"),
        "port": int(os.getenv("SMTP_PORT", "465")),
        "user": os.getenv("SMTP_USER", ""),
        "password": os.getenv("SMTP_PASSWORD", ""),
        "sender": os.getenv("MAIL_FROM", ""),
        "to": [x.strip() for x in os.getenv("MAIL_TO", "").split(",") if x.strip()],
    }
    if not (cfg["user"] and cfg["password"] and cfg["to"]):
        return None
    cfg["sender"] = cfg["sender"] or (cfg["user"] if "@" in cfg["user"] else f"{cfg['user']}@naver.com")
    return cfg


def send_report(subject: str, html_body: str, text_body: str, pdf_path: Path) -> bool:
    cfg = mail_config()
    if cfg is None:
        log.warning("메일 설정(SMTP_USER/SMTP_PASSWORD/MAIL_TO)이 없어 발송을 건너뜁니다.")
        return False
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = cfg["sender"]
    msg["To"] = ", ".join(cfg["to"])
    msg.set_content(text_body)
    msg.add_alternative(html_body, subtype="html")
    msg.add_attachment(pdf_path.read_bytes(), maintype="application", subtype="pdf",
                       filename=pdf_path.name)  # 한글 파일명은 RFC 2231 로 자동 인코딩
    ctx = ssl.create_default_context()
    if cfg["port"] == 465:
        with smtplib.SMTP_SSL(cfg["host"], cfg["port"], context=ctx, timeout=60) as s:
            s.login(cfg["user"], cfg["password"])
            s.send_message(msg)
    else:
        with smtplib.SMTP(cfg["host"], cfg["port"], timeout=60) as s:
            s.starttls(context=ctx)
            s.login(cfg["user"], cfg["password"])
            s.send_message(msg)
    log.info("메일 발송 완료 → %s", msg["To"])
    return True
