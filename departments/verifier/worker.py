# departments/verifier/worker.py
from office_core.schemas import Task

def handle(task: Task) -> Task:
    # initialise trace on first touch
    task.payload.setdefault("trace", [])
    task.payload["trace"].append(__name__)  # log which worker touched it
    return task
