from dataclasses import dataclass, field
from typing import Optional, List, Dict

@dataclass
class EvidenceCard:
    positive: List[str] = field(default_factory=list)
    negative: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, List[str]]:
        return {
            'positive': self.positive,
            'negative': self.negative,
            'warnings': self.warnings
        }

@dataclass
class EngineResult:
    score: Optional[float]
    confidence: float          # 0-100
    coverage: float            # 0-100
    status: str                # READY / INCOMPLETE / NOT_IMPLEMENTED / FAILED
    evidence: EvidenceCard
    warnings: List[str] = field(default_factory=list)

    def to_dict(self):
        return {
            'score': self.score,
            'confidence': self.confidence,
            'coverage': self.coverage,
            'status': self.status,
            'evidence': self.evidence.to_dict(),
            'warnings': self.warnings
        }
