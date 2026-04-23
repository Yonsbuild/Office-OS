import json
import pathlib

from office_core.schemas import Task
from office_core.dispatcher import route


LEADS_FILE = pathlib.Path("projects/sales/leads.json")


def load_leads():
    if not LEADS_FILE.exists():
        return []
    return json.loads(LEADS_FILE.read_text())


def run():
    leads = load_leads()

    if not leads:
        print("No leads found.")
        return

    lead = leads[0]

    task = Task(
        kind="generate_outreach",
        payload=lead
    )

    result = route(task)

    print("Trace:", result.payload.get("trace"))

    print("\n--- Selected Outreach ---\n")
    print(result.payload.get("selected_outreach", "No message generated."))

    print("\n--- All Variants ---\n")
    variants = result.payload.get("outreach_variants", {})
    for name, msg in variants.items():
        print(f"\n[{name.upper()}]\n{msg}\n")

    print("\n--- Follow Ups ---\n")
    follow_ups = result.payload.get("follow_ups", {})
    for name, msg in follow_ups.items():
        print(f"\n[{name.upper()}]\n{msg}\n")


if __name__ == "__main__":
    run()
