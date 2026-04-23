import json
import pathlib
from collections import Counter


QUEUE_FILE = pathlib.Path("projects/sales/queue.json")
BRIEF_FILE = pathlib.Path("system/manager_brief.md")


def load_queue():
    if not QUEUE_FILE.exists():
        return []
    return json.loads(QUEUE_FILE.read_text())


def summarize_queue(queue):
    status_counts = Counter()
    next_action_counts = Counter()

    for lead in queue:
        status_counts[lead.get("status", "unknown")] += 1
        next_action_counts[lead.get("next_action", "none")] += 1

    return status_counts, next_action_counts


def classify_priorities(queue):
    awaiting_founder = []
    ready_to_send = []
    follow_ups_due = []
    replied = []
    stalled = []

    for lead in queue:
        status = lead.get("status")
        next_action = lead.get("next_action")
        name = lead.get("lead_name", "Unknown")
        institution = lead.get("institution", "Unknown institution")

        summary = f"{name} ({institution})"

        if next_action == "founder_review":
            awaiting_founder.append(summary)
        elif next_action == "mark_sent":
            ready_to_send.append(summary)
        elif next_action in ("follow_up_1_due", "follow_up_2_due"):
            follow_ups_due.append(summary)
        elif next_action == "founder_takeover":
            replied.append(summary)
        elif next_action is None and status not in ("closed", "no_response"):
            stalled.append(summary)

    return {
        "awaiting_founder_review": awaiting_founder,
        "ready_to_send": ready_to_send,
        "follow_ups_due": follow_ups_due,
        "replied_needing_founder": replied,
        "stalled": stalled,
    }


def build_manager_brief(queue):
    status_counts, next_action_counts = summarize_queue(queue)
    priorities = classify_priorities(queue)

    lines = []
    lines.append("# Manager Brief")
    lines.append("")
    lines.append("## Queue Summary")
    lines.append(f"- Total leads in queue: {len(queue)}")
    lines.append("")

    lines.append("## Status Breakdown")
    if status_counts:
        for status, count in status_counts.items():
            lines.append(f"- {status}: {count}")
    else:
        lines.append("- No leads found.")
    lines.append("")

    lines.append("## Next Action Breakdown")
    if next_action_counts:
        for action, count in next_action_counts.items():
            lines.append(f"- {action}: {count}")
    else:
        lines.append("- No queued actions found.")
    lines.append("")

    lines.append("## Immediate Priorities")

    if priorities["awaiting_founder_review"]:
        lines.append("- Founder review needed for:")
        for item in priorities["awaiting_founder_review"]:
            lines.append(f"  - {item}")

    if priorities["ready_to_send"]:
        lines.append("- Ready to send:")
        for item in priorities["ready_to_send"]:
            lines.append(f"  - {item}")

    if priorities["follow_ups_due"]:
        lines.append("- Follow-ups due:")
        for item in priorities["follow_ups_due"]:
            lines.append(f"  - {item}")

    if priorities["replied_needing_founder"]:
        lines.append("- Replies waiting on founder:")
        for item in priorities["replied_needing_founder"]:
            lines.append(f"  - {item}")

    if priorities["stalled"]:
        lines.append("- Stalled leads:")
        for item in priorities["stalled"]:
            lines.append(f"  - {item}")

    if not any(priorities.values()):
        lines.append("- No urgent priorities detected.")
    lines.append("")

    lines.append("## Recommended Sales Sprint")

    if priorities["awaiting_founder_review"]:
        lines.append("- Review and approve queued outreach first.")
    elif priorities["ready_to_send"]:
        lines.append("- Send approved outreach and move leads into live follow-up tracking.")
    elif priorities["follow_ups_due"]:
        lines.append("- Process due follow-ups to keep pipeline warm.")
    elif priorities["replied_needing_founder"]:
        lines.append("- Respond to active replies before generating new outreach.")
    else:
        lines.append("- No active blockers. Generate new leads or refresh messaging.")
    lines.append("")

    lines.append("## Plain-English Takeaway")
    if priorities["awaiting_founder_review"]:
        lines.append("- The system has leads ready, but they are waiting on your approval.")
    elif priorities["ready_to_send"]:
        lines.append("- The system has approved messages ready to go out.")
    elif priorities["follow_ups_due"]:
        lines.append("- The system has live leads that need follow-up attention.")
    elif priorities["replied_needing_founder"]:
        lines.append("- Real engagement exists and needs your direct response.")
    else:
        lines.append("- The queue is clear enough to focus on adding or improving pipeline.")

    return "\n".join(lines)


def run():
    queue = load_queue()
    brief = build_manager_brief(queue)

    BRIEF_FILE.parent.mkdir(parents=True, exist_ok=True)
    BRIEF_FILE.write_text(brief)

    print(brief)
    print(f"\nWrote {BRIEF_FILE}")


if __name__ == "__main__":
    run()
