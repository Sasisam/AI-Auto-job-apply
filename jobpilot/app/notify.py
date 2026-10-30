"""Email + phone push notifications (ntfy.sh app: free, no phone-number setup needed)."""
import smtplib
from email.message import EmailMessage

import requests

from . import config


def send_email(subject, body):
    if not (config.SMTP_USER and config.SMTP_PASS and config.NOTIFY_EMAIL):
        return False
    try:
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = config.SMTP_USER
        msg["To"] = config.NOTIFY_EMAIL
        msg.set_content(body)
        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=20) as s:
            s.starttls()
            s.login(config.SMTP_USER, config.SMTP_PASS)
            s.send_message(msg)
        return True
    except Exception as e:
        print("email error:", e)
        return False


def push(title, body, urgent=False, click_url=None):
    if not config.NTFY_TOPIC:
        return False
    try:
        headers = {"Title": title.encode("utf-8"), "Priority": "high" if urgent else "default"}
        if click_url:
            headers["Click"] = click_url
        requests.post(
            f"https://ntfy.sh/{config.NTFY_TOPIC}", data=body.encode("utf-8"), headers=headers, timeout=15
        )
        return True
    except Exception as e:
        print("push error:", e)
        return False


def notify(subject, body, urgent=False, link=None):
    """Email always; phone push too. `urgent` = a human is needed."""
    text = body + (f"\n\nLink: {link}" if link else "")
    e = send_email(f"[JobPilot] {subject}", text)
    p = push(subject, body, urgent=urgent, click_url=link)
    return e or p
