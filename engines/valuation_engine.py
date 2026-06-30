import logging
from engines.base import EngineResult, EvidenceCard

log = logging.getLogger("engines.valuation_engine")

VALUATION_WEIGHTS = {
    "relative": 0.25,
    "intrinsic": 0.35,
    "growth": 0.20,
    "premium_justification": 0.20
}

PREMIUM_WEIGHTS = {
    "roic": 0.25,
    "revenue_cagr": 0.25, # Proxy for growth persistence
    "margin_volatility": 0.20, # Proxy for margin stability
    "fcf_margin": 0.20, # Proxy for fcf quality
    "debt_to_equity": 0.10
}

def format_percentage(val):
    if val is None: return "N/A"
    return f"{val*100:.1f}%"

def format_number(val):
    if val is None: return "N/A"
    return f"{val:.2f}"

def format_evidence_value(metric, value):
    if value is None: return "N/A"
    if 'margin' in metric or 'cagr' in metric or 'roic' in metric or 'roce' in metric or 'yield' in metric or 'volatility' in metric:
        return format_percentage(value)
    return format_number(value)

def generate_evidence(metric, value, score, name_override=None):
    val_str = format_evidence_value(metric, value)
    name = name_override if name_override else metric.replace('_', ' ').title()
    
    if score >= 80:
        return "positive", f"✓ {name} ({val_str})"
    elif score <= 40:
        return "negative", f"✗ {name} ({val_str})"
    return "warnings", f"! {name} is average ({val_str})"

def score_relative(facts, sector_medians=None):
    score = 0
    metrics_found = 0
    evidence = []
    
    pe = facts.get('pe')
    if pe is not None and pe > 0:
        if pe <= 15: m_score = 100
        elif pe <= 25: m_score = 80
        elif pe <= 40: m_score = 60
        elif pe <= 60: m_score = 40
        else: m_score = 20
        score += m_score
        metrics_found += 1
        ev_type, msg = generate_evidence('pe', pe, m_score, "P/E Ratio")
        evidence.append((ev_type, msg))
        
    pb = facts.get('pb')
    if pb is not None and pb > 0:
        if pb <= 1.5: m_score = 100
        elif pb <= 3.0: m_score = 80
        elif pb <= 5.0: m_score = 60
        elif pb <= 10.0: m_score = 40
        else: m_score = 20
        score += m_score
        metrics_found += 1
        ev_type, msg = generate_evidence('pb', pb, m_score, "P/B Ratio")
        evidence.append((ev_type, msg))
        
    if metrics_found == 0:
        return None, evidence
    return score / metrics_found, evidence

def score_intrinsic(facts):
    score = 0
    metrics_found = 0
    evidence = []
    
    # FCF Yield = FCF / Market Cap
    # We might not have market cap in facts, but we have fcf_margin and ps.
    # Alternatively, PE inverted is Earnings Yield.
    pe = facts.get('pe')
    if pe is not None and pe > 0:
        earnings_yield = 1.0 / pe
        if earnings_yield >= 0.08: m_score = 100
        elif earnings_yield >= 0.05: m_score = 80
        elif earnings_yield >= 0.03: m_score = 60
        elif earnings_yield >= 0.01: m_score = 40
        else: m_score = 20
        score += m_score
        metrics_found += 1
        ev_type, msg = generate_evidence('earnings_yield', earnings_yield, m_score, "Earnings Yield")
        evidence.append((ev_type, msg))
        
    # We can also use EPS and Current Price to do DCF-lite later if needed
    if metrics_found == 0:
        return None, evidence
    return score / metrics_found, evidence

def score_growth(facts):
    score = 0
    metrics_found = 0
    evidence = []
    
    peg = facts.get('peg')
    if peg is not None and peg > 0:
        if peg <= 1.0: m_score = 100
        elif peg <= 1.5: m_score = 80
        elif peg <= 2.0: m_score = 60
        elif peg <= 3.0: m_score = 40
        else: m_score = 20
        score += m_score
        metrics_found += 1
        ev_type, msg = generate_evidence('peg', peg, m_score, "PEG Ratio")
        evidence.append((ev_type, msg))
        
    if metrics_found == 0:
        return None, evidence
    return score / metrics_found, evidence

def score_premium(facts):
    score = 0
    total_weight = 0
    evidence = []
    
    for metric, weight in PREMIUM_WEIGHTS.items():
        val = facts.get(metric)
        if val is not None:
            m_score = 50
            if metric == 'roic':
                if val >= 0.20: m_score = 100
                elif val >= 0.15: m_score = 80
                elif val < 0.10: m_score = 20
            elif metric == 'revenue_cagr':
                if val >= 0.15: m_score = 100
                elif val >= 0.10: m_score = 80
                elif val < 0.05: m_score = 20
            elif metric == 'margin_volatility':
                if val <= 0.02: m_score = 100
                elif val <= 0.05: m_score = 80
                elif val > 0.10: m_score = 20
            elif metric == 'fcf_margin':
                if val >= 0.15: m_score = 100
                elif val >= 0.10: m_score = 80
                elif val < 0.05: m_score = 20
            elif metric == 'debt_to_equity':
                if val <= 0.20: m_score = 100
                elif val <= 0.50: m_score = 80
                elif val > 1.00: m_score = 20
                
            score += m_score * weight
            total_weight += weight
            
            ev_type, msg = generate_evidence(metric, val, m_score, f"Premium Justifier: {metric.replace('_', ' ').title()}")
            evidence.append((ev_type, msg))
            
    if total_weight == 0:
        return None, evidence
    return score / total_weight, evidence

def calculate_valuation(facts, sector_medians=None) -> EngineResult:
    """
    Computes Valuation Score based on raw facts.
    """
    evidence = EvidenceCard()
    
    scores = {
        'relative': score_relative(facts, sector_medians),
        'intrinsic': score_intrinsic(facts),
        'growth': score_growth(facts),
        'premium_justification': score_premium(facts)
    }
    
    total_score = 0
    total_weight = 0
    found_categories = 0
    
    for category, (cat_score, cat_evidence) in scores.items():
        if cat_score is not None:
            weight = VALUATION_WEIGHTS[category]
            total_score += cat_score * weight
            total_weight += weight
            found_categories += 1
            for ev_type, msg in cat_evidence:
                getattr(evidence, ev_type).append(msg)
                
    coverage = (found_categories / len(VALUATION_WEIGHTS)) * 100
    confidence = coverage
    
    if total_weight > 0:
        normalized_score = total_score / total_weight
    else:
        normalized_score = 0
        
    warnings = []
    if coverage < 50:
        msg = f"! Low valuation coverage ({coverage:.0f}%)."
        evidence.warnings.append(msg)
        warnings.append(msg)
        
    return EngineResult(
        score=round(normalized_score, 2),
        confidence=round(confidence, 2),
        coverage=round(coverage, 2),
        status='READY',
        evidence=evidence,
        warnings=warnings
    )
