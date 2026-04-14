import json
import pathlib

from office_core.schemas import Task
from office_core.dispatcher import route


QUEUE_FILE = pathlib.Path("projects/sales/queue.json")


def load_queue():
    if not QUEUE_FILE.exists():
        return []
    return json.loads(QUEUE_FILE.read_text())


def save_queue(queue):
    QUEUE_FILE.write_text(json.dumps(queue, indent=2))


def run():
    queue = load_queue()

    if not queue:
        print("No queue items found.")
        return

    lead = queue[0]

    print("Current lead:")
    print(json.dumps(lead, indent=2))

    if lead["next_action"] == "generate_initial_outreach":
        task = Task(kind="generate_outreach", payload=lead)
        result = route(task)

        lead["generated_outreach"] = result.payload.get("selected_outreach")
        lead["generated_follow_ups"] = result.payload.get("follow_ups", {})
        lead["status"] = "outreach_generated"
        lead["next_action"] = "awaiting_founder_review"

        save_queue(queue)

        print("\n--- Generated Outreach ---\n")
        print(lead["generated_outreach"])

        print("\n--- Follow Ups ---\n")
        for name, msg in lead["generated_follow_ups"].items():
            print(f"\n[{name.upper()}]\n{msg}\n")

    else:
        print(f"No handler yet for next_action={lead['next_action']}")


if __name__ == "__main__":
    run()
