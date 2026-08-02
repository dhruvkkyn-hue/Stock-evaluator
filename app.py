import streamlit as st
import pandas as pd
import re
import plotly.graph_objects as go
import json

# ─────────────────────────────────────────────────────────────────────────────
# 1. SAFE OPENAI IMPORT (PREVENTS CRASHING IF MODULE IS MISSING)
# ─────────────────────────────────────────────────────────────────────────────
try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False

# ─────────────────────────────────────────────────────────────────────────────
# 2. MANDATORY: PAGE CONFIG (MUST BE FIRST LINE OF CODE)
# ─────────────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Institutional Equity Terminal", 
    layout="wide", 
    page_icon="💎"
)

# ─────────────────────────────────────────────────────────────────────────────
# 3. BASELINE PRECISION HELPERS
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
# 4. AI STRATEGIC ENGINE (SAFE WRAPPER)
# ─────────────────────────────────────────────────────────────────────────────

def get_ai_summary(metrics_json, api_key):
    if not OPENAI_AVAILABLE:
        st.error("The 'openai' library is not installed. Check requirements.txt.")
        return None
    if not api_key:
        st.warning("Please enter your OpenAI API Key in the sidebar to use AI features.")
        return None
    
    try:
        client = OpenAI(api_key=api_key)
        system_prompt = "You are a Lead Quant Fund Manager. Analyze the JSON metrics and provide a 3-bullet executive summary (Valuation, Health, Momentum)."
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"DATA: {json.dumps(metrics_json)}"}
            ],
            temperature=0.2
        )
        return response.choices[0].message.content
    except Exception as e:
        st.error(f"AI Error: {str(e)}")
        return None

# ─────────────────────────────────────────────────────────────────────────────
# 5. EXTRACTION ENGINE
# ─────────────────────────────────────────────────────────────────────────────

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

def get_tab_value(xl, tab_name_regex, label_regex):
    try:
        sheet_name = next((s for s in xl.sheet_names if re.search(tab_name_regex, s, re.I)), None)
        if not sheet_name: return "N/A"
        df = pd.read_excel(xl, sheet_name=sheet_name, header=None).astype(str)
        for r_idx in range(len(df)):
            cell_val = df.iloc[r_idx, 0].lower()
            if re.search(label_regex.lower(), cell_val):
                return df.iloc[r_idx, 1]
        return "N/A"
    except: return "N/A"

def parse_file(file):
    try:
        xl = pd.ExcelFile(file, engine="openpyxl")
        ds_name = next((s for s in xl.sheet_names if "data sheet" in s.lower()), None)
        if not ds_name:
            st.error("Data Sheet tab missing.")
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

        equity = safe_num(share_cap) + safe_num(reserves)
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

        # AI Metric Scrapes
        data["piotroski"] = get_tab_value(xl, "Health|Piotroski", "Piotroski F-Score")
        data["altman_z"] = get_tab_value(xl, "Health|Piotroski", "Altman Z-Score")
        data["dcf_val"] = get_tab_value(xl, "Intrinsic|Summary", "DCF")
        data["graham_val"] = get_tab_value(xl, "Intrinsic|Summary", "Graham")

        return data
    except Exception as e:
        st.error(f"Error parsing file: {e}")
        return None

# ─────────────────────────────────────────────────────────────────────────────
# 6. UI LAYOUT
# ─────────────────────────────────────────────────────────────────────────────

with st.sidebar:
    st.title("🔐 Analyst Controls")
    api_key = st.text_input("OpenAI API Key", type="password")
    gov_ok = st.checkbox("Governance Verified", value=True)
    st.divider()
    up = st.file_uploader("Upload Screener Excel", type="xlsx")

if up:
    data = parse_file(up)
    if data:
        st.header(f"💎 {data['company_name']}")
        
        # ── 1. SCORE & AI NARRATIVE ──
        s1 = data.get("roe", 0) >= 15
        s2 = data.get("cfo_pat", 0) >= 0.8
        s3 = data.get("pe", 100) <= (data.get("pe_5yr_avg", 20) * 1.1)
        score = sum([s1, s2, s3, gov_ok])

        col_score, col_ai = st.columns([1, 2])
        with col_score:
            st.metric("Fundamental Score", f"{score}/4")
        with col_ai:
            if st.button("Generate AI Executive Summary"):
                llm_data = {"Valuation": data['pe'], "ROIC": data['roic'], "Health": data['piotroski']}
                summary = get_ai_summary(llm_data, api_key)
                if summary: st.info(summary)

        st.divider()

        # ── 2. INVESTOR MANDATE ──
        st.subheader("🎯 Investor Mandate Suitability")
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("### 🟢 BUY IF:")
            if data['roic'] > 18: st.success(f"Quality Focus: ROIC is {fmt(data['roic'],1)}%")
        with c2:
            st.markdown("### 🔴 AVOID IF:")
            if data['de'] > 1.0: st.error("Zero Debt Mandate: High Leverage detected.")

        # ── 3. DUPONT ANALYSIS ──
        st.divider()
        st.subheader("🔬 ROE Engineering (DuPont)")
        d1, d2, d3 = st.columns(3)
        d1.metric("Net Margin", fmt(data['net_margin'], 1, "%"))
        d2.metric("Asset Turn", fmt(data['asset_turnover'], 2))
        d3.metric("Leverage Factor", fmt(data['equity_multiplier'], 2))
        
        if data['equity_multiplier'] > 2.2:
            st.warning("⚠️ ROE is significantly driven by debt (Leverage).")

        # ── 4. CHART ──
        if data["sales_series"]:
            with st.expander("📈 Revenue Trajectory"):
                fig = go.Figure()
                fig.add_trace(go.Scatter(y=data["sales_series"], name="Sales"))
                st.plotly_chart(fig, use_container_width=True)
