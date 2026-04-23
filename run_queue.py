import json
from datetime import datetime, UTC
from pathlib import Path
from typing import Any, Dict, List, Optional

from office_core.send import send_message


BASE_DIR = Path(__file__).resolve().parent
QUEUE_PATH = BASE_DIR / "projects" / "sales" / "queue.json"


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def parse_time(value: Optional[str]) -> Optional[datetime]:
    if not value or not isinstance(value, str):
        return None

    try:
        normalized = value.replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=UTC)
        return dt
    except ValueError:
        return None


def load_queue() -> List[Dict[str, Any]]:
    if not QUEUE_PATH.exists():
        return []

    with QUEUE_PATH.open("r", encoding="utf-8") as f:
        data = json.load(f)
        return data if isinstance(data, list) else []


def save_queue(queue: List[Dict[str, Any]]) -> None:
    with QUEUE_PATH.open("w", encoding="utf-8") as f:
        json.dump(queue, f, indent=2, ensure_ascii=False)


def add_history(lead: Dict[str, Any], event: str, details: str) -> None:
    lead.setdefault("history", [])
    lead["history"].append(
        {
            "timestamp": now_iso(),
            "event": event,
            "details": details,
        }
    )


def should_follow_up(last_contacted: Optional[str], wait_days: int) -> bool:
    dt = parse_time(last_contacted)
    if dt is None:
        return False

    elapsed = datetime.now(UTC) - dt.astimezone(UTC)
    return elapsed.total_seconds() >= wait_days * 86400


def build_subject(lead: Dict[str, Any], message_type: str) -> str:
    institution = lead.get("institution", "your team")
    if message_type == "initial_outreach":
        return f"Quick question about verification at {institution}"
    if message_type == "follow_up_1":
        return f"Following up on verification workflows at {institution}"
    if message_type == "follow_up_2":
        return f"Last note on verification checks at {institution}"
    return f"Quick question for {institution}"


def require_email(lead: Dict[str, Any]) -> Optional[str]:
    email = lead.get("email")
    if not email or not isinstance(email, str):
        return None
    return email.strip()


def process_founder_review(lead: Dict[str, Any]) -> None:
    if lead.get("founder_approved") is True:
        lead["stage"] = "approved"
        lead["status"] = "ready_to_send"
        lead["next_action"] = "mark_sent"
        add_history(lead, "founder_approved", "Founder approved outreach.")
        print("Lead approved by founder. Ready to send.")
    else:
        print("Awaiting founder approval.")


def process_send(lead: Dict[str, Any]) -> None:
    to_email = require_email(lead)
    if not to_email:
        lead["status"] = "send_failed"
        lead["next_action"] = "retry_send"
        lead["send_failed"] = True
        lead["last_error"] = "Missing lead email."
        add_history(lead, "send_failed", "Send failed: missing lead email.")
        print("Send failed: missing lead email.")
        return

    body = lead.get("selected_outreach") or lead.get("generated_outreach")
    if not body:
        lead["status"] = "send_failed"
        lead["next_action"] = "retry_send"
        lead["send_failed"] = True
        lead["last_error"] = "Missing outreach content."
        add_history(lead, "send_failed", "Send failed: missing outreach content.")
        print("Send failed: missing outreach content.")
        return

    result = send_message(
        lead=lead,
        to_email=to_email,
        subject=build_subject(lead, "initial_outreach"),
        body=body,
        message_type="initial_outreach",
        campaign_id=lead.get("campaign_id"),
        dry_run=lead.get("dry_run", False),
    )

    if result.get("success") is True:
        lead["stage"] = "sent"
        lead["status"] = "waiting_for_reply"
        lead["next_action"] = "follow_up_1_due"
        lead["last_contacted"] = result["sent_at"]
        lead["send_failed"] = False
        lead["last_error"] = None
        lead["last_send"] = {
            "provider": result.get("provider"),
            "external_id": result.get("external_id"),
            "sent_at": result.get("sent_at"),
            "message_type": "initial_outreach",
        }
        add_history(
            lead,
            "outreach_sent",
            f"Initial outreach sent via {result.get('provider')}.",
        )
        print("Initial outreach sent.")
    else:
        lead["status"] = "send_failed"
        lead["next_action"] = "retry_send"
        lead["send_failed"] = True
        lead["last_error"] = result.get("error")
        add_history(
            lead,
            "send_failed",
            f"Initial outreach failed: {result.get('error')}",
        )
        print(f"Send failed: {result.get('error')}")


