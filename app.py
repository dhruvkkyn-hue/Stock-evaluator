import streamlit as st
import pandas as pd
import re
import os
import json
import plotly.graph_objects as go

# ─────────────────────────────────────────────────────────────────────────────
# 1. MANDATORY: PAGE CONFIG (MUST BE FIRST)
# ─────────────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Institutional Equity Terminal", 
    layout="wide", 
    page_icon="💎"
)

# ─────────────────────────────────────────────────────────────────────────────
# 2. SAFE OPENAI IMPORT & API SETUP
# ─────────────────────────────────────────────────────────────────────────────
try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False

def resolve_api_key(sidebar_key):
    """Tiered resolution: Sidebar > Streamlit Secrets > Environment Variable."""
    if sidebar_key:
        return sidebar_key
    
    # Try Streamlit Secrets (for Cloud Deployment)
    try:
        secret_key = st.secrets.get("OPENAI_API_KEY")
        if secret_key:
            return secret_key
    except:
        pass
        
    # Try OS Environment (for Local Testing)
    return os.getenv("OPENAI_API_KEY")

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
    return n / d if d != 0 else 0.0

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
# 4. EXTRACTION ENGINE (FIXED NameError: parse_file)
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
    """Scans specialized sheets (Health, Trends, etc.) for specific data points."""
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
    """FIXED: Processes the uploaded Excel file and calculates core metrics."""
    try:
        xl = pd.ExcelFile(file, engine="openpyxl")
        
        # ─── Data Sheet Extractions ───
        ds_name = next((s for s in xl.sheet_names if "data sheet" in s.lower()), None)
        if not ds_name:
            st.error("Critical Failure: 'Data Sheet' tab not found in the Excel file.")
            return None
        
        df = pd.read_excel(xl, sheet_name=ds_name, header=None, dtype=str)
        
        data = {"company_name": str(df.iloc[0, 1]).strip()}
        data["sales_series"] = get_row_series(df, r"sales|revenue")
        data["pat_series"]   = get_row_series(df, r"net profit|profit after tax")
        data["cfo_series"]   = get_row_series(df, r"cash from operating|cfo")
        ebit_series          = get_row_series(df, r"operating profit|ebit")
        
        # Latest Snapshot
        pat   = data["pat_series"][-1] if data["pat_series"] else 0
        sales = data["sales_series"][-1] if data["sales_series"] else 0
        ebit  = ebit_series[-1] if ebit_series else 0
        cfo   = data["cfo_series"][-1] if data["cfo_series"] else 0
        pbt   = get_latest(df, r"profit before tax|pbt")
        
        # Balance Sheet
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
        data["de"] = div_safe(borrowings, equity)
        tax_rate = div_safe((safe_num(pbt) - safe_num(pat)), pbt) if safe_num(pbt) > 0 else 0.25
        nopat = safe_num(ebit) * (1 - tax_rate)
        invested_cap = max((equity + safe_num(borrowings) - safe_num(cash)), equity)
        
        data["roic"] = div_safe(nopat, invested_cap) * 100
        data["roe"] = div_safe(pat, equity) * 100
        data["net_margin"] = div_safe(pat, sales) * 100
        data["asset_turnover"] = div_safe(sales, total_assets if total_assets else (equity + borrowings))
        data["equity_multiplier"] = div_safe(total_assets if total_assets else (equity + borrowings), equity)
        data["fcf_conv"] = div_safe(safe_num(cfo) - abs(safe_num(capex)), pat) * 100
        data["pe"] = div_safe(data["market_cap"], pat)
        data["cfo_pat"] = div_safe(cfo, pat)

        # Scrape Secondary Tabs for AI Narrative
        data["piotroski"] = get_tab_value(xl, "Health|Piotroski", "Piotroski F-Score")
        data["altman_zone"] = get_tab_value(xl, "Health|Piotroski", "Zone")
        data["dcf_val"] = get_tab_value(xl, "Intrinsic|Summary", "DCF")

        return data
    except Exception as e:
        st.error(f"Excel Processing Error: {e}")
        return None

# ─────────────────────────────────────────────────────────────────────────────
# 5. SAFE AI STRATEGIC ENGINE
# ─────────────────────────────────────────────────────────────────────────────

