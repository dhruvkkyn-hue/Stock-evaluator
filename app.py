import streamlit as st
import pandas as pd
import openpyxl
import io
import zipfile
import re
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
        .thesis-card {
            background-color: #161b22;
            border: 1px solid #30363d;
            border-radius: 8px;
            padding: 20px;
            margin-bottom: 15px;
        }
        .trigger-box-buy {
            background-color: rgba(16, 185, 129, 0.08);
            border-left: 4px solid #10b981;
            padding: 12px 16px;
            border-radius: 4px;
            margin-bottom: 10px;
        }
        .trigger-box-sell {
            background-color: rgba(239, 68, 68, 0.08);
            border-left: 4px solid #ef4444;
            padding: 12px 16px;
            border-radius: 4px;
            margin-bottom: 10px;
        }
    </style>
    """, unsafe_allow_html=True)

inject_custom_css()

# ─────────────────────────────────────────────────────────────────────────────
# 2. QUANT ENGINE: SAFE MATH & FINANCIAL SECTOR PARSING
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

def find_row_series(ws, keywords):
    kw_lower = [k.lower() for k in keywords]
    for row in ws.iter_rows(min_row=1, max_row=ws.max_row, min_col=1, max_col=3):
        label = f"{str(row[0].value or '')} {str(row[1].value or '')} {str(row[2].value or '')}".lower()
        if any(k in label for k in kw_lower):
            row_idx = row[0].row
            series = []
            for c in range(2, ws.max_column + 1):
                val = ws.cell(row=row_idx, column=c).value
                if val is not None:
                    series.append(safe_float(val, None))
            if series:
                return series
    return None

def detect_financial_entity(ws, filename, extracted_name, raw_data):
    fin_keywords = [
        "bank", "nbfc", "advances", "deposits", "interest earned", "interest expended", 
        "net interest income", "nii", "provisions & contingencies", "gross npa", 
        "net npa", "capital adequacy", "housing finance", "microfinance"
    ]
    
    ws_text_sample = ""
    for r in range(1, min(40, ws.max_row + 1)):
        for c in range(1, min(4, ws.max_column + 1)):
            val = ws.cell(row=r, column=c).value
            if val:
                ws_text_sample += f" {str(val).lower()}"
                
    if any(kw in ws_text_sample for kw in fin_keywords):
        return True

    combined_name = f"{extracted_name} {filename}".lower()
    name_fin_terms = ["bank", "finance", "fin", "nbfc", "capital", "housing fin", "lending"]
    if any(term in combined_name for term in name_fin_terms):
        return True

    return False

def process_workbook(file_bytes, filename):
    try:
        res = {}
        wb = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True)
        ds_name = next((s for s in wb.sheetnames if "data sheet" in s.lower()), wb.sheetnames[0])
        ws = wb[ds_name]

        extracted_name = ws.cell(row=1, column=2).value
        company_name = str(extracted_name).strip() if extracted_name else str(filename).replace(".xlsx", "").replace(".xls", "")
        res["Company"] = company_name

        data_map = {
            "mcap": ["Market Capitalization", "Market Cap"],
            "sales": ["Sales", "Revenue", "Interest Earned", "Total Revenue", "Gross Revenue"],
            "op": ["Operating Profit", "EBITDA", "EBIT", "Operating Profit / (Loss)"],
            "pat": ["Net Profit", "Profit after tax", "PAT"],
            "pbt": ["Profit before tax", "PBT"],
            "interest": ["Interest", "Finance Costs"],
            "depr": ["Depreciation", "Depreciation & Amortization"],
            "debt": ["Borrowings", "Total Debt", "Debt"],
            "equity": ["Equity Share Capital", "Share Capital"],
            "reserves": ["Reserves", "Other Equity"],
            "cfo": ["Cash from Operating", "CFO", "Cash flow from operating activities"],
            "cfi": ["Cash from Investing", "CFI", "Cash flow from investing activities"],
            "capex": ["Capital Expenditure", "Fixed Assets Purchased", "CapEx", "Purchase of fixed assets"],
            "cwip": ["Capital Work in Progress", "CWIP"],
            "net_block": ["Net Block", "Fixed Assets", "Property Plant and Equipment"],
            "liab": ["Other Liabilities", "Total Liabilities", "Current Liabilities"],
            "assets": ["Total Assets"],
            "receivables": ["Receivables", "Trade Receivables"],
            "inventory": ["Inventory", "Inventories"]
        }

        raw = {k: find_row_series(ws, v) for k, v in data_map.items()}
        curr = {k: (raw[k][-1] if raw[k] and raw[k][-1] is not None else 0.0) for k in raw}
        
        is_fin = detect_financial_entity(ws, filename, company_name, raw)
        res["Is_Financial"] = is_fin
        res["Sector_Type"] = "Financial / Banking" if is_fin else "Industrial / Commercial"

        local_equity = curr['equity'] + curr['reserves']
        local_debt = curr['debt']
        local_assets = curr['assets'] if curr['assets'] > 0 else (local_equity + local_debt + curr['liab'])
        local_pat = curr['pat']
        local_pbt = curr['pbt'] if curr['pbt'] != 0 else local_pat
        local_cfo = curr['cfo']
        local_sales = curr['sales']
        local_mcap = curr['mcap']
        
        raw_capex = curr['capex']
        if raw_capex > 0:
            capex_val = raw_capex
        elif curr['cfi'] != 0:
            capex_val = abs(curr['cfi'])
        else:
            capex_val = 0.0

        fcf_val = local_cfo - capex_val
        res["CapEx"] = capex_val
        res["FCF"] = fcf_val
        res["FCF Yield %"] = safe_div(fcf_val, local_mcap) * 100

        if is_fin:
            local_ebit = local_pbt if local_pbt != 0 else local_pat
            res["Interest Coverage"] = None
        else:
            local_ebit = (curr['pbt'] + curr['interest']) if (curr['pbt'] != 0 or curr['interest'] != 0) else curr['op']
            res["Interest Coverage"] = safe_div(local_ebit, curr['interest'], default=999.0) if curr['interest'] > 0 else 999.0

        res["Market Cap"] = local_mcap
        res["Sales"] = local_sales
        res["Net Profit"] = local_pat
        res["PE"] = safe_div(local_mcap, local_pat) if local_pat > 0 else -1.0
        res["D/E"] = safe_div(local_debt, local_equity)
        
        if is_fin:
            res["OPM %"] = safe_div(local_pat, local_sales) * 100
            res["ROE %"] = safe_div(local_pat, local_equity) * 100
            res["ROCE %"] = safe_div(local_ebit, local_equity + local_debt) * 100
        else:
            res["OPM %"] = safe_div(curr['op'], local_sales) * 100
            res["ROE %"] = safe_div(local_pat, local_equity) * 100
            res["ROCE %"] = safe_div(local_ebit, local_equity + local_debt) * 100

        res["CWIP to Net Block %"] = safe_div(curr['cwip'], curr['net_block']) * 100 if curr['net_block'] > 0 else 0.0
        res["3Yr Sales CAGR %"] = calculate_cagr(raw['sales'], 3)
        res["3Yr PAT CAGR %"] = calculate_cagr(raw['pat'], 3)
        
        if is_fin:
            res["Sloan %"] = None
        else:
            res["Sloan %"] = safe_div(local_pat - local_cfo, local_assets) * 100

        if is_fin:
            res["Altman Z"] = None
            res["Zone"] = "N/A (Financial)"
        else:
            wc_proxy = (curr['receivables'] + curr['inventory'] + (local_assets * 0.05)) - curr['liab']
            z_val = (
                (1.2 * safe_div(wc_proxy, local_assets)) + 
                (1.4 * safe_div(curr['reserves'], local_assets)) + 
                (3.3 * safe_div(curr['op'], local_assets)) + 
                (0.6 * safe_div(local_mcap, local_debt + curr['liab'])) + 
                (0.99 * safe_div(local_sales, local_assets))
            )
            res["Altman Z"] = z_val
            res["Zone"] = "Safe" if z_val > 2.99 else "Grey" if z_val >= 1.81 else "Distress"

        p_score = 0
        if local_pat > 0: p_score += 1
        if local_cfo > 0: p_score += 1
        if local_cfo > local_pat: p_score += 1
        if res["3Yr PAT CAGR %"] > 0: p_score += 1
        
        if raw['debt'] and len(raw['debt']) > 1 and raw['equity'] and len(raw['equity']) > 1 and raw['reserves'] and len(raw['reserves']) > 1:
            prev_eq = (raw['equity'][-2] or 0.0) + (raw['reserves'][-2] or 0.0)
            prev_de = safe_div(raw['debt'][-2], prev_eq)
            if res["D/E"] <= prev_de: p_score += 1
            
        if res["ROCE %"] > 12: p_score += 1
        if res["3Yr Sales CAGR %"] > 0: p_score += 1
        if local_assets > 0: p_score += 1
        res["Piotroski"] = p_score

        return res, file_bytes

    except Exception as e:
        err_msg = f"Error in {filename}: {str(e)}\n{traceback.format_exc()}"
        st.error(err_msg)
        return None, None

def dataframe_to_markdown_table(df_sub):
    headers = list(df_sub.columns)
    header_row = "| " + " | ".join(headers) + " |"
    sep_row = "| " + " | ".join(["---"] * len(headers)) + " |"
    data_rows = []
    for _, row in df_sub.iterrows():
        r_str = [str(val) for val in row.values]
        data_rows.append("| " + " | ".join(r_str) + " |")
    return "\n".join([header_row, sep_row] + data_rows)

# ─────────────────────────────────────────────────────────────────────────────
# 3. QUALITATIVE GENERATION ENGINE: EXPLICIT METRIC DEEP DIVES & THESES
# ─────────────────────────────────────────────────────────────────────────────

def generate_explicit_metric_breakdown(row):
    """Generates rigorous metric-by-metric institutional breakdown paragraphs for a stock."""
    is_fin = row["Is_Financial"]
    comp = row["Company"]
    
    # 1. Valuation & Pricing
    pe = row["PE"]
    if pe > 0:
        if pe < 15:
            pe_eval = f"at a deep value / depressed multiple of {pe:.1f}x P/E, offering potential valuation re-rating if operational momentum sustains."
        elif pe <= 35:
            pe_eval = f"at a fair market valuation multiple of {pe:.1f}x P/E, pricing in baseline compound growth without excessive speculative premium."
        else:
            pe_eval = f"at a premium growth multiple of {pe:.1f}x P/E, requiring execution excellence and continuous high earnings growth to prevent multiple contraction."
    else:
        pe_eval = "with a negative P/E multiple due to reported trailing net losses, making classical earnings-based valuation non-applicable and requiring asset-based or cash flow recovery analysis."
    
    val_text = f"**1. Valuation Multiple (P/E Ratio):** {comp} is currently priced {pe_eval} From an institutional standpoint, trailing earnings valuation reflects market expectations regarding growth durability. Industry benchmarks vary widely between asset-light high-margin businesses (where 30-40x P/E can be justified) and cyclical commodity producers (where single-digit P/E is standard)."

    # 2. Capital Efficiency & Returns (ROE & ROCE)
    roe = row["ROE %"]
    roce = row["ROCE %"]
    if roe > 18:
        roe_eval = f"demonstrates outstanding equity compounding power with an ROE of {roe:.1f}%, exceeding cost of equity thresholds by a wide margin."
    elif roe >= 10:
        roe_eval = f"delivers moderate equity capital returns with an ROE of {roe:.1f}%, indicating steady reinvestment yield."
    else:
        roe_eval = f"exhibits sub-par equity capital return of {roe:.1f}%, signalling potential capital misallocation or cyclically suppressed profits."

    roce_eval = f"ROCE stands at {roce:.1f}%." + (" For industrial firms, a ROCE above 15% signifies strong economic moats and pricing power over capital providers." if not is_fin else " For financial entities, return on total funds employed reflects spread management efficiency.")
    
    cap_text = f"**2. Capital Efficiency & Compound Returns (ROE & ROCE):** {comp} {roe_eval} Simultaneously, {roce_eval} Institutional investors closely monitor the spread between ROCE and the weighted average cost of capital (WACC); a wide positive spread confirms value creation."

    # 3. Profitability & Operating Margins
    opm = row["OPM %"]
    if is_fin:
        margin_label = "Net Margin (PAT / Income)"
        margin_eval = f"stands at {opm:.1f}%. In banking and credit underwriting, net income margin captures asset quality, credit cost management, and net interest spread efficiency."
    else:
        margin_label = "Operating Profit Margin (OPM)"
        if opm > 20:
            margin_eval = f"expands to a robust {opm:.1f}%, reflecting premium product positioning, cost leadership, or high value-addition capabilities."
        elif opm >= 10:
            margin_eval = f"sits at {opm:.1f}%, aligned with competitive commercial operating norms but susceptible to raw material cost inflation."
        else:
            margin_eval = f"is constrained at {opm:.1f}%, highlighting thin operating buffers and heightened sensitivity to input price fluctuations."

    prof_text = f"**3. Operational Profitability ({margin_label}):** The current margin profile {margin_eval} Sustaining or expanding margins during macro inflationary cycles is a primary qualitative indicator of structural pricing power."

    # 4. Solvency, Leverage & Coverage
    de = row["D/E"]
    ic = row["Interest Coverage"]
    alt_z = row["Altman Z"]
    zone = row["Zone"]
    
    if is_fin:
        solv_eval = f"Financial leverage (D/E) is measured at {de:.2f}x. High leverage is standard for deposit-taking entities where financial liabilities represent funding capital. Solvency is classified under banking regulatory frameworks rather than manufacturing Z-scores."
    else:
        ic_str = f"{ic:.1f}x" if isinstance(ic, (int, float)) and ic < 990 else "Debt Free"
        z_str = f"{alt_z:.2f}" if alt_z is not None else "N/A"
        solv_eval = f"Debt-to-Equity leverage stands at {de:.2f}x with an Interest Coverage Ratio of {ic_str}. The combined balance sheet solvency is evaluated via an Altman Z-Score of {z_str}, placing the enterprise in the **{zone}** health classification zone. A Z-Score above 2.99 confirms negligible short-to-medium term bankruptcy vulnerability."

    solv_text = f"**4. Solvency, Debt Structure & Balance Sheet Coverage:** {solv_eval}"

    # 5. Earnings Quality & Sloan Accrual Ratio
    sloan = row["Sloan %"]
    if is_fin or sloan is None:
        sloan_text = f"**5. Earnings Quality & Sloan Accrual Ratio:** Sloan Accrual Ratio is N/A for financial institutions due to specialized loan-loss provision accounting and credit cash flow timing."
    else:
        if sloan > 10.0:
            sloan_eval = f"stands elevated at {sloan:.1f}% (>10.0% threshold), raising red flags regarding aggressive revenue recognition, uncollected receivables, or non-cash inventory build-up."
        elif sloan < -10.0:
            sloan_eval = f"is deeply negative at {sloan:.1f}%, indicating highly conservative accounting with operating cash flow substantially exceeding reported net profit."
        else:
            sloan_eval = f"sits in the pristine neutral zone at {sloan:.1f}%, confirming that reported earnings are backed by actual cash receipts."
        sloan_text = f"**5. Earnings Quality & Accrual Accounting (Sloan Ratio):** The Sloan Accrual Ratio for {comp} {sloan_eval}"

    # 6. Cash Conversion & FCF Yield
    fcf = row["FCF"]
    fcf_y = row["FCF Yield %"]
    fcf_text = f"**6. Cash Flow Generation & Free Cash Flow Yield:** The enterprise generated absolute Free Cash Flow (FCF = CFO - CapEx) of ₹{fcf:,.0f} Cr, translating into an FCF Yield of {fcf_y:.1f}% relative to market capitalization. FCF yield represents the unencumbered cash available for dividend distribution, debt paydown, or strategic bolt-on acquisitions."

    # 7. Piotroski F-Score
    p_score = row["Piotroski"]
    if p_score >= 6:
        p_eval = f"achieves an excellent score of {p_score}/8, signaling strong fundamental momentum, improving asset turn, and operational efficiency."
    elif p_score >= 4:
        p_eval = f"scores a moderate {p_score}/8, reflecting acceptable baseline health with minor operational areas requiring monitoring."
    else:
        p_eval = f"scores a weak {p_score}/8, pointing to structural operational friction, deteriorating leverage, or margin pressures."
        
    piot_text = f"**7. Piotroski Fundamental Quality Score:** {comp} {p_eval}"

    return "\n\n".join([val_text, cap_text, prof_text, solv_text, sloan_text, fcf_text, piot_text])

def generate_comprehensive_investment_thesis(row):
    """Generates Bull Thesis, Bear Thesis, Event Triggers, and Pros/Cons."""
    comp = row["Company"]
    is_fin = row["Is_Financial"]
    roe = row["ROE %"]
    roce = row["ROCE %"]
    pe = row["PE"]
    de = row["D/E"]
    opm = row["OPM %"]
    sloan = row["Sloan %"]
    fcf_y = row["FCF Yield %"]
    p_score = row["Piotroski"]
    zone = row["Zone"]

    # Bull Thesis
    bull = f"### 🐂 The Bull Thesis (Growth Drivers & Moats)\n"
    bull += f"1. **Capital Allocation Efficiency:** {comp} demonstrates strong compounding efficiency with an ROE of **{roe:.1f}%** and ROCE of **{roce:.1f}%**, generating attractive returns on incremental reinvested capital.\n"
    bull += f"2. **Operational Cash Generation:** The company delivers an FCF Yield of **{fcf_y:.1f}%**, proving that earnings are translating into actual liquid cash reserves rather than remaining trapped on the balance sheet.\n"
    bull += f"3. **Fundamental Health Momentum:** Backed by a Piotroski F-Score of **{p_score}/8**, operational trends across leverage, margin expansion, and asset turnover remain healthy."

    # Bear Thesis
    bear = f"### 🐻 The Bear Thesis (Key Risks & Vulnerabilities)\n"
    bear += f"1. **Valuation & Multiple Contraction Risk:** Trading at a P/E of **{pe:.1f}x**, any growth deceleration or margin compression could trigger a sharp derating in valuation multiples.\n"
    if not is_fin and sloan is not None and sloan > 10.0:
        bear += f"2. **Accrual & Earnings Quality Red Flag:** Sloan Accrual Ratio is elevated at **{sloan:.1f}%**, indicating a potential disconnect between accounting PAT and cash flows.\n"
    else:
        bear += f"2. **Leverage & Refinancing Exposure:** Debt-to-Equity stands at **{de:.2f}x**; sustained macro interest rate volatility could elevate interest burdens.\n"
    bear += f"3. **Solvency & Macro Headwinds:** Solvency is categorized as **{zone}**, making macro demand shocks or raw material price inflation critical monitoring factors."

    # Event-Driven Triggers
    buy_trig = f"**🟢 Buy / Accumulate Triggers:**\n"
    buy_trig += f"- Debt-to-Equity ratio reducing below 0.3x or Interest Coverage expanding > 5.0x.\n"
    buy_trig += f"- Operating Margin (OPM) expanding by > 150 bps YoY due to operating leverage.\n"
    buy_trig += f"- Sloan Accrual Ratio dropping below 5.0% alongside positive Free Cash Flow growth.\n"
    buy_trig += f"- Major capital expenditure (CWIP) commissioning leading to revenue acceleration."

    sell_trig = f"**🔴 Avoid / Liquidation Triggers:**\n"
    sell_trig += f"- Piotroski F-Score deteriorating below 4/8 or Altman Z-Score dropping into Distress (<1.81).\n"
    sell_trig += f"- Uncollected receivables spike exceeding sales growth or CFO/PAT disconnect widening for 2 consecutive quarters.\n"
    sell_trig += f"- Margin contraction > 200 bps YoY driven by loss of pricing power."

    triggers = f"### ⚡ Event-Driven Catalyst & Trigger Framework\n{buy_trig}\n\n{sell_trig}"

    # Pros & Cons List
    pros = [
        f"Delivers ROE of {roe:.1f}% and ROCE of {roce:.1f}%.",
        f"Generates Free Cash Flow Yield of {fcf_y:.1f}%.",
        f"Piotroski Quality Score of {p_score}/8 confirms healthy fundamental momentum.",
        f"Revenue 3-Yr CAGR of {row['3Yr Sales CAGR %']:.1f}% demonstrating growth resilience."
    ]
    
    cons = [
        f"P/E valuation multiple stands at {pe:.1f}x.",
        f"Debt-to-Equity leverage measured at {de:.2f}x.",
        f"Solvency zone classified as {zone}.",
    ]
    if not is_fin and sloan is not None and sloan > 10.0:
        cons.append(f"Elevated Sloan Accrual Ratio of {sloan:.1f}% indicates accounting accrual risk.")

    pros_str = "\n".join([f"- ✅ {p}" for p in pros])
    cons_str = "\n".join([f"- ⚠️ {c}" for c in cons])

    pros_cons = f"### ⚖️ Granular Pros & Cons Matrix\n**Strengths & Moats:**\n{pros_str}\n\n**Vulnerabilities & Risks:**\n{cons_str}"

    return "\n\n".join([bull, bear, triggers, pros_cons])

# ─────────────────────────────────────────────────────────────────────────────
# 4. UI & CONTROL FLOW
# ─────────────────────────────────────────────────────────────────────────────

with st.sidebar:
    st.header("📂 Batch Ingestion")
    uploads = st.file_uploader("Upload Screener Excels", type=["xlsx", "xls"], accept_multiple_files=True)
    st.divider()
    st.markdown("### ⚙️ Terminal Settings")
    max_pe_bound = st.slider("Scatter Plot Max P/E Axis Limit", min_value=50, max_value=300, value=150, step=25, 
                             help="Clips scatter plot x-axis upper bound to prevent valuation outliers from compressing the chart.")
    st.divider()
    st.caption(f"Institutional Terminal v3.5 | {datetime.now().year}")

st.markdown("<h1 class='hero-title'>🏛️ Institutional Research Terminal</h1>", unsafe_allow_html=True)
st.markdown("<p class='hero-subtitle'>Dynamic Quantitative Auditor & Multi-Asset Valuation Architecture</p>", unsafe_allow_html=True)

if uploads:
    results = []
    raw_files = []
    for up in uploads:
        data, b_content = process_workbook(up.getvalue(), up.name)
        if data:
            results.append(data)
            raw_files.append((up.name, b_content))

    if results:
        df = pd.DataFrame(results)
        
        tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
            "📊 Matrix", "🕵️ Deep-Dive", "🏛️ Thesis & Allocation", 
            "📈 Visuals", "🚨 Risk Audit", "📄 Export Report"
        ])

        # ─────────────────────────────────────────────────────────────────────────
        # TAB 1: MASTER QUANTITATIVE MATRIX
        # ─────────────────────────────────────────────────────────────────────────
        with tab1:
            st.subheader("Master Quantitative Grid")
            
            disp_df = df.copy()
            st.dataframe(
                disp_df[[
                    "Company", "Sector_Type", "Market Cap", "Sales", "Net Profit", 
                    "PE", "ROE %", "ROCE %", "D/E", "Interest Coverage", 
                    "FCF Yield %", "Piotroski", "Altman Z", "Zone"
                ]].style.format({
                    "Market Cap": "₹{:,.0f}Cr", 
                    "Sales": "₹{:,.0f}Cr", 
                    "Net Profit": "₹{:,.0f}Cr",
                    "PE": lambda x: f"{x:.1f}x" if x > 0 else "N/A (Loss)",
                    "ROE %": "{:.1f}%",
                    "ROCE %": "{:.1f}%", 
                    "D/E": "{:.2f}", 
                    "Interest Coverage": lambda x: f"{x:.1f}x" if isinstance(x, (int, float)) and x < 990 else ("Debt Free" if isinstance(x, (int, float)) else "N/A"),
                    "FCF Yield %": "{:.1f}%", 
                    "Altman Z": lambda x: f"{x:.2f}" if isinstance(x, (int, float)) else "N/A"
                }).background_gradient(subset=["Piotroski"], cmap="RdYlGn"),
                use_container_width=True
            )

        # ─────────────────────────────────────────────────────────────────────────
        # TAB 2: EXPLICIT METRIC-BY-METRIC DEEP DIVE
        # ─────────────────────────────────────────────────────────────────────────
        with tab2:
            st.subheader("Explicit Metric-by-Metric Deep Dive")
            
            kpi_col1, kpi_col2, kpi_col3 = st.columns(3)
            
            valid_roe_df = df.dropna(subset=["ROE %"])
            if not valid_roe_df.empty:
                top_roe = valid_roe_df.loc[valid_roe_df["ROE %"].idxmax()]
                kpi_col1.metric("🏆 Cohort ROE Leader", f"{top_roe['Company']}", f"{top_roe['ROE %']:.1f}% ROE")
            
            profitable_df = df[df["PE"] > 0]
            if not profitable_df.empty:
                lowest_pe = profitable_df.loc[profitable_df["PE"].idxmin()]
                kpi_col2.metric("💎 Lowest Valuation (P/E)", f"{lowest_pe['Company']}", f"{lowest_pe['PE']:.1f}x P/E")
            else:
                kpi_col2.metric("💎 Lowest Valuation (P/E)", "N/A", "No Profitable Stocks")
                
            industrial_df = df[df["Altman Z"].notnull()]
            if not industrial_df.empty:
                safest_z = industrial_df.loc[industrial_df["Altman Z"].idxmax()]
                kpi_col3.metric("🛡️ Safest Solvency (Altman Z)", f"{safest_z['Company']}", f"Z-Score {safest_z['Altman Z']:.2f}")
            else:
                kpi_col3.metric("🛡️ Safest Solvency (Altman Z)", "Banking Cohort", "N/A (Financials)")

            st.divider()

            selection = st.multiselect(
                "Select Companies for Deep-Dive Analysis:", 
                df["Company"].unique(), 
                default=df["Company"].unique()[:min(4, len(df))]
            )
            
            if selection:
                subset = df[df["Company"].isin(selection)]
                for _, row in subset.iterrows():
                    with st.expander(f"Comprehensive Metric Analysis: {row['Company']} ({row['Sector_Type']})", expanded=True):
                        st.markdown(generate_explicit_metric_breakdown(row))

        # ─────────────────────────────────────────────────────────────────────────
        # TAB 3: COMPREHENSIVE INVESTMENT THESIS & ALLOCATION
        # ─────────────────────────────────────────────────────────────────────────
        with tab3:
            st.subheader("🏛️ Comprehensive Investment Thesis & Allocation Strategy")
            
            if selection:
                subset = df[df["Company"].isin(selection)]
                for _, row in subset.iterrows():
                    with st.expander(f"Investment Thesis & Trigger Framework: {row['Company']}", expanded=True):
                        st.markdown(generate_comprehensive_investment_thesis(row))

        # ─────────────────────────────────────────────────────────────────────────
        # TAB 4: VISUAL ANALYTICS (PLOTLY)
        # ─────────────────────────────────────────────────────────────────────────
        with tab4:
            st.subheader("Visual Analytics & Cohort Benchmarking")
            
            c1, c2 = st.columns(2)
            
            with c1:
                scatter_df = df.copy()
                scatter_df["Plot_PE"] = scatter_df["PE"].apply(lambda x: min(x, max_pe_bound) if x > 0 else 0)
                scatter_df["PE_Label"] = scatter_df["PE"].apply(lambda x: f"{x:.1f}x" if x > 0 else "Negative P/E")

                fig1 = px.scatter(
                    scatter_df, 
                    x="Plot_PE", 
                    y="OPM %", 
                    size="Market Cap", 
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
                st.caption("ℹ️ Note: P/E axis is bounded between -5x and user-defined limit to prevent extreme valuation outliers from compressing the visual.")

            with c2:
                bar_companies = selection if selection else df['Company'].tolist()
                bar_df = df[df['Company'].isin(bar_companies)]
                
                fig2 = go.Figure()
                fig2.add_trace(go.Bar(
                    x=bar_df['Company'], 
                    y=bar_df['Piotroski'], 
                    name='Piotroski F-Score (0-8)',
                    marker_color='#10b981'
                ))
                fig2.add_trace(go.Bar(
                    x=bar_df['Company'], 
                    y=[z if z is not None else 0 for z in bar_df['Altman Z']], 
                    name='Altman Z-Score',
                    marker_color='#3b82f6'
                ))
                fig2.update_layout(
                    title="Fundamental Quality (Piotroski) vs. Solvency (Altman Z)",
                    barmode='group',
                    template="plotly_dark",
                    yaxis_title="Score / Z-Value"
                )
                st.plotly_chart(fig2, use_container_width=True)

        # ─────────────────────────────────────────────────────────────────────────
        # TAB 5: AUTOMATED RISK AUDITOR
        # ─────────────────────────────────────────────────────────────────────────
        with tab5:
            st.subheader("🚨 Automated Forensic & Risk Auditor")
            
            for _, row in df.iterrows():
                st.write(f"### {row['Company']} <span class='sector-badge'>{row['Sector_Type']}</span>", unsafe_allow_html=True)
                cols = st.columns(4)
                
                # 1. Cash Conversion Risk
                if row['Net Profit'] > 0 and row['FCF'] < 0:
                    cols[0].error("⚠️ Cash Conversion\nNegative FCF despite PAT.")
                else: 
                    cols[0].success("✅ Cash Flow OK")

                # 2. Solvency Risk
                if not row['Is_Financial']:
                    ic_val = row['Interest Coverage'] if isinstance(row['Interest Coverage'], (int, float)) else 999
                    if row['D/E'] > 1.5 and ic_val < 2.5:
                        cols[1].error("⚠️ Solvency Risk\nHigh Debt / Low Coverage.")
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
                        cols[2].warning("⚠️ Accrual Risk\nSloan Ratio > 10%.")
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
        # TAB 6: OFFLINE REPORT EXPORT
        # ─────────────────────────────────────────────────────────────────────────
        with tab6:
            st.subheader("📄 Institutional Research Export Engine")
            
            export_sub = df[df["Company"].isin(selection)] if selection else df

            report = f"# INSTITUTIONAL EQUITY RESEARCH REPORT\n"
            report += f"Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            report += f"Total Companies Analyzed: {len(export_sub)}\n\n"
            report += "=" * 80 + "\n\n"
            
            report += "## 1. COHORT SUMMARY GRID\n\n"
            report += dataframe_to_markdown_table(export_sub[["Company", "Sector_Type", "Market Cap", "PE", "ROE %", "ROCE %", "D/E", "Piotroski", "Zone"]])
            report += "\n\n" + "=" * 80 + "\n\n"
            
            report += "## 2. EXPLICIT METRIC-BY-METRIC DEEP DIVES\n\n"
            for _, row in export_sub.iterrows():
                report += f"### {row['Company']} ({row['Sector_Type']})\n\n"
                report += generate_explicit_metric_breakdown(row)
                report += "\n\n" + "-" * 60 + "\n\n"
            
            report += "=" * 80 + "\n\n"
            report += "## 3. COMPREHENSIVE INVESTMENT THESES & TRIGGER FRAMEWORKS\n\n"
            for _, row in export_sub.iterrows():
                report += f"## {row['Company']} - INVESTMENT THESIS & STRATEGY\n\n"
                report += generate_comprehensive_investment_thesis(row)
                report += "\n\n" + "=" * 60 + "\n\n"

            col_exp1, col_exp2 = st.columns(2)
            
            col_exp1.download_button(
                "📥 Download Institutional Research Report (.md)", 
                data=report, 
                file_name=f"Institutional_Terminal_Report_{datetime.now().strftime('%Y%m%d')}.md",
                mime="text/markdown"
            )
            
            zip_io = io.BytesIO()
            with zipfile.ZipFile(zip_io, 'w') as zf:
                for fname, content in raw_files: 
                    zf.writestr(f"Processed_{fname}", content)
            
            col_exp2.download_button(
                "📥 Download Ingestion Package (.zip)", 
                data=zip_io.getvalue(), 
                file_name="Ingested_Workbooks_Package.zip",
                mime="application/zip"
            )

else:
    st.info("👋 Upload Screener.in Excel exports in the sidebar to run quantitative analysis.")
