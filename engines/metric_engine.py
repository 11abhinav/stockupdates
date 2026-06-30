import logging

log = logging.getLogger("engines.metric_engine")

def extract_raw_metrics(info, financials, balance_sheet, cashflow):
    """
    Extracts and derives raw financial metrics.
    Returns ONLY facts. No scoring, no normalization.
    """
    facts = {}
    
    def safe_get_series(df, row_name):
        if df is not None and not df.empty and row_name in df.index:
            return df.loc[row_name]
        return None

    def get_latest(series):
        if series is not None and len(series) > 0:
            return series.iloc[0]
        return None
        
    def get_past(series, years_back=3):
        if series is not None and len(series) > years_back:
            return series.iloc[years_back]
        return None

    def safe_div(a, b):
        if a is not None and b is not None and b != 0:
            return a / b
        return None

    def cagr(ending, beginning, years):
        if ending is not None and beginning is not None and beginning > 0 and ending > 0:
            return (ending / beginning) ** (1 / years) - 1
        return None

    # Basic info metrics
    facts['pe'] = info.get('trailingPE') or info.get('peRatio')
    facts['forward_pe'] = info.get('forwardPE')
    facts['pb'] = info.get('priceToBook') or info.get('pbRatio')
    facts['ps'] = info.get('priceToSalesTrailing12Months')
    facts['peg'] = info.get('pegRatio')
    facts['current_price'] = info.get('currentPrice') or info.get('regularMarketPrice')
    facts['eps'] = info.get('trailingEps')
    
    # Pre-calculated from info where available
    facts['roic'] = info.get('returnOnEquity') # Using ROE as fallback if ROIC not explicitly available
    facts['gross_margin'] = info.get('grossMargins')
    facts['operating_margin'] = info.get('operatingMargins')
    facts['debt_to_equity'] = info.get('debtToEquity')
    
    if facts['debt_to_equity'] is not None:
        facts['debt_to_equity'] /= 100.0  # yfinance returns 12.5 for 12.5%

    # Calculate from financials (Income Statement)
    net_income = safe_get_series(financials, 'Net Income')
    total_revenue = safe_get_series(financials, 'Total Revenue')
    ebit = safe_get_series(financials, 'EBIT')
    interest_expense = safe_get_series(financials, 'Interest Expense')
    
    # Calculate from Balance Sheet
    total_assets = safe_get_series(balance_sheet, 'Total Assets')
    total_liab = safe_get_series(balance_sheet, 'Total Liabilities Net Minority Interest')
    stockholders_equity = safe_get_series(balance_sheet, 'Stockholders Equity')
    
    # Calculate from Cashflow
    operating_cf = safe_get_series(cashflow, 'Operating Cash Flow')
    free_cf = safe_get_series(cashflow, 'Free Cash Flow')
    capex = safe_get_series(cashflow, 'Capital Expenditure')
    repurchase_shares = safe_get_series(cashflow, 'Repurchase Of Capital Stock')

    # Latest Values
    rev_latest = get_latest(total_revenue)
    fcf_latest = get_latest(free_cf)
    ni_latest = get_latest(net_income)
    ebit_latest = get_latest(ebit)
    int_exp_latest = get_latest(interest_expense)
    assets_latest = get_latest(total_assets)
    equity_latest = get_latest(stockholders_equity)
    ocf_latest = get_latest(operating_cf)
    capex_latest = get_latest(capex)

    # Derived Metrics (Profitability)
    if facts['roic'] is None and ebit_latest is not None and equity_latest is not None:
        # Approximate ROIC / ROCE if not in info
        facts['roic'] = safe_div(ebit_latest, equity_latest)
        
    facts['roce'] = safe_div(ebit_latest, assets_latest) if ebit_latest and assets_latest else None
    facts['fcf_margin'] = safe_div(fcf_latest, rev_latest)
    
    # Derived Metrics (Growth)
    rev_3y = get_past(total_revenue, 3)
    ni_3y = get_past(net_income, 3)
    fcf_3y = get_past(free_cf, 3)
    
    facts['revenue_cagr'] = cagr(rev_latest, rev_3y, 3)
    facts['eps_cagr'] = cagr(ni_latest, ni_3y, 3) # Proxied by net income growth
    facts['fcf_cagr'] = cagr(fcf_latest, fcf_3y, 3)

    # Derived Metrics (Financial Strength)
    facts['interest_coverage'] = safe_div(ebit_latest, abs(int_exp_latest)) if ebit_latest and int_exp_latest else None
    facts['cash_conversion'] = safe_div(ocf_latest, ni_latest)
    
    # Capital Allocation
    facts['reinvestment'] = safe_div(abs(capex_latest), ocf_latest) if capex_latest and ocf_latest else None
    
    buyback_latest = get_latest(repurchase_shares)
    facts['buyback_yield'] = safe_div(abs(buyback_latest), info.get('marketCap')) if buyback_latest and info.get('marketCap') else None
    
    # Trends (Consistency / Durability)
    if total_revenue is not None and len(total_revenue) >= 3 and ebit is not None and len(ebit) >= 3:
        margins = [safe_div(e, r) for e, r in zip(ebit.dropna(), total_revenue.dropna())]
        margins = [m for m in margins if m is not None]
        if len(margins) >= 3:
            facts['margin_stability'] = sum(margins) / len(margins) # Could be stdev, using average for now to proxy stability or just the margin itself? Actually stdev is better.
            import statistics
            try:
                facts['margin_volatility'] = statistics.stdev(margins)
            except:
                facts['margin_volatility'] = None
                
    facts['capital_intensity'] = safe_div(abs(capex_latest), rev_latest) if capex_latest and rev_latest else None

    # Filter out None values to keep the dictionary clean
    return {k: v for k, v in facts.items() if v is not None}
