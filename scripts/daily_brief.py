# scripts/daily_brief.py
import json
import pathlib
from datetime import datetime

LEDGER = pathlib.Path("projects/lumen/evidence_ledger.jsonl")
REPORT = pathlib.Path("projects/lumen/calibration_report.md")
BRIEF = pathlib.Path("system/daily_brief.md")


def load_latest_belief():
    if not LEDGER.exists():
        return None

    lines = LEDGER.read_text().strip().splitlines()
    if not lines:
        return None

    return json.loads(lines[-1])


def load_calibration_report():
    if not REPORT.exists():
        return "No calibration report found yet."

    return REPORT.read_text()


def main():
    latest_belief = load_latest_belief()
    calibration_text = load_calibration_report()

    BRIEF.parent.mkdir(parents=True, exist_ok=True)

    with BRIEF.open("w") as f:
        f.write("# Daily Brief\n\n")
        f.write(f"- Generated: {datetime.utcnow().isoformat()} UTC\n\n")

        f.write("## Latest Lumen Belief\n")
        if latest_belief:
            f.write(f"- Claim: {latest_belief.get('claim')}\n")
            f.write(f"- Probability: {latest_belief.get('probability')}\n")
            f.write(f"- Evidence: {latest_belief.get('evidence')}\n")
            f.write(f"- Created At: {latest_belief.get('created_at')}\n")
        else:
            f.write("- No belief logged yet.\n")

        f.write("\n## Calibration Snapshot\n")
        f.write(calibration_text)
        f.write("\n")

    print(f"Wrote {BRIEF}")


if __name__ == "__main__":
    main()