def process_follow_up_1(lead: Dict[str, Any]) -> None:
    if lead.get("reply_received") is True:
        lead["stage"] = "replied"
        lead["status"] = "awaiting_founder_response"
        lead["next_action"] = "founder_takeover"
        add_history(lead, "reply_received", "Reply received before first follow-up.")
        print("Reply detected. Founder takeover required.")
        return

    if not should_follow_up(lead.get("last_contacted"), wait_days=2):
        print("Follow-up 1 not due yet.")
        return

    to_email = require_email(lead)
    if not to_email:
        lead["status"] = "send_failed"
        lead["next_action"] = "retry_send"
        lead["send_failed"] = True
        lead["last_error"] = "Missing lead email for follow-up 1."
        add_history(lead, "send_failed", "Follow-up 1 failed: missing lead email.")
        print("Follow-up 1 failed: missing lead email.")
        return

    body = (
        lead.get("follow_ups", {}).get("follow_up_1")
        or lead.get("generated_follow_ups", {}).get("follow_up_1")
    )
    if not body:
        lead["status"] = "send_failed"
        lead["next_action"] = "retry_send"
        lead["send_failed"] = True
        lead["last_error"] = "Missing follow-up 1 content."
        add_history(lead, "send_failed", "Follow-up 1 failed: missing content.")
        print("Follow-up 1 failed: missing content.")
        return

    result = send_message(
        lead=lead,
        to_email=to_email,
        subject=build_subject(lead, "follow_up_1"),
        body=body,
        message_type="follow_up_1",
        campaign_id=lead.get("campaign_id"),
        dry_run=lead.get("dry_run", False),
    )

    if result.get("success") is True:
        lead["stage"] = "follow_up_1_sent"
        lead["status"] = "waiting_for_reply"
        lead["next_action"] = "follow_up_2_due"
        lead["last_contacted"] = result["sent_at"]
        lead["send_failed"] = False
        lead["last_error"] = None
        lead["last_send"] = {
            "provider": result.get("provider"),
            "external_id": result.get("external_id"),
            "sent_at": result.get("sent_at"),
            "message_type": "follow_up_1",
        }
        add_history(lead, "follow_up_1_sent", "First follow-up sent.")
        print("Follow-up 1 sent.")
    else:
        lead["status"] = "send_failed"
        lead["next_action"] = "retry_send"
        lead["send_failed"] = True
        lead["last_error"] = result.get("error")
        add_history(
            lead,
            "send_failed",
            f"Follow-up 1 failed: {result.get('error')}",
        )
        print(f"Follow-up 1 failed: {result.get('error')}")


