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

        # Risk angle
        risk_message = """
Hi — I’ve been looking into how lending teams are verifying key financial metrics like DSCR and income.

One thing that keeps coming up:
Most decisions rely on reported numbers that aren’t independently re-verified.

I recently ran a check that caught a DSCR discrepancy (reported 1.42 vs actual ~1.18) that would have otherwise passed through.

Curious — how does your team currently catch things like that?
""".strip()

        # Compliance angle
        compliance_message = """
Hi — quick question on your process.

With more AI and automation being used in underwriting, how are teams handling auditability of decisions?

Most workflows don’t leave a clear trail showing how numbers were verified.

I’ve been working on a system that logs every check with evidence and flags inconsistencies automatically.

Would be interested to hear how your team is thinking about that.
""".strip()

        # Efficiency angle
        efficiency_message = """
Hi — I’ve been speaking with a few teams about the time spent double-checking financial calculations in lending workflows.

A lot of that still seems manual.

I built a lightweight system that recomputes key metrics like DSCR and flags inconsistencies instantly, so teams don’t have to re-check everything themselves.

Is that something your team has tried to streamline yet?
""".strip()

        task.payload["outreach_variants"] = {
            "risk": risk_message,
            "compliance": compliance_message,
            "efficiency": efficiency_message
        }

    return task
