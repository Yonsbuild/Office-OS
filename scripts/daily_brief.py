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


def interpret_probability(p):
    if p >= 0.75:
        return "High confidence — safe to rely on"
    elif p >= 0.4:
        return "Moderate confidence — review recommended"
    else:
        return "Low confidence — do not rely on without checking"


def load_calibration_summary():
    if not REPORT.exists():
        return "No system reliability data yet."

    text = REPORT.read_text()

    # crude extraction for readability
    lines = text.splitlines()
    summary = []

    for line in lines:
        if "Average confidence" in line or "Checks analysed" in line:
            summary.append(line.replace("**", "").replace("-", "").strip())

    return "\n".join(summary) if summary else "No usable calibration summary yet."


def main():
    latest = load_latest_belief()
    calibration = load_calibration_summary()

    BRIEF.parent.mkdir(parents=True, exist_ok=True)

    with BRIEF.open("w") as f:
        f.write("# Daily Brief\n\n")
        f.write(f"Generated: {datetime.utcnow().isoformat()} UTC\n\n")

        f.write("## What the system checked\n")

        if latest:
            claim = latest.get("claim")
            prob = latest.get("probability", 0)

            f.write(f"- The system evaluated: {claim}\n")
            f.write(f"- Confidence level: {interpret_probability(prob)}\n")
            f.write(f"- Raw confidence score: {round(prob, 2)}\n")
        else:
            f.write("- No checks have been run yet.\n")

        f.write("\n## System reliability (so far)\n")
        f.write(calibration + "\n")

        f.write("\n## What this means\n")

        if latest:
            if prob >= 0.75:
                f.write("- You can trust this result without additional review.\n")
            elif prob >= 0.4:
                f.write("- This result should be reviewed before making a decision.\n")
            else:
                f.write("- Do not trust this result yet. It needs verification.\n")
        else:
            f.write("- No actionable output yet.\n")

    print(f"Wrote {BRIEF}")


if __name__ == "__main__":
    main()
