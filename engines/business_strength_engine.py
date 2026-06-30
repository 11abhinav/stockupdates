import logging
from engines.base import EngineResult, EvidenceCard

log = logging.getLogger("engines.business_strength_engine")

STRENGTH_WEIGHTS = {
    "profitability": {"weight": 0.30, "metrics": ["roic", "roce", "fcf_margin", "gross_margin"]},
    "growth_quality": {"weight": 0.20, "metrics": ["revenue_cagr", "eps_cagr", "fcf_cagr"]},
    "financial_strength": {"weight": 0.20, "metrics": ["debt_to_equity", "cash_conversion", "interest_coverage"]},
    "capital_allocation": {"weight": 0.15, "metrics": ["reinvestment", "buyback_yield"]},
    "business_consistency": {"weight": 0.15, "metrics": ["margin_volatility", "capital_intensity"]}
}

def score_metric(metric_name, value):
    """
    Returns a score between 0 and 100 for a given raw metric value.
    """
    if value is None:
        return None
        
    if metric_name in ['roic', 'roce']:
        if value >= 0.20: return 100
        elif value >= 0.15: return 80
        elif value >= 0.10: return 60
        elif value >= 0.05: return 40
        else: return 20
        
    elif metric_name == 'fcf_margin':
        if value >= 0.15: return 100
        elif value >= 0.10: return 80
        elif value >= 0.05: return 60
        elif value > 0: return 40
        else: return 0
        
    elif metric_name == 'gross_margin':
        if value >= 0.40: return 100
        elif value >= 0.30: return 80
        elif value >= 0.20: return 60
        elif value >= 0.10: return 40
        else: return 20
        
    elif metric_name in ['revenue_cagr', 'eps_cagr', 'fcf_cagr']:
        if value >= 0.15: return 100
        elif value >= 0.10: return 80
        elif value >= 0.05: return 60
        elif value >= 0: return 40
        else: return 0
        
    elif metric_name == 'debt_to_equity':
        if value <= 0.20: return 100
        elif value <= 0.50: return 80
        elif value <= 1.00: return 60
        elif value <= 2.00: return 40
        else: return 0
        
    elif metric_name == 'cash_conversion':
        if value >= 1.0: return 100
        elif value >= 0.75: return 80
        elif value >= 0.50: return 60
        elif value > 0: return 40
        else: return 0
        
    elif metric_name == 'interest_coverage':
        if value >= 10: return 100
        elif value >= 5: return 80
        elif value >= 3: return 60
        elif value >= 1.5: return 40
        else: return 0
        
    elif metric_name == 'reinvestment':
        if value >= 0.50: return 100
        elif value >= 0.25: return 80
        elif value > 0: return 60
        else: return 40
        
    elif metric_name == 'buyback_yield':
        if value >= 0.02: return 100
        elif value > 0: return 80
        else: return 50
        
    elif metric_name == 'margin_volatility':
        # Lower volatility is better
        if value <= 0.02: return 100
        elif value <= 0.05: return 80
        elif value <= 0.10: return 60
        elif value <= 0.20: return 40
        else: return 20
        
    elif metric_name == 'capital_intensity':
        # Lower intensity is better
        if value <= 0.10: return 100
        elif value <= 0.20: return 80
        elif value <= 0.40: return 60
        elif value <= 0.60: return 40
        else: return 20
        
    return 50 # Default fallback

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

def generate_evidence(metric, value, score):
    val_str = format_evidence_value(metric, value)
    name = metric.replace('_', ' ').title()
    
    if score >= 80:
        return "positive", f"✓ {name} is strong ({val_str})"
    elif score <= 40:
        return "negative", f"✗ {name} is weak ({val_str})"
    return "warnings", f"! {name} is average ({val_str})"

def calculate_business_strength(facts) -> EngineResult:
    """
    Computes Business Strength Score based on raw facts.
    """
    evidence = EvidenceCard()
    
    total_score = 0
    total_weight = 0
    total_metrics_possible = 0
    total_metrics_found = 0

    for category, config in STRENGTH_WEIGHTS.items():
        cat_weight = config['weight']
        cat_metrics = config['metrics']
        
        cat_score_sum = 0
        cat_metrics_found = 0
        
        for metric in cat_metrics:
            total_metrics_possible += 1
            if metric in facts and facts[metric] is not None:
                val = facts[metric]
                m_score = score_metric(metric, val)
                if m_score is not None:
                    cat_score_sum += m_score
                    cat_metrics_found += 1
                    total_metrics_found += 1
                    
                    ev_type, ev_msg = generate_evidence(metric, val, m_score)
                    getattr(evidence, ev_type).append(ev_msg)
                    
        if cat_metrics_found > 0:
            cat_avg = cat_score_sum / cat_metrics_found
            total_score += cat_avg * cat_weight
            total_weight += cat_weight

    coverage = (total_metrics_found / total_metrics_possible) * 100 if total_metrics_possible > 0 else 0
    
    # Confidence is heavily tied to coverage, but also penalized if critical metrics like ROIC/Revenue are missing
    confidence = coverage
    if 'roic' not in facts or facts['roic'] is None:
        confidence *= 0.8
    if 'revenue_cagr' not in facts or facts['revenue_cagr'] is None:
        confidence *= 0.9

    if total_weight > 0:
        normalized_score = (total_score / total_weight)
    else:
        normalized_score = 0

    warnings = []
    # Add coverage warning if low
    if coverage < 50:
        msg = f"! Low data coverage ({coverage:.0f}%). Score may be inaccurate."
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
