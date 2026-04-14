# office_core/schemas.py

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Any

@dataclass
class Task:
    kind: str                   # e.g. "lead_gen", "dscr_check"
    payload: Dict[str, Any]     # raw data for the worker
    created_at: datetime = field(default_factory=datetime.utcnow)

@dataclass
class Evidence:
    source: str                 # "cash_flow_csv", "llm_summary", etc.
    data: Any

@dataclass
class Confidence:
    value: float                # 0–1
    rationale: str              # short explanation

@dataclass
class Outcome:
    result: Any
    confidence: Confidence
    evidence: List[Evidence]
