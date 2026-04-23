import json
import pathlib
from datetime import datetime, timedelta


QUEUE_FILE = pathlib.Path("projects/sales/queue.json")
SENT_LOG_FILE = pathlib.Path("projects/sales/sent_log.json")
OPS_REPORT_FILE = pathlib.Path("system/ops_report.md")

VALID_NEXT_ACTIONS = {
    "generate_initial_outreach",
    "founder_review",
    "mark_sent",
    "follow_up_1_due",
    "follow_up_2_due",
    "close_if_no_response",
    "founder_takeover",
    None,
}

REQUIRED_FIELDS = {
    "lead_name",
    "lead_role",
    "institution",
    "stage",
    "status",
    "next_action",
    "founder_approved",
    "reply_received",
    "history",
}


def load_json(path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text())


def parse_time(ts):
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts)
    except Exception:
        return None


def inspect_queue(queue, sent_log):
    findings = []

    sent_names = {entry.get("lead_name") for entry in sent_log}

    for i, lead in enumerate(queue):
        lead_id = f"{lead.get('lead_name', 'Unknown')} ({lead.get('institution', 'Unknown institution')})"

        missing = [field for field in REQUIRED_FIELDS if field not in lead]
        if missing:
            findings.append({
                "severity": "high",
                "lead": lead_id,
                "issue": f"Missing required fields: {', '.join(missing)}"
            })

        next_action = lead.get("next_action")
        if next_action not in VALID_NEXT_ACTIONS:
            findings.append({
                "severity": "high",
                "lead": lead_id,
                "issue": f"Invalid next_action: {next_action}"
            })

        status = lead.get("status")
        stage = lead.get("stage")

        if status == "awaiting_founder_review" and not lead.get("founder_approved", False):
            findings.append({
                "severity": "medium",
                "lead": lead_id,
                "issue": "Waiting on founder approval."
            })

        if lead.get("reply_received") and next_action != "founder_takeover":
            findings.append({
                "severity": "high",
                "lead": lead_id,
                "issue": "Reply received but lead is not routed to founder_takeover."
            })

        if stage == "closed" and next_action is not None:
            findings.append({
                "severity": "medium",
                "lead": lead_id,
                "issue": "Closed lead still has an active next_action."
            })

        generated_outreach = lead.get("generated_outreach")
        if generated_outreach and lead.get("lead_name") not in sent_names and next_action not in ("founder_review", "mark_sent"):
            findings.append({
                "severity": "medium",
                "lead": lead_id,
                "issue": "Generated outreach exists but no send record was found."
            })

        last_contacted = parse_time(lead.get("last_contacted"))
        if next_action in ("follow_up_1_due", "follow_up_2_due") and last_contacted:
            age = datetime.utcnow() - last_contacted
            if age > timedelta(days=7):
                findings.append({
                    "severity": "medium",
                    "lead": lead_id,
                    "issue": "Lead appears stale; follow-up has been pending for over 7 days."
                })

        if not lead.get("history"):
            findings.append({
                "severity": "low",
                "lead": lead_id,
                "issue": "No history entries logged yet."
            })

    return findings


def summarize(findings):
    high = [f for f in findings if f["severity"] == "high"]
    medium = [f for f in findings if f["severity"] == "medium"]
    low = [f for f in findings if f["severity"] == "low"]
    return high, medium, low


def build_report(findings):
    high, medium, low = summarize(findings)

    lines = []
    lines.append("# Ops Report")
    lines.append("")
    lines.append("## System Health Summary")
    lines.append(f"- High severity issues: {len(high)}")
    lines.append(f"- Medium severity issues: {len(medium)}")
    lines.append(f"- Low severity issues: {len(low)}")
    lines.append("")

    lines.append("## Immediate Issues")
    if high:
        for item in high:
            lines.append(f"- [HIGH] {item['lead']}: {item['issue']}")
    else:
        lines.append("- No high severity issues found.")
    lines.append("")

    lines.append("## Operational Follow-Up")
    if medium:
        for item in medium:
            lines.append(f"- [MEDIUM] {item['lead']}: {item['issue']}")
    else:
        lines.append("- No medium severity issues found.")
    lines.append("")

    lines.append("## Minor Observations")
    if low:
        for item in low:
            lines.append(f"- [LOW] {item['lead']}: {item['issue']}")
    else:
        lines.append("- No low severity issues found.")
    lines.append("")

    lines.append("## Recommended Ops Sprint")
    if high:
        lines.append("- Fix state machine and routing issues before adding new automation.")
    elif medium:
        lines.append("- Clean stale leads, tighten founder handoff, and verify send coverage.")
    else:
        lines.append("- No urgent system issues. Safe to extend automation.")
    lines.append("")

    lines.append("## Plain-English Takeaway")
    if high:
        lines.append("- The system has structural issues that could break pipeline flow.")
    elif medium:
        lines.append("- The system is functioning, but some leads may stall or drift.")
    else:
        lines.append("- The system looks stable enough for the next build step.")

    return "\n".join(lines)


def run():
    queue = load_json(QUEUE_FILE, [])
    sent_log = load_json(SENT_LOG_FILE, [])

    findings = inspect_queue(queue, sent_log)
    report = build_report(findings)

    OPS_REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OPS_REPORT_FILE.write_text(report)

    print(report)
    print(f"\nWrote {OPS_REPORT_FILE}")


if __name__ == "__main__":
    run()
