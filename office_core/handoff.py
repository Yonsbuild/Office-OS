import pathlib


MANAGER_BRIEF_FILE = pathlib.Path("system/manager_brief.md")
OPS_REPORT_FILE = pathlib.Path("system/ops_report.md")
HANDOFF_FILE = pathlib.Path("system/founder_handoff.md")


def load_text(path):
    if not path.exists():
        return ""
    return path.read_text()


def extract_section(text, heading):
    lines = text.splitlines()
    capture = False
    collected = []

    for line in lines:
        if line.strip() == heading:
            capture = True
            continue
        if capture and line.startswith("## "):
            break
        if capture:
            collected.append(line)

    return "\n".join(collected).strip()


def build_handoff(manager_text, ops_text):
    queue_summary = extract_section(manager_text, "## Queue Summary")
    immediate_priorities = extract_section(manager_text, "## Immediate Priorities")
    recommended_sales_sprint = extract_section(manager_text, "## Recommended Sales Sprint")
    manager_takeaway = extract_section(manager_text, "## Plain-English Takeaway")

    system_health = extract_section(ops_text, "## System Health Summary")
    immediate_issues = extract_section(ops_text, "## Immediate Issues")
    ops_follow_up = extract_section(ops_text, "## Operational Follow-Up")
    ops_takeaway = extract_section(ops_text, "## Plain-English Takeaway")

    lines = []
    lines.append("# Founder Handoff")
    lines.append("")
    lines.append("## What Sales Needs Next")
    lines.append(recommended_sales_sprint or "- No sales recommendation available.")
    lines.append("")

    lines.append("## What Is Waiting On You")
    lines.append(immediate_priorities or "- No immediate founder actions identified.")
    lines.append("")

    lines.append("## Queue Snapshot")
    lines.append(queue_summary or "- No queue summary available.")
    lines.append("")

    lines.append("## System Health")
    lines.append(system_health or "- No system health summary available.")
    lines.append("")

    lines.append("## Potential Blockers")
    if immediate_issues:
        lines.append(immediate_issues)
    else:
        lines.append("- No major blockers found.")
    lines.append("")

    lines.append("## Ops Follow-Up")
    lines.append(ops_follow_up or "- No ops follow-up items identified.")
    lines.append("")

    lines.append("## Plain-English Read")
    if manager_takeaway:
        lines.append(manager_takeaway)
    if ops_takeaway:
        lines.append(ops_takeaway)
    if not manager_takeaway and not ops_takeaway:
        lines.append("- No plain-English summary available.")
    lines.append("")

    lines.append("## Founder Decision")
    if "review" in (immediate_priorities or "").lower():
        lines.append("- Review and approve queued outreach before generating more work.")
    elif "high severity" in (system_health or "").lower() and "0" not in (system_health or ""):
        lines.append("- Fix system issues before scaling activity.")
    else:
        lines.append("- No critical intervention required. Proceed with next sales sprint.")

    return "\n".join(lines)


def run():
    manager_text = load_text(MANAGER_BRIEF_FILE)
    ops_text = load_text(OPS_REPORT_FILE)

    handoff = build_handoff(manager_text, ops_text)

    HANDOFF_FILE.parent.mkdir(parents=True, exist_ok=True)
    HANDOFF_FILE.write_text(handoff)

    print(handoff)
    print(f"\nWrote {HANDOFF_FILE}")


if __name__ == "__main__":
    run()
