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
        lead_name = task.payload.get("lead_name", "there")
        lead_role = task.payload.get("lead_role", "team lead")
        institution = task.payload.get("institution", "your institution")
        relationship_context = task.payload.get("relationship_context", "").strip()
        preferred_angle = task.payload.get("preferred_angle", "risk")

        intro = f"Hi {lead_name},"
        if relationship_context:
            intro += f" {relationship_context.strip().rstrip('.')}."

        institution_phrase = f"teams at {institution}" if institution else "lending teams"

        # --- Outreach Variants ---

        risk_message = f"""
{intro}

I’ve been speaking with {institution_phrase} about how key financial metrics like DSCR and income are verified.

One thing that keeps coming up is that reported numbers often aren’t independently re-checked.

In one case, a DSCR was reported as 1.42 but recalculated closer to 1.18 — something that could have easily passed through.

Given your role as a {lead_role}, I was curious how your team currently catches issues like that.
""".strip()

        compliance_message = f"""
{intro}

Quick question based on your role as a {lead_role}.

As more automation and AI enter underwriting workflows, how is {institution} handling auditability around financial decisions?

Most processes still don’t leave a clear trail showing how numbers were verified.

I’ve been working on a lightweight system that logs each check with supporting evidence and flags inconsistencies automatically.

I’d be interested to hear how your team is thinking about that.
""".strip()

        efficiency_message = f"""
{intro}

I’ve been speaking with lending teams about how much time still goes into double-checking calculations like DSCR, income, and DTI.

A lot of that process is still manual.

I built a lightweight system that recomputes key metrics and flags inconsistencies automatically, so teams don’t have to re-check everything themselves.

Given your role as a {lead_role}, I was curious whether your team has looked at streamlining that process.
""".strip()

        variants = {
            "risk": risk_message,
            "compliance": compliance_message,
            "efficiency": efficiency_message
        }

        # --- Follow Ups ---

        follow_up_1 = f"""
Hi {lead_name},

Wanted to circle back on this — I’m speaking with a few teams about how financial checks like DSCR are being verified.

Curious if this is something your team has already dialed in, or if inconsistencies still slip through occasionally.
""".strip()

        follow_up_2 = f"""
Hi {lead_name},

Following up one last time — I’ve seen a few cases recently where small calculation mismatches (like DSCR) made it all the way through review.

It’s a small issue until it isn’t, which is why I’ve been digging into how teams are handling verification.

If it’s relevant, happy to share what I’ve been seeing.
""".strip()

        task.payload["outreach_variants"] = variants
        task.payload["selected_outreach"] = variants.get(preferred_angle, risk_message)

        task.payload["follow_ups"] = {
            "follow_up_1": follow_up_1,
            "follow_up_2": follow_up_2
        }

    return task
