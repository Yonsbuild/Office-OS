# scripts/recalibrate.py
import json, pathlib, statistics, datetime, sys

LEDGER = pathlib.Path("projects/lumen/evidence_ledger.jsonl")
REPORT = pathlib.Path("projects/lumen/calibration_report.md")

if not LEDGER.exists():
    print("No ledger yet — nothing to recalibrate.")
    sys.exit(0)

probs = []
with LEDGER.open() as f:
    for line in f:
        try:
            entry = json.loads(line)
            probs.append(entry["probability"])
        except Exception:
            continue  # skip malformed

if not probs:
    print("No probability data found.")
    sys.exit(0)

avg_conf = statistics.mean(probs)
std_conf = statistics.stdev(probs) if len(probs) > 1 else 0.0
ts = datetime.datetime.utcnow().isoformat(timespec="seconds")

REPORT.parent.mkdir(parents=True, exist_ok=True)
with REPORT.open("w") as f:
    f.write(f"# Lumen DSCR Calibration Report\n\n")
    f.write(f"- Generated: {ts} UTC\n")
    f.write(f"- Checks analysed: {len(probs)}\n")
    f.write(f"- **Average confidence**: {avg_conf:.3f}\n")
    f.write(f"- Std-dev: {std_conf:.3f}\n")

print(f"Wrote {REPORT}")
