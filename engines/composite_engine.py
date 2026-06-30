import logging
from engines.base import EngineResult, EvidenceCard

log = logging.getLogger("engines.composite_engine")

COMPOSITE_WEIGHTS = {
    "business_strength": 0.40,
    "future_potential": 0.25,
    "valuation": 0.20,
    "technical": 0.15
}

def calculate_composite_score(bqs_res: EngineResult, vs_res: EngineResult, fps_res: EngineResult, trs_res: EngineResult) -> EngineResult:
    """
    Computes Composite Investment Score dynamically.
    If components are missing/deferred, returns status INCOMPLETE.
    """
    
    # Check if we have all necessary implementations
    if fps_res.status == 'NOT_IMPLEMENTED' or trs_res.status == 'NOT_IMPLEMENTED':
        msg = "Composite score deferred: Not all engines are fully implemented yet."
        evidence = EvidenceCard(warnings=[msg])
        return EngineResult(
            score=None,
            confidence=0.0,
            coverage=0.0,
            status='INCOMPLETE',
            evidence=evidence,
            warnings=[msg]
        )
        
    bqs_score = bqs_res.score
    vs_score = vs_res.score
    fps_score = fps_res.score
    trs_score = trs_res.score
    
    if any(s is None for s in [bqs_score, vs_score, fps_score, trs_score]):
        msg = "Composite score deferred: Incomplete data from one or more engines."
        evidence = EvidenceCard(warnings=[msg])
        return EngineResult(
            score=None,
            confidence=0.0,
            coverage=0.0,
            status='INCOMPLETE',
            evidence=evidence,
            warnings=[msg]
        )

    composite_score = (
        bqs_score * COMPOSITE_WEIGHTS['business_strength'] +
        fps_score * COMPOSITE_WEIGHTS['future_potential'] +
        vs_score * COMPOSITE_WEIGHTS['valuation'] +
        trs_score * COMPOSITE_WEIGHTS['technical']
    )
    
    evidence = EvidenceCard()
    if composite_score >= 80:
        evidence.positive.append(f"✓ Strong composite score ({composite_score:.1f})")
    elif composite_score <= 40:
        evidence.negative.append(f"✗ Weak composite score ({composite_score:.1f})")
        
    return EngineResult(
        score=round(composite_score, 2),
        confidence=100.0,
        coverage=100.0,
        status='READY',
        evidence=evidence,
        warnings=[]
    )
