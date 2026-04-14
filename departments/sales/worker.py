from office_core.schemas import Task
import pathlib


LUMEN_ANGLES = pathlib.Path("projects/lumen/outreach_angles.md")
LUMEN_PROOF = pathlib.Path("projects/lumen/proof_points.md")


def load_file(path):
    if not path.exists():
        return ""
    return path.read_text()


def handle(task: Task) -> Task:
    task.payload.setdefault("trace", [])
    task.payload["trace"].append(__name__)

    if task.kind == "generate_outreach":

        angles = load_file(LUMEN_ANGLES)
        proof = load_file(LUMEN_PROOF)

        # simple first-pass message (we’ll improve later)
        message = f"""
Hi — I’ve been looking into how lending teams are handling verification of financial calculations (DSCR, income, etc.).

One thing that stood out:
Most decisions rely on reported numbers that aren’t independently re-verified.

I recently built a lightweight system that recomputes key metrics and flags inconsistencies automatically.
In one case, it caught a DSCR discrepancy (reported 1.42 vs actual ~1.18) that would have otherwise passed through.

Not pitching anything — just curious how your team is handling verification today.
"""

        task.payload["outreach_message"] = message.strip()

    return task
