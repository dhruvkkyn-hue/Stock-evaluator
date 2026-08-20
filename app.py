import streamlit as st
import pandas as pd
import openpyxl
import io
import zipfile
import re
import yfinance as yf
import plotly.express as px
import plotly.graph_objects as go
import traceback
from datetime import datetime

# ─────────────────────────────────────────────────────────────────────────────
# 1. UI/UX: INSTITUTIONAL CSS INJECTION
# ─────────────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Institutional Equity Terminal", 
    layout="wide", 
    page_icon="💎"
)

def inject_custom_css():
    st.markdown("""
    <style>
        :root {
            --bg-dark: #0e1117;
            --card-bg: #161b22;
            --card-hover: #1c2128;
            --border-color: #30363d;
            --text-main: #c9d1d9;
            --text-heading: #ffffff;
            --accent-emerald: #10b981;
            --accent-blue: #3b82f6;
            --accent-orange: #f59e0b;
        }
        .stApp { background-color: var(--bg-dark); color: var(--text-main); }
        
        div[data-testid="stMetric"] {
            background-color: var(--card-bg);
            border: 1px solid var(--border-color);
            padding: 18px;
            border-radius: 10px;
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.35);
            transition: transform 0.2s ease, border-color 0.2s ease;
        }
        div[data-testid="stMetric"]:hover {
            border-color: var(--accent-emerald);
            transform: translateY(-2px);
        }
        
        h1, h2, h3, h4 { 
            color: var(--text-heading) !important; 
            font-family: 'Inter', system-ui, -apple-system, sans-serif;
            font-weight: 700;
        }
        .hero-title {
            font-size: 2.3rem;
            font-weight: 800;
            background: linear-gradient(90deg, #ffffff, #94a3b8);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            margin-bottom: 0.2rem;
        }
        .hero-subtitle { 
            color: #8b949e; 
            font-size: 1.05rem; 
            margin-bottom: 1.8rem; 
        }
        
        .stTabs [data-baseweb="tab-list"] { 
            gap: 10px; 
            border-bottom: 1px solid var(--border-color);
        }
        .stTabs [data-baseweb="tab"] {
            background-color: var(--card-bg);
            border: 1px solid var(--border-color);
            border-radius: 6px 6px 0px 0px;
            padding: 10px 24px;
            color: var(--text-main);
            font-weight: 600;
        }
        .stTabs [aria-selected="true"] {
            background-color: var(--accent-emerald) !important;
            color: #ffffff !important;
            border-color: var(--accent-emerald) !important;
        }
        
        .sector-badge {
            background-color: #1e293b;
            color: #38bdf8;
            padding: 3px 8px;
            border-radius: 4px;
            font-size: 0.8rem;
            font-weight: 600;
            border: 1px solid #0284c7;
        }
        
        .signal-tag-strong-buy {
            background-color: rgba(16, 185, 129, 0.2);
            color: #10b981;
            padding: 6px 14px;
            border-radius: 6px;
            font-size: 1.1rem;
            font-weight: 800;
            border: 1px solid #10b981;
            display: inline-block;
            margin-bottom: 12px;
        }
        .signal-tag-accumulate {
            background-color: rgba(59, 130, 246, 0.2);
            color: #3b82f6;
            padding: 6px 14px;
            border-radius: 6px;
            font-size: 1.1rem;
            font-weight: 800;
            border: 1px solid #3b82f6;
            display: inline-block;
            margin-bottom: 12px;
        }
        .signal-tag-hold {
            background-color: rgba(245, 158, 11, 0.2);
            color: #f59e0b;
            padding: 6px 14px;
            border-radius: 6px;
            font-size: 1.1rem;
            font-weight: 800;
            border: 1px solid #f59e0b;
            display: inline-block;
            margin-bottom: 12px;
        }
        .signal-tag-avoid {
            background-color: rgba(239, 68, 68, 0.2);
            color: #ef4444;
            padding: 6px 14px;
            border-radius: 6px;
            font-size: 1.1rem;
            font-weight: 800;
            border: 1px solid #ef4444;
            display: inline-block;
            margin-bottom: 12px;
        }
    </style>
    """, unsafe_allow_html=True)

inject_custom_css()

# ─────────────────────────────────────────────────────────────────────────────
# 2. QUANT ENGINE: SAFE MATH & REAL-TIME API INGESTION
# ─────────────────────────────────────────────────────────────────────────────

def safe_float(val, default=0.0):
    if val is None: 
        return default
    try:
        if isinstance(val, (int, float)): 
            return float(val)
        s = str(val).replace(',', '').replace('₹', '').replace('Rs.', '').strip()
        if s.startswith('(') and s.endswith(')'): 
            s = "-" + s[1:-1]
        return float(s) if s != '' else default
    except: 
        return default

def safe_div(n, d, default=0.0):
    try:
        n_f = float(n) if n is not None else 0.0
        d_f = float(d) if d is not None else 0.0
        return n_f / d_f if d_f != 0 else default
    except: 
        return default

def calculate_cagr(series, years):
    clean_series = [s for s in series if s is not None]
    if not clean_series or len(clean_series) < years + 1: 
        return 0.0
    try:
        start_val = clean_series[-(years + 1)]
        end_val = clean_series[-1]
        if start_val <= 0 or end_val <= 0: 
            return 0.0
        return ((end_val / start_val) ** (1 / years) - 1) * 100
    except: 
        return 0.0

def extract_yfinance_series(df, keywords):
    if df is None or df.empty:
        return None
    cols_sorted = sorted(df.columns)
    df_sorted = df[cols_sorted]
    idx_lower = [str(x).lower().strip() for x in df_sorted.index]
    for kw in keywords:
        kw_l = kw.lower().strip()
        for pos, name in enumerate(idx_lower):
            if kw_l == name or kw_l in name:
                return [safe_float(val, None) for val in df_sorted.iloc[pos].values]
    return None

