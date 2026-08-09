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
# 1. UI/UX: INSTITUTIONAL CSS & ARCHITECTURE
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
        
        /* Custom Card Styling */
        .metric-card {
            background-color: var(--card-bg);
            border: 1px solid var(--border-color);
            padding: 20px;
            border-radius: 12px;
            margin-bottom: 15px;
            box-shadow: 0 4px 6px rgba(0, 0, 0, 0.2);
        }

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
            gap: 15px; 
            border-bottom: 1px solid var(--border-color);
        }
        .stTabs [data-baseweb="tab"] {
            background-color: var(--card-bg);
            border: 1px solid var(--border-color);
            border-radius: 6px 6px 0px 0px;
            padding: 12px 28px;
            color: var(--text-main);
            font-weight: 600;
            font-size: 1rem;
        }
        .stTabs [aria-selected="true"] {
            background-color: var(--accent-emerald) !important;
            color: #ffffff !important;
            border-color: var(--accent-emerald) !important;
        }
        
        .signal-tag-strong-buy { background-color: rgba(16, 185, 129, 0.2); color: #10b981; padding: 6px 14px; border-radius: 6px; font-size: 0.9rem; font-weight: 800; border: 1px solid #10b981; display: inline-block; margin-bottom: 8px; }
        .signal-tag-accumulate { background-color: rgba(59, 130, 246, 0.2); color: #3b82f6; padding: 6px 14px; border-radius: 6px; font-size: 0.9rem; font-weight: 800; border: 1px solid #3b82f6; display: inline-block; margin-bottom: 8px; }
        .signal-tag-hold { background-color: rgba(245, 158, 11, 0.2); color: #f59e0b; padding: 6px 14px; border-radius: 6px; font-size: 0.9rem; font-weight: 800; border: 1px solid #f59e0b; display: inline-block; margin-bottom: 8px; }
        .signal-tag-avoid { background-color: rgba(239, 68, 68, 0.2); color: #ef4444; padding: 6px 14px; border-radius: 6px; font-size: 0.9rem; font-weight: 800; border: 1px solid #ef4444; display: inline-block; margin-bottom: 8px; }
    </style>
    """, unsafe_allow_html=True)

inject_custom_css()

# ─────────────────────────────────────────────────────────────────────────────
# 2. QUANT ENGINE: FROZEN CALCULATIONS (UNMODIFIED)
# ─────────────────────────────────────────────────────────────────────────────

def safe_float(val, default=0.0):
    if val is None: return default
    try:
        if isinstance(val, (int, float)): return float(val)
        s = str(val).replace(',', '').replace('₹', '').replace('Rs.', '').strip()
        if s.startswith('(') and s.endswith(')'): s = "-" + s[1:-1]
        return float(s) if s != '' else default
    except: return default

def safe_div(n, d, default=0.0):
    try:
        n_f = float(n) if n is not None else 0.0
        d_f = float(d) if d is not None else 0.0
        return n_f / d_f if d_f != 0 else default
    except: return default

def calculate_cagr(series, years):
    clean_series = [s for s in series if s is not None]
    if not clean_series or len(clean_series) < years + 1: return 0.0
    try:
        start_val = clean_series[-(years + 1)]
        end_val = clean_series[-1]
        if start_val <= 0 or end_val <= 0: return 0.0
        return ((end_val / start_val) ** (1 / years) - 1) * 100
    except: return 0.0

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
            if series: return series
    return None

def detect_financial_entity(ws, filename, extracted_name, raw_data):
    fin_keywords = ["bank", "nbfc", "advances", "deposits", "interest earned", "net interest income", "nii", "provisions & contingencies", "gross npa", "net npa", "capital adequacy", "housing finance", "microfinance"]
    ws_text_sample = ""
    for r in range(1, min(40, ws.max_row + 1)):
        for c in range(1, min(4, ws.max_column + 1)):
            val = ws.cell(row=r, column=c).value
            if val: ws_text_sample += f" {str(val).lower()}"
    if any(kw in ws_text_sample for kw in fin_keywords): return True
    combined_name = f"{extracted_name} {filename}".lower()
    name_fin_terms = ["bank", "finance", "fin", "nbfc", "capital", "housing fin", "lending"]
    if any(term in combined_name for term in name_fin_terms): return True
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
        capex_val = raw_capex if raw_capex > 0 else (abs(curr['cfi']) if curr['cfi'] != 0 else 0.0)

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
        
        ev = local_mcap + local_debt
        ebitda = curr['op'] if curr['op'] > 0 else local_ebit
        res["EV/EBITDA"] = safe_div(ev, ebitda) if ebitda > 0 else -1.0
        res["D/E"] = safe_div(local_debt, local_equity)
        
        res["OPM %"] = safe_div(curr['op'] if not is_fin else local_pat, local_sales) * 100
        res["ROE %"] = safe_div(local_pat, local_equity) * 100
        res["ROCE %"] = safe_div(local_ebit, local_equity + local_debt) * 100

        res["CWIP to Net Block %"] = safe_div(curr['cwip'], curr['net_block']) * 100 if curr['net_block'] > 0 else 0.0
        res["3Yr Sales CAGR %"] = calculate_cagr(raw['sales'], 3)
        res["3Yr PAT CAGR %"] = calculate_cagr(raw['pat'], 3)
        res["Sloan %"] = None if is_fin else (safe_div(local_pat - local_cfo, local_assets) * 100)

        if is_fin:
            res["Altman Z"] = None
            res["Zone"] = "N/A (Financial)"
        else:
            wc_proxy = (curr['receivables'] + curr['inventory'] + (local_assets * 0.05)) - curr['liab']
            z_val = (1.2 * safe_div(wc_proxy, local_assets)) + (1.4 * safe_div(curr['reserves'], local_assets)) + (3.3 * safe_div(curr['op'], local_assets)) + (0.6 * safe_div(local_mcap, local_debt + curr['liab'])) + (0.99 * safe_div(local_sales, local_assets))
            res["Altman Z"] = z_val
            res["Zone"] = "Safe" if z_val > 2.99 else "Grey" if z_val >= 1.81 else "Distress"

        p_score = 0
        if local_pat > 0: p_score += 1
        if local_cfo > 0: p_score += 1
        if local_cfo > local_pat: p_score += 1
        if res["3Yr PAT CAGR %"] > 0: p_score += 1
        if raw['debt'] and len(raw['debt']) > 1 and raw['equity'] and len(raw['equity']) > 1 and raw['reserves'] and len(raw['reserves']) > 1:
            if res["D/E"] <= safe_div(raw['debt'][-2], (raw['equity'][-2] or 0.0) + (raw['reserves'][-2] or 0.0)): p_score += 1
        if res["ROCE %"] > 12: p_score += 1
        if res["3Yr Sales CAGR %"] > 0: p_score += 1
        if local_assets > 0: p_score += 1
        res["Piotroski"] = p_score

        return res, file_bytes
    except Exception as e:
        st.error(f"Error in {filename}: {str(e)}")
        return None, None

def dataframe_to_markdown_table(df_sub):
    headers = list(df_sub.columns)
    header_row = "| " + " | ".join(headers) + " |"
    sep_row = "| " + " | ".join(["---"] * len(headers)) + " |"
    data_rows = ["| " + " | ".join([str(val) for val in row.values]) + " |" for _, row in df_sub.iterrows()]
    return "\n".join([header_row, sep_row] + data_rows)

# ─────────────────────────────────────────────────────────────────────────────
# 3. CONTENT GENERATION (3-TIER ANALYSYS)
# ─────────────────────────────────────────────────────────────────────────────

def get_tier_content(row, complexity):
    c = row["Company"]
    is_fin = row["Is_Financial"]
    
    # Pre-calculate indicators
    pe_status = "[🟢 STRONG]" if (row['PE'] > 0 and row['PE'] < 22) else "[🟡 AVERAGE]" if row['PE'] < 45 else "[🔴 WEAK]"
    roe_status = "[🟢 STRONG]" if row['ROE %'] > 18 else "[🟡 AVERAGE]" if row['ROE %'] > 12 else "[🔴 WEAK]"
    debt_status = "[🟢 STRONG]" if (row['D/E'] < 0.5 or (is_fin and row['D/E'] < 6.5)) else "[🔴 WEAK]"
    
    if complexity == "🌱 Beginner Investor":
        return {
            "PE": f"**Status:** {pe_status}\n- 💡 **In Plain Terms:** P/E is like a price tag. A score of {row['PE']:.1f} means for every ₹1 the company makes, you are paying ₹{row['PE']:.1f} to own it.\n- ⚠️ **When it lies:** It can look 'cheap' (low number) just because the company is in trouble and people are selling.",
            "ROE": f"**Status:** {roe_status}\n- 💡 **In Plain Terms:** This shows how much profit the company makes using the money owners put in. {row['ROE %']:.1f}% is like a bank interest rate for your investment.\n- ⚠️ **When it lies:** Companies can borrow too much money from banks to make this number look bigger than it really is.",
            "DE": f"**Status:** {debt_status}\n- 💡 **In Plain Terms:** This compares bank loans to the company's own cash. A score of {row['D/E']:.2f} tells you how 'heavy' the debt is.\n- ⚠️ **When it lies:** Some businesses like power plants or banks naturally have higher debt because they use it to build big things or lend to others.",
            "OPM": f"**Status:** {roe_status}\n- 💡 **In Plain Terms:** This is the money left over after paying for raw materials and workers. It's the 'spare change' from every sale.",
            "ALT": f"**Status:** {row['Zone']}\n- 💡 **In Plain Terms:** A health check score. 'Safe' means the company is unlikely to go bust soon.",
            "PIO": f"**Status:** {row['Piotroski']}/8\n- 💡 **In Plain Terms:** A 9-point report card. High scores mean the business is getting healthier every year."
        }
    elif complexity == "📈 Intermediate Investor":
        return {
            "PE": f"- **Practical View:** Trading at {row['PE']:.1f}x earnings. This is your 'valuation multiple'.\n- **Why it matters:** Lower multiples suggest better value, provided growth is stable. Check if this is below the 5-year sector average.",
            "ROE": f"- **Practical View:** Generating {row['ROE %']:.1f}% return on shareholder equity.\n- **Why it matters:** This is the core measure of internal capital efficiency. Consistent double-digit ROE is the hallmark of a compounder.",
            "DE": f"- **Practical View:** Debt-to-Equity is {row['D/E']:.2f}.\n- **Why it matters:** Anything above 1.0x (industrial) or 7.0x (banking) requires a closer look at interest coverage to ensure the debt isn't a burden.",
            "OPM": f"- **Practical View:** Operating Margin at {row['OPM %']:.1f}%.\n- **Why it matters:** High margins suggest pricing power or cost leadership in the industry.",
            "ALT": f"- **Practical View:** Solvency Zone: **{row['Zone']}**.\n- **Why it matters:** Forensic check on balance sheet stability. Avoid 'Distress' zones unless there is a clear turnaround catalyst.",
            "PIO": f"- **Practical View:** Quality Score: {row['Piotroski']}/8.\n- **Why it matters:** Tracks 8 fundamental improvements. 6+ is considered a high-quality signature."
        }
    else: # Institutional
        return {
            "PE": f"- **Quant Logic:** P/E Multiple of {row['PE']:.1f}x. Earnings Yield: {safe_div(1, row['PE'])*100:.2f}%.\n- **Metric Profile:** Trailing-Twelve-Month (TTM) relative valuation. Input for exit multiple assumptions.",
            "ROE": f"- **Quant Logic:** ROE at {row['ROE %']:.1f}%. Decomposition: Net Margin x Asset Turnover x Equity Multiplier.\n- **Metric Profile:** Measures efficiency of shareholder capital deployment.",
            "DE": f"- **Quant Logic:** Gearing ratio at {row['D/E']:.2f}. Capital structure check.\n- **Metric Profile:** Critical risk variable for Weighted Average Cost of Capital (WACC) calculations.",
            "OPM": f"- **Quant Logic:** OPM at {row['OPM %']:.1f}%. Proxy for EBITDA margin pre-adjustments.\n- **Metric Profile:** Core operational efficiency indicator.",
            "ALT": f"- **Quant Logic:** Altman Z-Score: {row['Altman Z'] if row['Altman Z'] else 'N/A'}.\n- **Metric Profile:** Multivariate formula based on liquidity, profitability, and leverage metrics.",
            "PIO": f"- **Quant Logic:** F-Score of {row['Piotroski']}.\n- **Metric Profile:** Binary assessment of 8 accounting-based fundamental momentum signals."
        }

def get_verdict(row):
    score = 0
    if row['ROE %'] >= 15: score += 1
    if 0 < row['PE'] <= 25: score += 1
    if (row['D/E'] <= 0.8 or (row['Is_Financial'] and row['D/E'] <= 7)): score += 1
    if row['Piotroski'] >= 6: score += 1
    if row['FCF Yield %'] >= 3: score += 1
    if row['Zone'] == "Safe": score += 1

    if score >= 5: return "STRONG BUY", "signal-tag-strong-buy"
    if score >= 3: return "ACCUMULATE ON DIPS", "signal-tag-accumulate"
    if score >= 2: return "HOLD / WATCHLIST", "signal-tag-hold"
    return "AVOID / EXIT", "signal-tag-avoid"

# ─────────────────────────────────────────────────────────────────────────────
# 4. APP FLOW & LAYOUT
# ─────────────────────────────────────────────────────────────────────────────

with st.sidebar:
    st.header("📂 Batch Ingestion")
    uploads = st.file_uploader("Upload Screener Excels", type=["xlsx", "xls"], accept_multiple_files=True)
    st.divider()
    st.header("🏛️ Tier Settings")
    complexity = st.radio("Select Analysis Complexity:", ["🌱 Beginner Investor", "📈 Intermediate Investor", "🏛️ Pro / Institutional Analyst"])
    st.divider()
    max_pe_bound = st.slider("Plot Max P/E Bound", 50, 300, 150)

st.markdown("<h1 class='hero-title'>🏛️ Institutional Research Terminal</h1>", unsafe_allow_html=True)
st.markdown(f"<p class='hero-subtitle'>Dynamic Quantitative Auditor | Profile: <b>{complexity}</b></p>", unsafe_allow_html=True)

if uploads:
    results, raw_files = [], []
    for up in uploads:
        data, b_content = process_workbook(up.getvalue(), up.name)
        if data:
            results.append(data)
            raw_files.append((up.name, b_content))

    if results:
        df = pd.DataFrame(results)
        
        # 1. TOP-LEVEL KPI DASHBOARD
        st.subheader("🏆 Cohort Leaders")
        kpi_cols = st.columns(3)
        valid_roe = df[df["ROE %"].notnull()]
        if not valid_roe.empty:
            best_roe = valid_roe.loc[valid_roe["ROE %"].idxmax()]
            kpi_cols[0].metric("ROE Leader", best_roe['Company'], f"{best_roe['ROE %']:.1f}%")
        
        valid_pe = df[df["PE"] > 0]
        if not valid_pe.empty:
            best_val = valid_pe.loc[valid_pe["PE"].idxmin()]
            kpi_cols[1].metric("Value Leader (P/E)", best_val['Company'], f"{best_val['PE']:.1f}x")
            
        valid_z = df[df["Altman Z"].notnull()]
        if not valid_z.empty:
            safest = valid_z.loc[valid_z["Altman Z"].idxmax()]
            kpi_cols[2].metric("Solvency Leader", safest['Company'], f"Z-Score {safest['Altman Z']:.2f}")

        # 2. MAIN TABULAR INTERFACE
        tab1, tab2, tab3, tab4, tab5 = st.tabs([
            "📊 Metric Deep-Dive", "🏛️ Investment Thesis", "🚦 Action Triggers", "🛡️ Risk Auditor", "📈 Visual Matrix"
        ])

        with tab1:
            target = st.selectbox("Select Target for Deep Analysis:", df["Company"].unique())
            row = df[df["Company"] == target].iloc[0]
            content = get_tier_content(row, complexity)
            
            with st.expander("▸ Group 1: Valuation & Operating Margins", expanded=True):
                c1, c2 = st.columns(2)
                c1.markdown(f"**P/E Ratio**\n{content['PE']}")
                c2.markdown(f"**Operating Margin (OPM %)**\n{content['OPM']}")

            with st.expander("▸ Group 2: Capital Efficiency & Cash Conversion", expanded=True):
                c1, c2 = st.columns(2)
                c1.markdown(f"**ROE %**\n{content['ROE']}")
                c2.markdown(f"**Free Cash Flow Yield**\n- Value: {row['FCF Yield %']:.1f}%\n- Meaning: Every ₹100 of market value generates ₹{row['FCF Yield %']:.1f} in surplus cash.")
                if not row['Is_Financial']:
                    st.markdown(f"**Sloan Accrual Ratio**\n- Value: {row['Sloan %']:.1f}%\n- Insight: High numbers (>10%) mean profit is 'paper-only' and not real cash.")

            with st.expander("▸ Group 3: Financial Safety & Operational Momentum", expanded=True):
                c1, c2 = st.columns(2)
                c1.markdown(f"**Debt-to-Equity**\n{content['DE']}")
                c2.markdown(f"**Altman Z-Score**\n{content['ALT']}")
                st.markdown(f"**Piotroski Quality Score**\n{content['PIO']}")

        with tab2:
            st.subheader("🏛️ Bull & Bear Thesis Side-by-Side")
            sel_stocks = st.multiselect("Select stocks to compare:", df["Company"].unique(), default=df["Company"].unique()[:2])
            if sel_stocks:
                cols = st.columns(len(sel_stocks))
                for i, s_name in enumerate(sel_stocks):
                    r = df[df["Company"] == s_name].iloc[0]
                    v_text, v_class = get_verdict(r)
                    with cols[i]:
                        st.markdown(f"<div class='{v_class}'>{v_text}</div>", unsafe_allow_html=True)
                        st.markdown(f"### {r['Company']}")
                        st.success(f"**🟢 Bull Case (Strengths):**\n- {r['ROE %']:.1f}% Return on Equity\n- Quality Score: {r['Piotroski']}/8\n- Solvency: {r['Zone']}")
                        st.error(f"**🔴 Bear Case (Vulnerabilities):**\n- Valuation: {r['PE']:.1f}x P/E\n- Leverage: {r['D/E']:.2f} D/E\n- OPM: {r['OPM %']:.1f}% Margin")

        with tab3:
            st.subheader("🚦 Action Triggers & Decision Framework")
            if sel_stocks:
                cols = st.columns(len(sel_stocks))
                for i, s_name in enumerate(sel_stocks):
                    r = df[df["Company"] == s_name].iloc[0]
                    with cols[i]:
                        st.info(f"**🎯 Buy Trigger:**\nAccumulate if P/E drops below {r['PE']*0.85:.1f}x while ROE stays >15%.")
                        st.warning(f"**⚠️ Sell Trigger:**\nExit if Piotroski drops below 4 or Debt-to-Equity exceeds {r['D/E']*1.3:.2f}.")
                        st.write("**🔄 Catalyst:** Monitor CWIP to Net Block ({:.1f}%). Asset commissioning will drive revenue.".format(r['CWIP to Net Block %']))

        with tab4:
            st.subheader("🛡️ Forensic Risk Auditor")
            for _, r in df.iterrows():
                with st.expander(f"Risk Audit: {r['Company']}"):
                    c1, c2, c3, c4 = st.columns(4)
                    if r['Net Profit'] > 0 and r['FCF'] < 0: c1.error("❌ Cash Burn Risk")
                    else: c1.success("✅ Cash Generative")
                    
                    if not r['Is_Financial']:
                        if r['D/E'] > 1.2: c2.error("❌ High Gearing")
                        else: c2.success("✅ Safe Leverage")
                        if r['Sloan %'] and r['Sloan %'] > 10: c3.warning("⚠️ High Accruals")
                        else: c3.success("✅ Clean Accruals")
                        if r['Altman Z'] and r['Altman Z'] < 1.8: c4.error("❌ Solvency Risk")
                        else: c4.success("✅ Solvent")
                    else:
                        c2.info("🏦 Financial Entity")
                        c3.info("N/A for Banks")
                        c4.info("Check Capital Adequacy")

        with tab5:
            st.subheader("📈 Visual Performance Analytics")
            vc1, vc2 = st.columns(2)
            with vc1:
                pdf = df.copy()
                pdf["PlotPE"] = pdf["PE"].apply(lambda x: min(x, max_pe_bound) if x > 0 else 0)
                fig1 = px.scatter(pdf, x="PlotPE", y="ROE %", size="Market Cap", color="Zone", hover_name="Company", title="Valuation vs efficiency")
                fig1.update_layout(template="plotly_dark", xaxis_title="P/E (Capped)")
                st.plotly_chart(fig1, use_container_width=True)
            with vc2:
                fig2 = go.Figure()
                fig2.add_trace(go.Bar(x=df['Company'], y=df['Piotroski'], name='Piotroski Score', marker_color='#10b981'))
                fig2.add_trace(go.Bar(x=df['Company'], y=[z if z else 0 for z in df['Altman Z']], name='Altman Z', marker_color='#3b82f6'))
                fig2.update_layout(template="plotly_dark", title="Quality vs Solvency")
                st.plotly_chart(fig2, use_container_width=True)

        # 3. EXPORT MODULE
        st.divider()
        report_md = f"# RESEARCH REPORT: {complexity}\n"
        report_md += f"Generated: {datetime.now().strftime('%Y-%m-%d')}\n\n"
        report_md += "## COHORT SUMMARY\n"
        report_md += dataframe_to_markdown_table(df[["Company", "PE", "ROE %", "D/E", "Zone", "Piotroski"]])
        
        st.download_button("📥 Download Research Report (.md)", data=report_md, file_name=f"Terminal_Report_{datetime.now().strftime('%Y%m%d')}.md")
        
        zip_io = io.BytesIO()
        with zipfile.ZipFile(zip_io, 'w') as zf:
            for fn, content in raw_files: zf.writestr(f"Processed_{fn}", content)
        st.download_button("📥 Download Raw Package (.zip)", data=zip_io.getvalue(), file_name="Terminal_Package.zip")

else:
    st.info("👋 Upload Screener.in Excel exports to start quantitative research.")