def get_ai_summary(metrics_json, api_key):
    """Safely calls OpenAI with 401 handling."""
    if not OPENAI_AVAILABLE:
        st.error("The 'openai' library is not installed in the environment.")
        return None
    
    if not api_key:
        st.warning("⚠️ Please enter a valid OpenAI API Key in the sidebar to generate the summary.")
        return None
    
    try:
        client = OpenAI(api_key=api_key)
        system_prompt = (
            "You are a Senior Equity Research Analyst. Provide a concise 3-bullet executive "
            "summary focused on: 1. Valuation Gap, 2. Financial Health, 3. Business Momentum."
        )
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
        err_str = str(e).lower()
        if "401" in err_str or "invalid_api_key" in err_str:
            st.error("🔐 Authentication Failed: The OpenAI API Key provided is invalid.")
        else:
            st.error(f"❌ AI Error: {str(e)}")
        return None

# ─────────────────────────────────────────────────────────────────────────────
# 6. INVESTOR UI & SIDEBAR
# ─────────────────────────────────────────────────────────────────────────────

with st.sidebar:
    st.title("🛡️ Risk Controls")
    sidebar_key = st.text_input("OpenAI API Key", type="password", help="Leave blank if set in Streamlit Secrets.")
    resolved_key = resolve_api_key(sidebar_key)
    
    gov_ok = st.checkbox("Governance Verified", value=True)
    st.divider()
    up = st.file_uploader("Upload Screener.in Excel", type="xlsx")

if up:
    # Main File Processing Block
    data = parse_file(up)
    
    if data:
        try:
            st.header(f"💎 {data['company_name']} | Strategic Analysis")
            
            # ── 1. SCORECARD & AI SUMMARY ──
            s1 = data.get("roe", 0) >= 15
            s2 = data.get("cfo_pat", 0) >= 0.8
            s3 = data.get("pe", 100) <= (data.get("pe_5yr_avg", 20) * 1.1)
            score = sum([s1, s2, s3, gov_ok])

            col_score, col_ai = st.columns([1, 2])
            with col_score:
                st.metric("Fundamental Score", f"{score}/4")
                if score >= 3: st.success("Quality Threshold Met")
                else: st.warning("High Risk / Speculative")
            
            with col_ai:
                st.subheader("🤖 AI Executive Narrative")
                if st.button("Generate Strategic Summary"):
                    llm_data = {
                        "PE": data['pe'], 
                        "ROIC": data['roic'], 
                        "Piotroski": data['piotroski'],
                        "DCF": data['dcf_val'],
                        "Zone": data['altman_zone']
                    }
                    with st.spinner("Analyzing via GPT-4o..."):
                        summary = get_ai_summary(llm_data, resolved_key)
                        if summary: st.info(summary)
                else:
                    st.caption("Click the button above to trigger AI qualitative analysis.")

            st.divider()

            # ── 2. METRIC WORKSPACE (Refactored) ──
            def metric_card(title, value, translation, status="info"):
                with st.container(border=True):
                    st.markdown(f"**{title}**")
                    st.subheader(value)
                    st.caption(f"💡 {translation}")

            c1, c2, c3, c4 = st.columns(4)
            with c1:
                metric_card("ROIC", fmt(data['roic'], 1, "%"), "Efficiency of capital use.", "success")
            with c2:
                metric_card("CFO/PAT", fmt(data['cfo_pat'], 2), "Cash backing of earnings.", "info")
            with c3:
                metric_card("Equity Multiplier", fmt(data['equity_multiplier'], 2) + "x", "Leverage dosage.", "warning")
            with c4:
                metric_card("D/E Ratio", fmt(data['de'], 2), "Debt safety level.", "success")

            # ── 3. DUPONT ANALYSIS ──
            st.divider()
            st.subheader("🔬 ROE Engineering (DuPont)")
            st.markdown(f"**Current ROE: {fmt(data['roe'], 1, '%')}**")
            dup1, dup2, dup3 = st.columns(3)
            dup1.metric("Net Margin", fmt(data['net_margin'], 1, "%"))
            dup2.metric("Asset Turn", fmt(data['asset_turnover'], 2))
            dup3.metric("Leverage Factor", fmt(data['equity_multiplier'], 2))

            # ── 4. CHART ──
            if data["sales_series"]:
                with st.expander("📈 View Financial Trends"):
                    fig = go.Figure()
                    fig.add_trace(go.Scatter(y=data["sales_series"], name="Revenue", line=dict(color="#2ECC71")))
                    fig.add_trace(go.Scatter(y=data["pat_series"], name="Net Profit", line=dict(color="#3498DB")))
                    st.plotly_chart(fig, use_container_width=True)

        except Exception as e:
            st.error(f"Rendering Error: {e}")

else:
    st.title("🏛️ Strategic Equity Evaluator")
    st.info("Please upload a Screener.in Excel file to begin.")
