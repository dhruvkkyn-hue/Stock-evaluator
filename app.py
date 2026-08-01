import streamlit as st
import pandas as pd
import re
import plotly.graph_objects as go
import json
from openai import OpenAI

# ─────────────────────────────────────────────────────────────────────────────
# 1. MANDATORY: PAGE CONFIG
# ─────────────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Institutional Equity Terminal + AI", 
    layout="wide", 
    page_icon="💎"
)

# ─────────────────────────────────────────────────────────────────────────────
# 2. BASELINE PRECISION HELPERS (PRESERVED)
# ─────────────────────────────────────────────────────────────────────────────

def safe_num(val, default=0.0):
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default

def div_safe(numerator, denominator):
    n = safe_num(numerator)
    d = safe_num(denominator)
    if d == 0:
        return 0.0
    return n / d

def fmt(v, d=2, sfx="", prefix=""):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "N/A"
    return f"{prefix}{safe_num(v):,.{d}f}{sfx}"

def to_num(val):
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    s = str(val).strip().replace(",", "").replace("₹", "").replace("Rs.", "")
    s = re.sub(r"\s*(cr|crores?|%|x|times|inr)\.?\s*$", "", s, flags=re.I)
    if s.startswith("(") and s.endswith(")"):
        s = "-" + s[1:-1]
    try:
        return float(s)
    except:
        return None

# ─────────────────────────────────────────────────────────────────────────────
# 3. AI STRATEGIC ENGINE
# ─────────────────────────────────────────────────────────────────────────────

def get_ai_summary(metrics_json, api_key):
    """Calls OpenAI to generate the 3-bullet executive analysis."""
    if not api_key:
        return "⚠️ OpenAI API Key missing in sidebar. AI Analysis skipped."
    
    try:
        client = OpenAI(api_key=api_key)
        system_prompt = (
            "You are a Lead Quantitative Fund Manager. Analyze the provided metrics JSON "
            "and produce a 3-bullet executive analysis for a high-net-worth investor."
        )
        user_content = f"""
        DATA: {json.dumps(metrics_json)}
        
        REQUIREMENTS:
        - Bullet 1: Valuation Gap (CMP vs DCF/Graham/Dhandho).
        - Bullet 2: Financial Health (Piotroski, Altman, Sloan quality).
        - Bullet 3: Business Momentum (Revenue & Margin trajectory).
        Keep it sharp, non-jargon, and objective.
        """
        
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content}
            ],
            temperature=0.2
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"❌ AI Engine Error: {str(e)}"

# ─────────────────────────────────────────────────────────────────────────────
# 4. ENHANCED EXTRACTION ENGINE
# ─────────────────────────────────────────────────────────────────────────────

def get_tab_value(xl, tab_name_regex, label_regex):
    """Scans specific tabs for labels and returns the adjacent numeric value."""
    try:
        sheet_name = next((s for s in xl.sheet_names if re.search(tab_name_regex, s, re.I)), None)
        if not sheet_name: return "N/A"
        df = pd.read_excel(xl, sheet_name=sheet_name, header=None).astype(str)
        for r_idx in range(len(df)):
            cell_val = df.iloc[r_idx, 0].lower()
            if re.search(label_regex.lower(), cell_val):
                return df.iloc[r_idx, 1]
        return "N/A"
    except:
        return "N/A"