@st.cache_data(ttl=300)
def fetch_company_data(symbol):
    try:
        t = yf.Ticker(symbol)
        info = t.info
        if not info or 'marketCap' not in info:
            hist = t.history(period="5d")
            if hist.empty:
                return None
        
        financials = t.financials
        balance_sheet = t.balance_sheet
        cashflow = t.cashflow
        history = t.history(period="1y")
        
        # Extract series
        sales_series = extract_yfinance_series(financials, ["Total Revenue", "Operating Revenue", "Revenue"])
        op_series = extract_yfinance_series(financials, ["Operating Income", "Operating Profit", "EBITDA", "EBIT"])
        pat_series = extract_yfinance_series(financials, ["Net Income", "Net Income Common Stockholders", "PAT"])
        pbt_series = extract_yfinance_series(financials, ["Pretax Income", "Pretax Income From Continuing Operations", "PBT"])
        interest_series = extract_yfinance_series(financials, ["Interest Expense", "Interest Expense Debt", "Finance Costs"])
        depr_series = extract_yfinance_series(financials, ["Depreciation And Amortization", "Depreciation", "Depreciation & Amortization"])
        
        debt_series = extract_yfinance_series(balance_sheet, ["Total Debt", "Long Term Debt", "Short Long Term Debt", "Borrowings"])
        equity_series = extract_yfinance_series(balance_sheet, ["Stockholders Equity", "Common Stock Equity"])
        reserves_series = extract_yfinance_series(balance_sheet, ["Retained Earnings", "Other Equity", "Surplus", "Reserves"])
        assets_series = extract_yfinance_series(balance_sheet, ["Total Assets", "Assets"])
        liab_series = extract_yfinance_series(balance_sheet, ["Total Liabilities Net Minor Interest", "Total Liabilities", "Current Liabilities"])
        receivables_series = extract_yfinance_series(balance_sheet, ["Receivables", "Accounts Receivable", "Net Receivables"])
        inventory_series = extract_yfinance_series(balance_sheet, ["Inventory", "Inventories"])
        cwip_series = extract_yfinance_series(balance_sheet, ["Capital Work In Progress", "CWIP"])
        net_block_series = extract_yfinance_series(balance_sheet, ["Net PPE", "Properties", "Property Plant Equipment", "Net Block"])
        
        cfo_series = extract_yfinance_series(cashflow, ["Operating Cash Flow", "Cash Flow From Operating Activities", "CFO"])
        cfi_series = extract_yfinance_series(cashflow, ["Investing Cash Flow", "Cash Flow From Investing Activities", "CFI"])
        capex_series = extract_yfinance_series(cashflow, ["Capital Expenditure", "Capital Expenditures", "CapEx", "Purchase Of Property Plant And Equipment"])
        
        # Fallbacks for current values
        curr_sales = sales_series[-1] if sales_series else safe_float(info.get("totalRevenue"), 0.0)
        curr_op = op_series[-1] if op_series else safe_float(info.get("ebitda"), 0.0)
        curr_pat = pat_series[-1] if pat_series else safe_float(info.get("netIncomeToCommon"), 0.0)
        curr_pbt = pbt_series[-1] if pbt_series else curr_pat
        curr_interest = interest_series[-1] if interest_series else 0.0
        curr_depr = depr_series[-1] if depr_series else 0.0
        curr_debt = debt_series[-1] if debt_series else safe_float(info.get("totalDebt"), 0.0)
        curr_equity = equity_series[-1] if equity_series else 0.0
        curr_reserves = reserves_series[-1] if reserves_series else 0.0
        curr_assets = assets_series[-1] if assets_series else 0.0
        curr_liab = liab_series[-1] if liab_series else 0.0
        curr_receivables = receivables_series[-1] if receivables_series else 0.0
        curr_inventory = inventory_series[-1] if inventory_series else 0.0
        curr_cwip = cwip_series[-1] if cwip_series else 0.0
        curr_net_block = net_block_series[-1] if net_block_series else 0.0
        curr_cfo = cfo_series[-1] if cfo_series else 0.0
        curr_cfi = cfi_series[-1] if cfi_series else 0.0
        curr_capex = capex_series[-1] if capex_series else 0.0
        
        company_name = info.get("longName") or info.get("shortName") or symbol
        is_fin = info.get("sector") == "Financial Services" or any(x in str(info.get("industry")).lower() for x in ["bank", "insurance", "capital markets", "financial"])
        
        raw_mcap = safe_float(info.get("marketCap"), 0.0)
        res = {
            "Company": company_name,
            "Symbol": symbol.upper(),
            "Is_Financial": is_fin,
            "Sector_Type": "Financial / Banking" if is_fin else "Industrial / Commercial",
            "Price": safe_float(info.get("currentPrice") or info.get("navPrice") or (history['Close'].iloc[-1] if not history.empty else 0.0)),
            "Market Cap": raw_mcap,
            "Market Cap Raw": raw_mcap
        }
        
        local_equity = curr_equity if curr_equity > 0 else (curr_reserves + 1.0)
        local_debt = curr_debt
        local_assets = curr_assets if curr_assets > 0 else (local_equity + local_debt + curr_liab)
        local_pat = curr_pat
        local_pbt = curr_pbt
        local_cfo = curr_cfo
        local_sales = curr_sales
        local_mcap = raw_mcap
        
        capex_val = abs(curr_capex) if curr_capex != 0 else abs(curr_cfi)
        fcf_val = local_cfo - capex_val
        res["FCF"] = fcf_val
        res["FCF Yield %"] = safe_div(fcf_val, local_mcap) * 100
        
        if is_fin:
            local_ebit = local_pbt if local_pbt != 0 else local_pat
            res["Interest Coverage"] = None
        else:
            local_ebit = (local_pbt + curr_interest) if (local_pbt != 0 or curr_interest != 0) else curr_op
            res["Interest Coverage"] = safe_div(local_ebit, curr_interest, default=999.0) if curr_interest > 0 else 999.0

        res["Sales"] = local_sales
        res["Net Profit"] = local_pat
        res["PE"] = safe_float(info.get("trailingPE") or info.get("forwardPE") or safe_div(local_mcap, local_pat))
        res["EV/EBITDA"] = safe_float(info.get("enterpriseToEbitda") or safe_div(local_mcap + local_debt, curr_op))
        res["D/E"] = safe_div(local_debt, local_equity)
        
        if is_fin:
            res["OPM %"] = safe_div(local_pat, local_sales) * 100
            res["ROE %"] = safe_div(local_pat, local_equity) * 100
            res["ROCE %"] = safe_div(local_ebit, local_equity + local_debt) * 100
        else:
            res["OPM %"] = safe_div(curr_op, local_sales) * 100
            res["ROE %"] = safe_div(local_pat, local_equity) * 100
            res["ROCE %"] = safe_div(local_ebit, local_equity + local_debt) * 100

        res["CWIP to Net Block %"] = safe_div(curr_cwip, curr_net_block) * 100 if curr_net_block > 0 else 0.0
        res["3Yr Sales CAGR %"] = calculate_cagr(sales_series, 3) if sales_series else 0.0
        res["3Yr PAT CAGR %"] = calculate_cagr(pat_series, 3) if pat_series else 0.0
        
        if is_fin:
            res["Sloan %"] = None
        else:
            res["Sloan %"] = safe_div(local_pat - local_cfo, local_assets) * 100

        if is_fin:
            res["Altman Z"] = None
            res["Zone"] = "N/A (Financial)"
        else:
            wc_proxy = (curr_receivables + curr_inventory + (local_assets * 0.05)) - curr_liab
            z_val = (
                (1.2 * safe_div(wc_proxy, local_assets)) + 
                (1.4 * safe_div(curr_reserves, local_assets)) + 
                (3.3 * safe_div(curr_op, local_assets)) + 
                (0.6 * safe_div(local_mcap, local_debt + curr_liab)) + 
                (0.99 * safe_div(local_sales, local_assets))
            )
            res["Altman Z"] = z_val
            res["Zone"] = "Safe" if z_val > 2.99 else "Grey" if z_val >= 1.81 else "Distress"

        # Piotroski F-Score (out of 8 metrics)
        p_score = 0
        if local_pat > 0: p_score += 1
        if local_cfo > 0: p_score += 1
        if local_cfo > local_pat: p_score += 1
        if res["3Yr PAT CAGR %"] > 0: p_score += 1
        
        if debt_series and len(debt_series) > 1 and equity_series and len(equity_series) > 1:
            prev_eq = equity_series[-2]
            prev_de = safe_div(debt_series[-2], prev_eq)
            if res["D/E"] <= prev_de: p_score += 1
            
        if res["ROCE %"] > 12: p_score += 1
        if res["3Yr Sales CAGR %"] > 0: p_score += 1
        if local_assets > 0: p_score += 1
        res["Piotroski"] = p_score

        # Technical Indicators from history
        if not history.empty and len(history) >= 200:
            res["SMA_200"] = safe_float(history['Close'].rolling(window=200).mean().iloc[-1])
        else:
            res["SMA_200"] = None
            
        if not history.empty and len(history) >= 14:
            # RSI
            delta = history['Close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rs = gain / loss
            rsi = 100 - (100 / (1 + rs))
            res["RSI_14"] = safe_float(rsi.iloc[-1])
            
            # ATR
            high_low = history['High'] - history['Low']
            high_close = (history['High'] - history['Close'].shift()).abs()
            low_close = (history['Low'] - history['Close'].shift()).abs()
            ranges = pd.concat([high_low, high_close, low_close], axis=1)
            true_range = ranges.max(axis=1)
            res["ATR_14"] = safe_float(true_range.rolling(14).mean().iloc[-1])
        else:
            res["RSI_14"] = None
            res["ATR_14"] = None

        return res, history
    except Exception as e:
        st.error(f"Error fetching data for {symbol}: {str(e)}")
        return None

# ─────────────────────────────────────────────────────────────────────────────
# 3. 3-TIER INVESTOR EXPERIENCE NARRATIVE ENGINE
# ─────────────────────────────────────────────────────────────────────────────

def get_metric_meta(metric_name, row):
    val = row.get(metric_name)
    is_fin = row["Is_Financial"]
    
    if metric_name == "PE":
        if val <= 0: return "[🔴 WEAK]"
        return "[🟢 STRONG]" if val <= 20 else ("[🟡 AVERAGE]" if val <= 40 else "[🔴 WEAK]")
    elif metric_name == "OPM %":
        return "[🟢 STRONG]" if val >= 18 else ("[🟡 AVERAGE]" if val >= 10 else "[🔴 WEAK]")
    elif metric_name == "ROE %":
        return "[🟢 STRONG]" if val >= 18 else ("[🟡 AVERAGE]" if val >= 12 else "[🔴 WEAK]")
    elif metric_name == "ROCE %":
        return "[🟢 STRONG]" if val >= 15 else ("[🟡 AVERAGE]" if val >= 10 else "[🔴 WEAK]")
    elif metric_name == "D/E":
        if is_fin:
            return "[🟢 STRONG]" if val <= 6.0 else ("[🟡 AVERAGE]" if val <= 8.5 else "[🔴 WEAK]")
        return "[🟢 STRONG]" if val <= 0.5 else ("[🟡 AVERAGE]" if val <= 1.2 else "[🔴 WEAK]")
    elif metric_name == "Altman Z":
        if is_fin or val is None: return "[🟢 STRONG]"
        return "[🟢 STRONG]" if val > 2.99 else ("[🟡 AVERAGE]" if val >= 1.81 else "[🔴 WEAK]")
    elif metric_name == "Piotroski":
        return "[🟢 STRONG]" if val >= 6 else ("[🟡 AVERAGE]" if val >= 4 else "[🔴 WEAK]")
    elif metric_name == "FCF Yield %":
        return "[🟢 STRONG]" if val >= 5.0 else ("[🟡 AVERAGE]" if val >= 1.0 else "[🔴 WEAK]")
    elif metric_name == "Sloan %":
        if is_fin or val is None: return "[🟡 AVERAGE]"
        return "[🟢 STRONG]" if (val <= 5.0 and val >= -10.0) else ("[🟡 AVERAGE]" if val <= 10.0 else "[🔴 WEAK]")
    return "[🟡 AVERAGE]"

# -- BEGINNER LEVEL --
def get_beginner_metric_desc(metric, row):
    comp = row["Company"]
    is_fin = row["Is_Financial"]
    tag = get_metric_meta(metric, row)
    val = row.get(metric)
    
    if metric == "PE":
        analogy = "P/E is like how many years of business profits you're paying upfront to buy the stock today."
        wrong = "A low P/E can be a trap if the company's business model is failing and profits are about to drop permanently."
        insight = f"At {val:.1f}x earnings, " + ("this is a cheap entry point." if val <= 20 else "it's moderately valued." if val <= 40 else "it's priced at a high premium.")
        return f"**Valuation P/E Tag: {tag}**\n- 💡 Analogy: {analogy}\n- 🔍 Insight: {insight}\n- ⚠️ Limitation: {wrong}"
        
    elif metric == "OPM %":
        analogy = "Operating Profit Margin is the spare cents left from every $1 of revenue after paying for inventory and running costs."
        wrong = "A high margin can look great during industry boom years, but might drop sharply if raw materials get expensive."
        insight = f"At {val:.1f}%, the business " + ("retains high operational profits." if val >= 18 else "keeps an average profit margin.")
        return f"**Operating Profit Margin (OPM %): {tag}**\n- 💡 Analogy: {analogy}\n- 🔍 Insight: {insight}\n- ⚠️ Limitation: {wrong}"

    elif metric == "ROE %":
        analogy = "Return on Equity is how much profit the company earns using the capital owners put into the business."
        wrong = "A company can make ROE look high simply by borrowing lots of risky debt, which shrinks equity but raises bankruptcy risk."
        insight = f"At {val:.1f}% ROE, compounding performance is " + ("exceptional." if val >= 18 else "moderate.")
        return f"**Return on Equity (ROE %): {tag}**\n- 💡 Analogy: {analogy}\n- 🔍 Insight: {insight}\n- ⚠️ Limitation: {wrong}"

    elif metric == "ROCE %":
        analogy = "Return on Capital Employed is how much profit a company generates using ALL capital raised, owners' money and loans combined."
        wrong = "Old factories that are fully paid off make ROCE look high, even if the machinery is outdated and needs replacement."
        insight = f"ROCE is {val:.1f}%, showing " + ("strong investment returns on resources." if val >= 15 else "average resource efficiency.")
        return f"**Return on Capital Employed (ROCE %): {tag}**\n- 💡 Analogy: {analogy}\n- 🔍 Insight: {insight}\n- ⚠️ Limitation: {wrong}"

    elif metric == "D/E":
        analogy = "Debt-to-Equity compares what the company owes to banks with what the owners themselves invested."
        wrong = "Infrastructure companies naturally carry high debt safely due to long-term government contracts."
        insight = f"With {val:.2f}x leverage, the borrowing burden is " + ("very low and safe." if val <= 0.5 else "manageable." if val <= 1.2 else "high.")
        return f"**Debt-to-Equity (Leverage Ratio): {tag}**\n- 💡 Analogy: {analogy}\n- 🔍 Insight: {insight}\n- ⚠️ Limitation: {wrong}"

    elif metric == "Sloan %":
        analogy = "Sloan Accrual Ratio checks if reported profits are real cash in the bank or just unpaid IOUs on paper."
        wrong = "Fast-growing companies might have temporary high accruals simply because they sold a lot of goods on credit."
        insight = f"Sloan Ratio is {val if val is None else f'{val:.1f}%'}, which means " + ("paper profit disconnect is low." if (val or 0) <= 5 else "accruals are normal." if (val or 0) <= 10 else "accrual risk is high.")
        return f"**Sloan Accrual Ratio (Cash Quality): {tag}**\n- 💡 Analogy: {analogy}\n- 🔍 Insight: {insight}\n- ⚠️ Limitation: {wrong}"

    elif metric == "Altman Z":
        analogy = "Altman Z is like a health score for a company's balance sheet, diagnosing bankruptcy risk."
        wrong = "Software firms trigger false alarms here because they don't hold physical assets like factories."
        insight = f"Altman Z points to a **{row['Zone']}** status."
        return f"**Altman Z-Score (Bankruptcy Health): {tag}**\n- 💡 Analogy: {analogy}\n- 🔍 Insight: {insight}\n- ⚠️ Limitation: {wrong}"

    elif metric == "Piotroski":
        analogy = "Piotroski is a report card checking financial checks: profit growth, debt paydown, and efficiency."
        wrong = "It compares this year to last year; a strong business that made heavy expansion investments might score low temporarily."
        insight = f"The stock scores **{val}/8** on fundamental tests."
        return f"**Piotroski F-Score (8-Point Report Card): {tag}**\n- 💡 Analogy: {analogy}\n- 🔍 Insight: {insight}\n- ⚠️ Limitation: {wrong}"

    elif metric == "FCF Yield %":
        analogy = "Free Cash Flow Yield is the spare cash generated divided by the company's price tag."
        wrong = "FCF yield can look negative if the company is building a massive new factory that will generate profits later."
        insight = f"At {val:.1f}%, spare cash generation is " + ("exceptional." if val >= 5.0 else "moderate.")
        return f"**Free Cash Flow Yield (Spare Cash Power): {tag}**\n- 💡 Analogy: {analogy}\n- 🔍 Insight: {insight}\n- ⚠️ Limitation: {wrong}"

    return ""

# -- INTERMEDIATE LEVEL --
def get_intermediate_metric_desc(metric, row):
    val = row.get(metric)
    tag = get_metric_meta(metric, row)
    
    if metric == "PE":
        return f"**Valuation P/E:** {val:.1f}x ({tag}) - Priced relative to peer averages. Growth rates must sustain multiple expansion."
    elif metric == "OPM %":
        return f"**Operating Margin (OPM):** {val:.1f}% ({tag}) - Reflects pricing power and operational cost structure relative to sector."
    elif metric == "ROE %":
        return f"**Return on Equity (ROE):** {val:.1f}% ({tag}) - Measures net profit returned as a percentage of shareholder equity."
    elif metric == "ROCE %":
        return f"**Return on Capital Employed (ROCE):** {val:.1f}% ({tag}) - Reflects asset utilization and return on all debt and equity capitals."
    elif metric == "D/E":
        return f"**Debt-to-Equity (D/E):** {val:.2f}x ({tag}) - Financial leverage profile. Balance sheet risk is moderate if coverage holds."
    elif metric == "Sloan %":
        return f"**Sloan Accruals:** {val if val is None else f'{val:.1f}%'} ({tag}) - Accrual component check. Lower accruals represent higher cash backing."
    elif metric == "Altman Z":
        return f"**Altman Z-Score:** {val if val is None else f'{val:.2f}'} ({row['Zone']}) ({tag}) - Statistical solvency measure."
    elif metric == "Piotroski":
        return f"**Piotroski F-Score:** {val}/8 ({tag}) - Year-on-year operational and liquidity trajectory score."
    elif metric == "FCF Yield %":
        return f"**FCF Yield:** {val:.1f}% ({tag}) - Cash return relative to capitalization. Supports capital returns."
    return ""

# -- PRO / INSTITUTIONAL LEVEL --
def get_pro_metric_desc(metric, row):
    val = row.get(metric)
    
    if metric == "PE":
        return f"**Earnings Multiple (P/E Ratio):** {val:.1f}x. Pricing sensitivity: WACC vs. long-term compounding growth."
    elif metric == "OPM %":
        return f"**Operating Profit Margin (OPM):** {val:.1f}%. Margin stability, cost architecture, and operational leverage potential."
    elif metric == "ROE %":
        return f"**ROE:** {val:.1f}%. Capital compounding efficiency. Formula: `PAT / (Share Capital + Reserves)`."
    elif metric == "ROCE %":
        return f"**ROCE:** {val:.1f}%. Return on Employed Capital. Formula: `EBIT / (Total Equity + Borrowings)`."
    elif metric == "D/E":
        return f"**D/E:** {val:.2f}x. Debt-to-Equity gearing, capital structure optimization, interest coverage risk metrics."
    elif metric == "Sloan %":
        s_val = f"{val:.2f}%" if val is not None else "N/A"
        return f"**Sloan Accrual:** {s_val}. Formula: `(PAT - CFO) / Total Assets`. Measures accounting quality and non-cash items."
    elif metric == "Altman Z":
        z_val = f"{val:.2f}" if val is not None else "N/A"
        return f"**Altman Z-Score:** {z_val} (Zone: {row['Zone']}). Multi-factor financial model assessing liquidity, solvency, leverage, and asset turnover."
    elif metric == "Piotroski":
        return f"**Piotroski F-Score:** {val}/8. Boolean tests for profitability, operational leverage, and asset-turn efficiency."
    elif metric == "FCF Yield %":
        return f"**FCF Yield:** {val:.1f}%. Free Cash Flow Yield. Formula: `(CFO - CapEx) / Market Cap`."
    return ""

def render_expertise_deep_dive(row, category, level):
    metrics_map = {
        "valuation": ["PE", "EV/EBITDA", "OPM %"],
        "capital": ["ROE %", "ROCE %", "Sloan %", "FCF Yield %"],
        "solvency": ["Altman Z", "Piotroski", "D/E", "Interest Coverage"]
    }
    
    metrics = metrics_map[category]
    output = []
    
    for m in metrics:
        if "Beginner" in level:
            desc = get_beginner_metric_desc(m, row)
        elif "Intermediate" in level:
            desc = get_intermediate_metric_desc(m, row)
        else:
            desc = get_pro_metric_desc(m, row)
        if desc:
            output.append(desc)
            
    return "\n\n".join(output)

def generate_pros_and_cons(row):
    comp = row["Company"]
    is_fin = row["Is_Financial"]
    roe = row["ROE %"]
    roce = row["ROCE %"]
    pe = row["PE"]
    de = row["D/E"]
    sloan = row["Sloan %"]
    p_score = row["Piotroski"]
    zone = row["Zone"]
    fcf_y = row["FCF Yield %"]

    pros = [
        f"**Capital Compounding:** Generates an ROE of {roe:.1f}% and ROCE of {roce:.1f}%, proving strong reinvestment yields.",
        f"**Cash Generation:** Delivers a Free Cash Flow Yield of {fcf_y:.1f}%, confirming profits translate into real bankable cash.",
        f"**Fundamental Health:** Piotroski Quality Score of {p_score}/8 confirms healthy operational momentum and asset efficiency."
    ]

    cons = [
        f"**Valuation Premium:** Trades at a P/E multiple of {pe:.1f}x, requiring sustained profit execution.",
        f"**Leverage & Borrowing:** Debt-to-Equity stands at {de:.2f}x, exposing earnings to interest rate fluctuations.",
        f"**Solvency Classification:** Balance sheet is classified under the {zone} solvency zone."
    ]
    if not is_fin and sloan is not None and sloan > 10.0:
        cons.append(f"**Accrual Accounting Risk:** Sloan Accrual Ratio is elevated at {sloan:.1f}% (>10%), signaling non-cash paper profit disconnect.")

    pros_md = "\n".join([f"- 🟢 {p}" for p in pros])
    cons_md = "\n".join([f"- 🔴 {c}" for c in cons])

    return f"### ⚖️ Pros & Cons for {comp}\n\n**🟢 Strengths (Pros):**\n{pros_md}\n\n**🔴 Vulnerabilities (Cons):**\n{cons_md}\n"

def generate_actionable_triggers_framework(row):
    comp = row["Company"]
    is_fin = row["Is_Financial"]
    roe = row["ROE %"]
    pe = row["PE"]
    de = row["D/E"]
    sloan = row["Sloan %"]
    p_score = row["Piotroski"]
    zone = row["Zone"]
    fcf_y = row["FCF Yield %"]

    score_points = 0
    if roe >= 15: score_points += 1
    if pe > 0 and pe <= 25: score_points += 1
    if de <= 0.8 or (is_fin and de <= 7.0): score_points += 1
    if p_score >= 6: score_points += 1
    if fcf_y >= 3.0: score_points += 1
    if zone == "Safe" or is_fin: score_points += 1

    if score_points >= 5:
        signal_tag = "STRONG BUY"
        tag_html = f"<div class='signal-tag-strong-buy'>🟢 FINAL VERDICT: [STRONG BUY]</div>"
    elif score_points >= 3:
        signal_tag = "ACCUMULATE ON DIPS"
        tag_html = f"<div class='signal-tag-accumulate'>🔵 FINAL VERDICT: [ACCUMULATE ON DIPS]</div>"
    elif score_points >= 2:
        signal_tag = "HOLD / WATCHLIST"
        tag_html = f"<div class='signal-tag-hold'>🟡 FINAL VERDICT: [HOLD / WATCHLIST]</div>"
    else:
        signal_tag = "AVOID / EXIT"
        tag_html = f"<div class='signal-tag-avoid'>🔴 FINAL VERDICT: [AVOID / EXIT]</div>"

    buy_triggers = [
        f"Buy if P/E drops below 25.0x (currently {pe:.1f}x) while ROE remains strong above 15.0%.",
        f"Accumulate if Free Cash Flow Yield expands above 4.0% (currently {fcf_y:.1f}%), proving high cash conversion.",
        f"Buy/Add if Piotroski Score remains >= 6/8 (currently {p_score}/8) alongside balance sheet debt paydown."
    ]

    sell_triggers = [
        f"Sell/Exit if Altman Z-Score falls below 1.81 into Distress Zone (currently {zone}).",
        f"Exit if Debt-to-Equity ratio exceeds 1.5x (currently {de:.2f}x) due to unmanaged borrowing.",
        f"Sell/Avoid if Sloan Accrual Ratio spikes above 10.0%" + (f" (currently {sloan:.1f}%)" if sloan is not None else "") + " indicating paper profit disconnect."
    ]

    game_changers = [
        f"**CWIP Commissioning Catalyst:** Major ongoing expansion projects completing and driving revenue growth.",
        f"**Debt Payoff Catalyst:** De-leveraging balance sheet bringing D/E below 0.3x, significantly lowering interest expense.",
        f"**Macro Risk Event:** Severe raw material price spike or key customer default contracting OPM by >250 bps."
    ]

    buy_str = "\n".join([f"- 🟢 **Trigger {idx+1}:** {bt}" for idx, bt in enumerate(buy_triggers)])
    sell_str = "\n".join([f"- 🔴 **Trigger {idx+1}:** {st}" for idx, st in enumerate(sell_triggers)])
    gc_str = "\n".join([f"- 🔄 **Catalyst {idx+1}:** {gc}" for idx, gc in enumerate(game_changers)])

    framework_md = f"### 🚦 Actionable Decision Framework for {comp}\n\n" \
                   f"**Verdict Tag:** `[{signal_tag}]`\n\n" \
                   f"#### 🟢 Exact BUY Triggers (When to Buy):\n{buy_str}\n\n" \
                   f"#### 🔴 Exact SELL Triggers (When to Sell / Avoid):\n{sell_str}\n\n" \
                   f"#### 🔄 Game-Changer Events (What Changes Thesis):\n{gc_str}\n"

    return tag_html, framework_md

def generate_beginner_executive_summary(df_sub):
    if df_sub.empty:
        return "No stocks selected for comparison."

    safest_df = df_sub.sort_values(by=["Piotroski", "ROE %"], ascending=[False, False])
    safest_pick = safest_df.iloc[0]

    growth_df = df_sub.sort_values(by=["3Yr Sales CAGR %", "ROCE %"], ascending=[False, False])
    growth_pick = growth_df.iloc[0]

    risk_df = df_sub.sort_values(by=["D/E"], ascending=[False])
    risk_pick = risk_df.iloc[0]

    summary_md = f"## 🏆 Ultimate Beginner Executive Summary\n\n" \
                 f"### 🛡️ 1. The Safest Long-Term Pick: **{safest_pick['Company']}**\n" \
                 f"- **Why It Wins:** Delivers a top Piotroski Score of **{safest_pick['Piotroski']}/8**, ROE of **{safest_pick['ROE %']:.1f}%**, and strong balance sheet health (**{safest_pick['Zone']} Zone**).\n\n" \
                 f"### 🚀 2. The Highest Growth Pick: **{growth_pick['Company']}**\n" \
                 f"- **Why It Wins:** Leads the cohort with a 3-Year Revenue CAGR of **{growth_pick['3Yr Sales CAGR %']:.1f}%** and ROCE of **{growth_pick['ROCE %']:.1f}%**.\n\n" \
                 f"### 💣 3. The Highest Risk Pick: **{risk_pick['Company']}**\n" \
                 f"- **Why It Requires Caution:** Carries the highest balance sheet leverage (D/E: **{risk_pick['D/E']:.2f}x**), requiring strict monitoring.\n"

    return summary_md

# ─────────────────────────────────────────────────────────────────────────────
# 4. UI & CONTROL FLOW
# ─────────────────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("### 🏛️ Complexity Tier")
    complexity_level = st.radio(
        "Select Analysis Complexity:", 
        ["🌱 Beginner Investor", "📈 Intermediate Investor", "🏛️ Pro / Institutional Analyst"]
    )
    
    st.divider()
    st.markdown("### 🔍 Live Data Pipeline")
    symbol_input = st.text_input(
        "Ingest Symbols (Comma-separated):", 
        value="AAPL, MSFT, NVDA, GOOG"
    )
    
    st.divider()
    st.markdown("### ⚙️ Terminal Settings")
    max_pe_bound = st.slider(
        "Scatter Plot Max P/E Axis Limit", 
        min_value=50, max_value=300, value=150, step=25, 
        help="Clips scatter plot x-axis upper bound to prevent valuation outliers from compressing the chart."
    )
    st.divider()
    st.caption(f"Institutional Terminal v5.5 | {datetime.now().year}")

# Parse input symbols
symbols = [s.strip().upper() for s in symbol_input.split(",") if s.strip()]

if symbols:
    results = []
    raw_histories = {}
    with st.spinner("Streaming real-time pricing & fundamentals..."):
        for sym in symbols:
            fetched = fetch_company_data(sym)
            if fetched:
                res, hist = fetched
                results.append(res)
                raw_histories[sym] = hist

    if results:
        df = pd.DataFrame(results)
        
        tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
            "📊 Master Matrix", "🔍 Metric Deep-Dive", "🏛️ Bull & Bear Thesis", 
            "🛡️ Forensic Risk Auditor", "📈 Interactive Charting", "📄 Export & Alerts"
        ])

        # ─────────────────────────────────────────────────────────────────────────
        # TAB 1: MASTER MATRIX
        # ─────────────────────────────────────────────────────────────────────────
        with tab1:
            st.subheader("Master Quantitative Grid & Technical Summary")
            
            disp_df = df.copy()
            # Clean formats for view
            st.dataframe(
                disp_df[[
                    "Company", "Symbol", "Sector_Type", "Price", "Market Cap", 
                    "PE", "EV/EBITDA", "ROE %", "ROCE %", "D/E", "Interest Coverage", 
                    "FCF Yield %", "Piotroski", "Altman Z", "Zone", "RSI_14", "SMA_200"
                ]].style.format({
                    "Price": "${:,.2f}" if not any(x.endswith(".NS") for x in symbols) else "₹{:,.2f}",
                    "Market Cap": "${:,.0f}M" if not any(x.endswith(".NS") for x in symbols) else "₹{:,.0f}Cr",
                    "PE": lambda x: f"{x:.1f}x" if x > 0 else "N/A (Loss)",
                    "EV/EBITDA": lambda x: f"{x:.1f}x" if x > 0 else "N/A",
                    "ROE %": "{:.1f}%",
                    "ROCE %": "{:.1f}%", 
                    "D/E": "{:.2f}", 
                    "Interest Coverage": lambda x: f"{x:.1f}x" if isinstance(x, (int, float)) and x < 990 else ("Debt Free" if isinstance(x, (int, float)) else "N/A"),
                    "FCF Yield %": "{:.1f}%", 
                    "Altman Z": lambda x: f"{x:.2f}" if isinstance(x, (int, float)) else "N/A",
                    "RSI_14": "{:.1f}",
                    "SMA_200": "{:.2f}"
                }).background_gradient(subset=["Piotroski"], cmap="RdYlGn"),
                use_container_width=True
            )

        # ─────────────────────────────────────────────────────────────────────────
        # TAB 2: METRIC DEEP-DIVE
        # ─────────────────────────────────────────────────────────────────────────
        with tab2:
            st.subheader("🔍 Dynamic Metric Deep-Dive Studio")
            
            # Top-Level KPI Badges
            kpi_col1, kpi_col2, kpi_col3 = st.columns(3)
            valid_roe_df = df.dropna(subset=["ROE %"])
            if not valid_roe_df.empty:
                top_roe = valid_roe_df.loc[valid_roe_df["ROE %"].idxmax()]
                kpi_col1.metric("🏆 Cohort ROE Leader", f"{top_roe['Symbol']}", f"{top_roe['ROE %']:.1f}% ROE")
            
            profitable_df = df[df["PE"] > 0]
            if not profitable_df.empty:
                lowest_pe = profitable_df.loc[profitable_df["PE"].idxmin()]
                kpi_col2.metric("💎 Lowest Valuation (P/E)", f"{lowest_pe['Symbol']}", f"{lowest_pe['PE']:.1f}x P/E")
            
            valid_fcf_df = df.dropna(subset=["FCF Yield %"])
            if not valid_fcf_df.empty:
                top_fcf = valid_fcf_df.loc[valid_fcf_df["FCF Yield %"].idxmax()]
                kpi_col3.metric("💧 Best Cash Yield (FCF %)", f"{top_fcf['Symbol']}", f"{top_fcf['FCF Yield %']:.1f}% FCF")

            st.divider()

            selection = st.multiselect(
                "Select Tickers for Comparative Deep-Dive:", 
                df["Symbol"].unique(), 
                default=df["Symbol"].unique()[:min(4, len(df))]
            )

            if selection:
                # Show Executive Summary comparing cohort
                st.markdown(generate_beginner_executive_summary(df[df["Symbol"].isin(selection)]))
                st.divider()

                subset = df[df["Symbol"].isin(selection)]
                for _, row in subset.iterrows():
                    st.markdown(f"### {row['Company']} ({row['Symbol']}) <span class='sector-badge'>{row['Sector_Type']}</span>", unsafe_allow_html=True)
                    
                    exp1 = st.expander("▸ Valuation & Pricing Power (P/E, EV/EBITDA, OPM %)")
                    with exp1:
                        st.markdown(render_expertise_deep_dive(row, "valuation", complexity_level))
                        
                    exp2 = st.expander("▸ Capital Efficiency & Cash Quality (ROE, ROCE, Sloan Ratio, FCF Yield)")
                    with exp2:
                        st.markdown(render_expertise_deep_dive(row, "capital", complexity_level))
                        
                    exp3 = st.expander("▸ Solvency & Operational Momentum (Altman Z, Piotroski, D/E, Interest Coverage)")
                    with exp3:
                        st.markdown(render_expertise_deep_dive(row, "solvency", complexity_level))
                    st.divider()

        # ─────────────────────────────────────────────────────────────────────────
        # TAB 3: BULL & BEAR THESIS
        # ─────────────────────────────────────────────────────────────────────────
        with tab3:
            st.subheader("🏛️ Bull & Bear Thesis & Buy/Sell Action Triggers")
            
            if selection:
                subset = df[df["Symbol"].isin(selection)]
                cols = st.columns(len(subset))
                for idx, (_, row) in enumerate(subset.iterrows()):
                    with cols[idx]:
                        st.markdown(f"## {row['Company']} ({row['Symbol']})")
                        st.markdown(generate_pros_and_cons(row))
                        st.divider()
                        tag_html, framework_md = generate_actionable_triggers_framework(row)
                        st.markdown(tag_html, unsafe_allow_html=True)
                        st.markdown(framework_md)

        # ─────────────────────────────────────────────────────────────────────────
        # TAB 4: FORENSIC RISK AUDITOR
        # ─────────────────────────────────────────────────────────────────────────
        with tab4:
            st.subheader("🛡️ Automated Forensic Risk Auditor")
            
            for _, row in df.iterrows():
                st.write(f"### {row['Company']} ({row['Symbol']}) <span class='sector-badge'>{row['Sector_Type']}</span>", unsafe_allow_html=True)
                cols = st.columns(4)
                
                # 1. Cash Conversion Risk
                if row['Net Profit'] > 0 and row['FCF'] < 0:
                    cols[0].error("⚠️ Cash Conversion\nNegative FCF despite reported profits.")
                else: 
                    cols[0].success("✅ Cash Flow OK")

                # 2. Solvency Risk
                if not row['Is_Financial']:
                    ic_val = row['Interest Coverage'] if isinstance(row['Interest Coverage'], (int, float)) else 999
                    if row['D/E'] > 1.5 and ic_val < 2.5:
                        cols[1].error("⚠️ Solvency Risk\nHigh Debt / Low Interest Coverage.")
                    else: 
                        cols[1].success("✅ Solvency OK")
                else:
                    if row['D/E'] > 8.0:
                        cols[1].warning("⚠️ High Banking Leverage\nD/E > 8.0x")
                    else:
                        cols[1].success("✅ Banking Leverage OK")

                # 3. Accrual Risk
                if not row['Is_Financial'] and row['Sloan %'] is not None:
                    if row['Sloan %'] > 10.0:
                        cols[2].warning("⚠️ Accrual Risk\nSloan Ratio > 10% (non-cash profits).")
                    else: 
                        cols[2].success("✅ Accruals OK")
                else:
                    cols[2].info("ℹ️ Accruals N/A\nFinancial Entity")

                # 4. Execution Risk
                if not row['Is_Financial']:
                    if row['CWIP to Net Block %'] > 40.0:
                        cols[3].warning("⚠️ Execution Risk\nExtreme CWIP Level (>40%).")
                    else: 
                        cols[3].success("✅ Asset Health OK")
                else:
                    cols[3].info("ℹ️ Asset Health OK\nNo Physical CWIP")
                    
                st.divider()

        # ─────────────────────────────────────────────────────────────────────────
        # TAB 5: INTERACTIVE CHARTING
        # ─────────────────────────────────────────────────────────────────────────
        with tab5:
            st.subheader("📈 Technical Charting & Valuation Scatter")
            
            c1, c2 = st.columns(2)
            
            with c1:
                target_symbol = st.selectbox("Select Ticker for Historical Chart:", options=symbols)
                hist_data = raw_histories.get(target_symbol)
                if hist_data is not None and not hist_data.empty:
                    fig_price = go.Figure()
                    fig_price.add_trace(go.Scatter(x=hist_data.index, y=hist_data['Close'], name='Close Price', line=dict(color='#10b981')))
                    sma200_series = hist_data['Close'].rolling(window=200).mean()
                    fig_price.add_trace(go.Scatter(x=hist_data.index, y=sma200_series, name='200-day SMA', line=dict(color='#3b82f6', dash='dash')))
                    fig_price.update_layout(
                        title=f"{target_symbol} Price Movement & 200 SMA",
                        xaxis_title="Date",
                        yaxis_title="Price",
                        template="plotly_dark"
                    )
                    st.plotly_chart(fig_price, use_container_width=True)
                else:
                    st.info("No historical data available for this ticker.")
            
            with c2:
                scatter_df = df.copy()
                scatter_df["Plot_PE"] = scatter_df["PE"].apply(lambda x: min(x, max_pe_bound) if x > 0 else 0)
                scatter_df["PE_Label"] = scatter_df["PE"].apply(lambda x: f"{x:.1f}x" if x > 0 else "Negative P/E")

                fig1 = px.scatter(
                    scatter_df, 
                    x="Plot_PE", 
                    y="OPM %", 
                    size="Market Cap Raw", 
                    color="Zone",
                    hover_name="Company",
                    hover_data={
                        "Plot_PE": False,
                        "PE_Label": True,
                        "ROE %": ":.1f%",
                        "Piotroski": True,
                        "Sector_Type": True
                    },
                    title=f"Valuation (P/E) vs. Profitability (OPM/Margin %) [Max Axis: {max_pe_bound}x]",
                    color_discrete_map={
                        "Safe": "#10b981", 
                        "Grey": "#f59e0b", 
                        "Distress": "#ef4444", 
                        "N/A (Financial)": "#3b82f6"
                    }
                )
                
                fig1.update_layout(
                    template="plotly_dark",
                    xaxis_title="P/E Ratio (Capped Bounds)",
                    yaxis_title="Margin / Profitability %",
                    xaxis=dict(range=[-5, max_pe_bound + 10])
                )
                st.plotly_chart(fig1, use_container_width=True)

        # ─────────────────────────────────────────────────────────────────────────
        # TAB 6: EXPORT & ALERTS
        # ─────────────────────────────────────────────────────────────────────────
        with tab6:
            st.subheader("📄 Institutional Research Export Engine")
            
            export_sub = df[df["Symbol"].isin(selection)] if selection else df

            report = f"# INSTITUTIONAL EQUITY RESEARCH REPORT\n"
            report += f"Complexity Level: {complexity_level}\n"
            report += f"Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            report += f"Total Companies Analyzed: {len(export_sub)}\n\n"
            report += "=" * 80 + "\n\n"
            
            report += "## 1. COHORT SUMMARY GRID\n\n"
            report += dataframe_to_markdown_table(export_sub[["Company", "Symbol", "Sector_Type", "Price", "PE", "EV/EBITDA", "ROE %", "ROCE %", "D/E", "Piotroski", "Zone"]])
            report += "\n\n" + "=" * 80 + "\n\n"
            
            report += generate_beginner_executive_summary(export_sub)
            report += "\n\n" + "=" * 80 + "\n\n"
            
            report += f"## 2. METRIC DEEP DIVES ({complexity_level})\n\n"
            for _, row in export_sub.iterrows():
                report += f"### {row['Company']} ({row['Symbol']})\n\n"
                report += "#### Valuation & Pricing Power\n"
                report += render_expertise_deep_dive(row, "valuation", complexity_level) + "\n\n"
                report += "#### Capital Efficiency & Cash Quality\n"
                report += render_expertise_deep_dive(row, "capital", complexity_level) + "\n\n"
                report += "#### Solvency & Balance Sheet Strength\n"
                report += render_expertise_deep_dive(row, "solvency", complexity_level) + "\n\n"
                report += "-" * 60 + "\n\n"
            
            report += "=" * 80 + "\n\n"
            report += "## 3. PROS & CONS\n\n"
            for _, row in export_sub.iterrows():
                report += generate_pros_and_cons(row)
                report += "\n\n" + "-" * 60 + "\n\n"

            report += "=" * 80 + "\n\n"
            report += "## 4. ACTIONABLE TRADING & INVESTMENT FRAMEWORK\n\n"
            for _, row in export_sub.iterrows():
                _, framework_md = generate_actionable_triggers_framework(row)
                report += framework_md
                report += "\n\n" + "=" * 60 + "\n\n"

            st.download_button(
                "📥 Download Institutional Research Report (.md)", 
                data=report, 
                file_name=f"Institutional_Terminal_Report_{datetime.now().strftime('%Y%m%d')}.md",
                mime="text/markdown"
            )
else:
    st.info("👋 Enter comma-separated stock symbols in the sidebar to run quantitative analysis.")
