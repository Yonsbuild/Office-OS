import importlib
from office_core.schemas import Task

DEPT_MAP = {
    "sales":     "departments.sales.worker",
    "ops":       "departments.ops.worker",
    "verifier":  "departments.verifier.worker",
}

def route(task: Task):
    for dept in ("sales", "ops", "verifier"):
        mod = importlib.import_module(DEPT_MAP[dept])
        task = mod.handle(task)
    return task  # final state of the Task
