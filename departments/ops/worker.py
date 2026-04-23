from office_core.schemas import Task
from projects.lumen.dscr import compute_dscr
import pathlib

LEDGER = pathlib.Path("projects/lumen/evidence_ledger.jsonl")


def handle(task: Task) -> Task:
    task.payload.setdefault("trace", [])
    task.payload["trace"].append(__name__)

    if task.kind == "dscr_check":
        cash_flow = task.payload["cash_flow"]
        debt_service = task.payload["debt_service"]

        belief = compute_dscr(cash_flow, debt_service)

        LEDGER.parent.mkdir(parents=True, exist_ok=True)
        with LEDGER.open("a") as f:
            f.write(belief.to_json() + "\n")

        task.payload["belief"] = belief.to_json()

    return task