def parse_file(file):
    try:
        xl = pd.ExcelFile(file, engine="openpyxl")
        
        # ─── DATA SHEET EXTRACTION ───
        ds_name = next((s for s in xl.sheet_names if "data sheet" in s.lower()), None)
        if not ds_name:
            st.error("Critical Failure: 'Data Sheet' tab not found.")
            return None
        df = pd.read_excel(xl, sheet_name=ds_name, header=None, dtype=str)
        
        data = {"company_name": str(df.iloc[0, 1]).strip()}
        data["sales_series"] = get_row_series(df, r"sales|revenue")
        data["pat_series"]   = get_row_series(df, r"net profit|profit after tax")
        data["cfo_series"]   = get_row_series(df, r"cash from operating|cfo")
        ebit_series          = get_row_series(df, r"operating profit|ebit")
        
        sales = data["sales_series"][-1] if data["sales_series"] else 0
        pat   = data["pat_series"][-1] if data["pat_series"] else 0
        ebit  = ebit_series[-1] if ebit_series else 0
        cfo   = data["cfo_series"][-1] if data["cfo_series"] else 0
        pbt   = get_latest(df, r"profit before tax|pbt")
        
        share_cap  = get_latest(df, r"equity share capital|share capital")
        reserves   = get_latest(df, r"reserves")
        borrowings = get_latest(df, r"borrowings|total debt") or 0.0
        total_assets = get_latest(df, r"total assets")
        cash       = get_latest(df, r"cash equivalents|cash & bank|cash") or 0.0
        capex      = get_latest(df, r"fixed assets purchased|capital expenditure|capex") or 0.0
        depr       = get_latest(df, r"depreciation") or 0.0

        data["cmp"] = get_latest(df, r"current price|cmp")
        data["market_cap"] = get_latest(df, r"market capitalization|market cap")
        data["pe_5yr_avg"] = get_latest(df, [r"5 year avg pe", r"median pe"]) or 20.0

        # Calculations
        equity = safe_num(share_cap) + safe_num(reserves)
        data["equity"] = equity
        data["de"] = div_safe(borrowings, equity)
        tax_rate = div_safe((safe_num(pbt) - safe_num(pat)), pbt) if safe_num(pbt) > 0 else 0.25
        nopat = safe_num(ebit) * (1 - tax_rate)
        invested_cap = max((equity + safe_num(borrowings) - safe_num(cash)), equity)
        
        data["roic"] = div_safe(nopat, invested_cap) * 100
        data["roe"] = div_safe(pat, equity) * 100
        data["net_margin"] = div_safe(pat, sales) * 100
        data["asset_turnover"] = div_safe(sales, total_assets if total_assets else (equity + borrowings))
        data["equity_multiplier"] = div_safe(total_assets if total_assets else (equity + borrowings), equity)
        data["fcf"] = safe_num(cfo) - abs(safe_num(capex))
        data["owner_earnings"] = safe_num(pat) + safe_num(depr) - abs(safe_num(capex))
        data["fcf_conv"] = div_safe(data["fcf"], pat) * 100
        data["reinv_rate"] = div_safe(abs(safe_num(capex)), nopat) * 100
        data["compounding_rate"] = (data["roic"] / 100) * data["reinv_rate"]
        data["pe"] = div_safe(data["market_cap"], pat)
        data["cfo_pat"] = div_safe(cfo, pat)

        # ─── LLM-SPECIFIC METRIC EXTRACTION ───
        # These look at other tabs in the workbook
        data["piotroski"] = get_tab_value(xl, "Health|Piotroski", "Piotroski F-Score")
        data["altman_z"] = get_tab_value(xl, "Health|Piotroski", "Altman Z-Score")
        data["altman_zone"] = get_tab_value(xl, "Health|Piotroski", "Zone")
        data["sloan"] = get_tab_value(xl, "Health|Piotroski", "Sloan Accrual")
        data["dcf_val"] = get_tab_value(xl, "Intrinsic|Summary", "DCF")
        data["graham_val"] = get_tab_value(xl, "Intrinsic|Summary", "Graham")
        data["dhandho_val"] = get_tab_value(xl, "Intrinsic|Summary", "Dhandho")
        data["rev_trend"] = get_tab_value(xl, "Trend", "Revenue Trend")

        return data
    except Exception as e:
        st.error(f"Excel Parsing Error: {e}")
        return None

# Placeholder for baseline helpers
def get_row_series(df, label_query):
    label_query = label_query.lower().strip()
    for r_idx in range(len(df)):
        cell_label = str(df.iloc[r_idx, 0]).lower().strip()
        if re.search(label_query, cell_label):
            return [to_num(val) for val in df.iloc[r_idx, 1:] if to_num(val) is not None]
    return []

def get_latest(df, labels):
    if isinstance(labels, str): labels = [labels]
    for label in labels:
        series = get_row_series(df, label)
        if series: return series[-1]
    return None

# ─────────────────────────────────────────────────────────────────────────────
# 5. INVESTOR INTERFACE
# ─────────────────────────────────────────────────────────────────────────────

with st.sidebar:
    st.title("🔐 Analyst Controls")
    ticker = st.text_input("Ticker Symbol", "STOCK").upper()
    api_key = st.text_input("OpenAI API Key", type="password")
    gov_ok = st.checkbox("Governance Verified", value=True)
    beta_val = st.number_input("Stock Beta", value=1.0, step=0.1)
    st.divider()
    up = st.file_uploader("Upload Screener.in Excel", type="xlsx")