def process_follow_up_2(lead: Dict[str, Any]) -> None:
    if lead.get("reply_received") is True:
        lead["stage"] = "replied"
        lead["status"] = "awaiting_founder_response"
        lead["next_action"] = "founder_takeover"
        add_history(lead, "reply_received", "Reply received before second follow-up.")
        print("Reply detected. Founder takeover required.")
        return

    if not should_follow_up(lead.get("last_contacted"), wait_days=3):
        print("Follow-up 2 not due yet.")
        return

    to_email = require_email(lead)
    if not to_email:
        lead["status"] = "send_failed"
        lead["next_action"] = "retry_send"
        lead["send_failed"] = True
        lead["last_error"] = "Missing lead email for follow-up 2."
        add_history(lead, "send_failed", "Follow-up 2 failed: missing lead email.")
        print("Follow-up 2 failed: missing lead email.")
        return

    body = (
        lead.get("follow_ups", {}).get("follow_up_2")
        or lead.get("generated_follow_ups", {}).get("follow_up_2")
    )
    if not body:
        lead["status"] = "send_failed"
        lead["next_action"] = "retry_send"
        lead["send_failed"] = True
        lead["last_error"] = "Missing follow-up 2 content."
        add_history(lead, "send_failed", "Follow-up 2 failed: missing content.")
        print("Follow-up 2 failed: missing content.")
        return

    result = send_message(
        lead=lead,
        to_email=to_email,
        subject=build_subject(lead, "follow_up_2"),
        body=body,
        message_type="follow_up_2",
        campaign_id=lead.get("campaign_id"),
        dry_run=lead.get("dry_run", False),
    )

    if result.get("success") is True:
        lead["stage"] = "follow_up_2_sent"
        lead["status"] = "waiting_for_reply"
        lead["next_action"] = "close_if_no_response"
        lead["last_contacted"] = result["sent_at"]
        lead["send_failed"] = False
        lead["last_error"] = None
        lead["last_send"] = {
            "provider": result.get("provider"),
            "external_id": result.get("external_id"),
            "sent_at": result.get("sent_at"),
            "message_type": "follow_up_2",
        }
        add_history(lead, "follow_up_2_sent", "Second follow-up sent.")
        print("Follow-up 2 sent.")
    else:
        lead["status"] = "send_failed"
        lead["next_action"] = "retry_send"
        lead["send_failed"] = True
        lead["last_error"] = result.get("error")
        add_history(
            lead,
            "send_failed",
            f"Follow-up 2 failed: {result.get('error')}",
        )
        print(f"Follow-up 2 failed: {result.get('error')}")


def process_close_if_no_response(lead: Dict[str, Any]) -> None:
    if lead.get("reply_received") is True:
        lead["stage"] = "replied"
        lead["status"] = "awaiting_founder_response"
        lead["next_action"] = "founder_takeover"
        add_history(lead, "reply_received", "Reply received before closeout.")
        print("Reply detected. Founder takeover required.")
        return

    if not should_follow_up(lead.get("last_contacted"), wait_days=3):
        print("Closeout not due yet.")
        return

    lead["stage"] = "closed"
    lead["status"] = "no_response"
    lead["next_action"] = None
    add_history(lead, "closed_no_response", "Lead closed after no response.")
    print("Lead closed due to no response.")


def process_retry_send(lead: Dict[str, Any]) -> None:
    if lead.get("stage") in {"approved", "sent", "follow_up_1_sent"}:
        print("Retrying failed send.")
        if lead.get("stage") == "approved":
            lead["next_action"] = "mark_sent"
        elif lead.get("stage") == "sent":
            lead["next_action"] = "follow_up_1_due"
        elif lead.get("stage") == "follow_up_1_sent":
            lead["next_action"] = "follow_up_2_due"
    else:
        print("Retry requested, but lead stage is not send-recoverable.")


def run() -> None:
    queue = load_queue()

    for index, lead in enumerate(queue, start=1):
        print(f"\n===== Processing Lead {index} =====\n")
        print(json.dumps(lead, indent=2, ensure_ascii=False))

        print("\n--- Processing ---\n")

        next_action = lead.get("next_action")

        if next_action == "founder_review":
            process_founder_review(lead)

        elif next_action == "mark_sent":
            process_send(lead)

        elif next_action == "follow_up_1_due":
            process_follow_up_1(lead)

        elif next_action == "follow_up_2_due":
            process_follow_up_2(lead)

        elif next_action == "close_if_no_response":
            process_close_if_no_response(lead)

        elif next_action == "retry_send":
            process_retry_send(lead)

        elif next_action == "founder_takeover":
            print("Founder action required.")

        elif next_action is None:
            print("No next action.")

        else:
            print(f"No handler for next_action={next_action}")

        if lead.get("history"):
            print("\n--- Latest History Event ---\n")
            print(json.dumps(lead["history"][-1], indent=2, ensure_ascii=False))

    save_queue(queue)
    print("\n=== Queue Updated ===\n")


if __name__ == "__main__":
    run()
