import logging
from engines.base import EngineResult, EvidenceCard

log = logging.getLogger("engines.future_potential_engine")

def calculate_future_potential(facts) -> EngineResult:
    """
    Computes Future Potential Score.
    Currently a stub that returns NOT_IMPLEMENTED.
    """
    evidence = EvidenceCard(warnings=["Future Potential Engine is not yet implemented."])
    return EngineResult(
        score=None,
        confidence=0.0,
        coverage=0.0,
        status='NOT_IMPLEMENTED',
        evidence=evidence,
        warnings=["Future Potential Engine is not yet implemented."]
    )
