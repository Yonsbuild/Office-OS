import json
import os
import smtplib
import ssl
from datetime import datetime, UTC
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Dict, List, Optional


BASE_DIR = Path(__file__).resolve().parent.parent
SENT_LOG_PATH = BASE_DIR / "projects" / "sales" / "sent_log.json"


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def load_sent_log() -> List[Dict[str, Any]]:
    if not SENT_LOG_PATH.exists():
        return []

    try:
        with SENT_LOG_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def save_sent_log(entries: List[Dict[str, Any]]) -> None:
    SENT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with SENT_LOG_PATH.open("w", encoding="utf-8") as f:
        json.dump(entries, f, indent=2, ensure_ascii=False)


def _append_log(entry: Dict[str, Any]) -> Dict[str, Any]:
    entries = load_sent_log()
    entries.append(entry)
    save_sent_log(entries)
    return entry


def _smtp_config() -> Dict[str, Any]:
    return {
        "host": os.getenv("OFFICE_SMTP_HOST", "smtp.gmail.com"),
        "port": int(os.getenv("OFFICE_SMTP_PORT", "587")),
        "username": os.getenv("OFFICE_SMTP_USERNAME", ""),
        "password": os.getenv("OFFICE_SMTP_PASSWORD", ""),
        "from_email": os.getenv("OFFICE_FROM_EMAIL", ""),
        "use_tls": os.getenv("OFFICE_SMTP_USE_TLS", "true").lower() == "true",
    }


def _build_message(
    to_email: str,
    subject: str,
    body: str,
    from_email: str,
    reply_to: Optional[str] = None,
) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = from_email
    msg["To"] = to_email
    msg["Subject"] = subject
    if reply_to:
        msg["Reply-To"] = reply_to
    msg.set_content(body)
    return msg


def send_message(
    *,
    lead: Dict[str, Any],
    to_email: str,
    subject: str,
    body: str,
    message_type: str,
    campaign_id: Optional[str] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """
    Sends a real email over SMTP unless dry_run=True.
    Always writes a structured record to sent_log.json.

    Returns:
        {
            "success": bool,
            "provider": str,
            "external_id": str | None,
            "sent_at": str,
            "error": str | None,
            "dry_run": bool,
            ...
        }
    """
    sent_at = now_iso()
    config = _smtp_config()

    base_record: Dict[str, Any] = {
        "timestamp": sent_at,
        "sent_at": sent_at,
        "lead_name": lead.get("lead_name"),
        "institution": lead.get("institution"),
        "lead_role": lead.get("lead_role"),
        "to_email": to_email,
        "subject": subject,
        "message_type": message_type,
        "campaign_id": campaign_id,
        "content": body,
        "provider": "smtp",
        "external_id": None,
        "success": False,
        "error": None,
        "dry_run": dry_run,
    }

    if dry_run:
        base_record["success"] = True
        base_record["provider"] = "dry_run"
        return _append_log(base_record)

    required = {
        "OFFICE_SMTP_USERNAME": config["username"],
        "OFFICE_SMTP_PASSWORD": config["password"],
        "OFFICE_FROM_EMAIL": config["from_email"],
    }
    missing = [key for key, value in required.items() if not value]
    if missing:
        base_record["error"] = f"Missing SMTP config: {', '.join(missing)}"
        return _append_log(base_record)

    try:
        msg = _build_message(
            to_email=to_email,
            subject=subject,
            body=body,
            from_email=config["from_email"],
            reply_to=config["from_email"],
        )

        with smtplib.SMTP(config["host"], config["port"], timeout=30) as server:
            if config["use_tls"]:
                server.starttls(context=ssl.create_default_context())
            server.login(config["username"], config["password"])
            response = server.send_message(msg)

        # send_message returns a dict of refused recipients.
        # Empty dict means success.
        if response:
            base_record["error"] = f"SMTP refused recipients: {response}"
            return _append_log(base_record)

        base_record["success"] = True
        base_record["external_id"] = f"smtp-{int(datetime.now(UTC).timestamp())}"
        return _append_log(base_record)

    except Exception as exc:
        base_record["error"] = str(exc)
        return _append_log(base_record)
