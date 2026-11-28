from dataclasses import dataclass
from typing import List, Optional


@dataclass(frozen=True)
class Route:
    name: str
    utterances: List[str]
    description: Optional[str] = None
    score_threshold: Optional[float] = None
