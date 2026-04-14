from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any, Dict, List
import json


# ---------- Core task & evidence ----------

@dataclass
class Task:
    kind: str                    # e.g. "lead_gen", "dscr_check"
    payload: Dict[str, Any]      # flexible data blob
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class Evidence:
    source: str                  # "cash_flow_csv", "llm_summary", etc.
    data: Any


# ---------- Confidence & outcome ----------

@dataclass
class Confidence:
    value: float                 # 0 – 1
    rationale: str               # short explanation


@dataclass
class Outcome:
    result: Any
    confidence: Confidence
    evidence: List[Evidence]


# ---------- Probabilistic belief ----------

@dataclass
class Belief:
    claim: str                   # e.g. "DSCR = 1.18"
    probability: float           # 0 – 1
    evidence: List[str]          # identifiers / notes
    created_at: datetime = field(default_factory=datetime.utcnow)

    def to_json(self) -> str:
        """Return a JSON-serialisable string with ISO datetime."""
        data = asdict(self)
        data["created_at"] = self.created_at.isoformat()
        return json.dumps(data)
