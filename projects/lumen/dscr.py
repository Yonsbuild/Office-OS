# projects/lumen/dscr.py
from office_core.schemas import Belief

def compute_dscr(cash_flow: float, debt_service: float) -> Belief:
    if debt_service == 0:
        probability = 0.0
        dscr = None
    else:
        dscr = round(cash_flow / debt_service, 2)
        # naive confidence: higher when inputs look healthy
        probability = min(1.0, max(0.1, abs(dscr - 1.0)))
    evidence = [f"cash_flow:{cash_flow}", f"debt_service:{debt_service}"]
    return Belief(
        claim=f"DSCR = {dscr}",
        probability=probability,
        evidence=evidence,
    )
