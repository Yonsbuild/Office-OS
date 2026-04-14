from office_core.schemas import Task
import json


def handle(task: Task) -> Task:
    task.payload.setdefault("trace", [])
    task.payload["trace"].append(__name__)

    belief_json = task.payload.get("belief")

    if not belief_json:
        task.payload["verification_status"] = "no_belief_found"
        task.payload["verification_notes"] = "No belief was attached for verification."
        return task

    belief = json.loads(belief_json)
    probability = belief.get("probability", 0)

    if probability >= 0.75:
        task.payload["verification_status"] = "pass"
        task.payload["verification_notes"] = "Confidence is high enough for use."
    elif probability >= 0.4:
        task.payload["verification_status"] = "review"
        task.payload["verification_notes"] = "Confidence is moderate. Human review advised."
    else:
        task.payload["verification_status"] = "fail"
        task.payload["verification_notes"] = "Confidence too low. Do not trust without intervention."

    return task