if not up:
    st.title("🏛️ Strategic Equity Evaluator")
    st.info("Upload Excel to begin.")
else:
    data = parse_file(up)
    if data:
        st.header(f"💎 {data['company_name']} | Strategic Evaluation")
        
        # ── 1. SCORECARD & AI NARRATIVE ──
        s1 = data.get("roe", 0) >= 15
        s2 = data.get("cfo_pat", 0) >= 0.8
        s3 = data.get("pe", 100) <= (data.get("pe_5yr_avg", 20) * 1.1)
        s4 = gov_ok
        score = sum([s1, s2, s3, s4])

        col_score, col_ai = st.columns([1, 2])
        
        with col_score:
            st.metric("Fundamental Score", f"{score}/4")
            if score >= 3: st.success("Quality Approved")
            else: st.error("Caution Advised")
            
        with col_ai:
            st.subheader("🤖 AI Strategic Narrative")
            # Create a clean JSON for the LLM
            llm_metrics = {
                "Valuation": {"CMP": data['cmp'], "DCF": data['dcf_val'], "Graham": data['graham_val'], "PE": data['pe']},
                "Health": {"Piotroski": data['piotroski'], "Altman": data['altman_z'], "Zone": data['altman_zone'], "Sloan": data['sloan']},
                "Performance": {"ROIC": data['roic'], "ROE": data['roe'], "Revenue_Trend": data['rev_trend']}
            }
            
            if st.button("Generate AI Executive Summary"):
                with st.spinner("Analyzing data via GPT-4o..."):
                    summary = get_ai_summary(llm_metrics, api_key)
                    st.markdown(summary)
            else:
                st.caption("Click the button to generate an AI-driven qualitative summary.")

        st.divider()

        # ── 2. INVESTOR MANDATE SUITABILITY (Refactored) ──
        st.subheader("🎯 Investor Mandate Suitability")
        m_col1, m_col2 = st.columns(2)
        with m_col1:
            st.markdown("### 🟢 BUY IF YOUR MANDATE IS:")
            if data['roic'] > 18: st.success(f"**Long-Term Quality:** ROIC {fmt(data['roic'],1)}% vs cost of capital.")
            if data['fcf_conv'] > 80: st.success(f"**Cash Purity:** {fmt(data['fcf_conv'],1)}% conversion.")
        with m_col2:
            st.markdown("### 🔴 AVOID IF YOUR MANDATE IS:")
            if data['pe'] > (data['pe_5yr_avg'] * 1.25): st.error("**Deep Value:** Significant premium to 5yr PE.")
            if data['de'] > 1.0: st.error(f"**Zero Debt:** Leverage is {fmt(data['de'])}x.")

        st.divider()

        # ── 3. METRIC WORKSPACE (Refactored) ──
        def metric_card(title, value, translation, status="info"):
            with st.container(border=True):
                st.markdown(f"**{title}**")
                st.subheader(value)
                st.caption(f"💡 {translation}")

        c1, c2, c3, c4 = st.columns(4)
        with c1:
            metric_card("ROIC", fmt(data['roic'], 1, "%"), "Return on actual capital deployed.", "success")
        with c2:
            metric_card("CFO/PAT", fmt(data['cfo_pat'], 2), "Cash reality check.", "info")
        with c3:
            metric_card("Equity Multiplier", fmt(data['equity_multiplier'], 2) + "x", "Leverage dosage.", "warning")
        with c4:
            metric_card("D/E Ratio", fmt(data['de'], 2), "Solvency check.", "success")

        # ── 4. DUPONT BREAKDOWN ──
        st.divider()
        st.subheader("🔬 ROE Engineering (DuPont)")
        st.markdown(f"**Current ROE: {fmt(data['roe'], 1, '%')}**")
        dup1, dup2, dup3 = st.columns(3)
        dup1.metric("Net Margin", fmt(data['net_margin'], 1, "%"))
        dup2.metric("Asset Efficiency", fmt(data['asset_turnover'], 2) + "x")
        dup3.metric("Leverage Factor", fmt(data['equity_multiplier'], 2) + "x")

        # ── 5. VISUALIZATION ──
        with st.expander("📈 Revenue & Profit Trends"):
            if data["sales_series"]:
                fig = go.Figure()
                fig.add_trace(go.Scatter(y=data["sales_series"], name="Sales"))
                fig.add_trace(go.Scatter(y=data["pat_series"], name="Profit"))
                st.plotly_chart(fig, use_container_width=True)
