import streamlit as st
import pandas as pd
import re
import os
import json
import time
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
# 2. SAFE GOOGLE GEMINI IMPORT & API SETUP
# ─────────────────────────────────────────────────────────────────────────────
try:
    from google import genai
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False

def resolve_gemini_key(sidebar_key):
    """Tiered resolution: Sidebar > Streamlit Secrets > Environment Variable."""
    if sidebar_key:
        return sidebar_key
    try:
        secret_key = st.secrets.get("GEMINI_API_KEY")
        if secret_key:
            return secret_key
    except:
        pass
    return os.getenv("GEMINI_API_KEY")

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
# 4. EXTRACTION ENGINE
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
    except:
        return "N/A"

def parse_file(file):
    try:
        xl = pd.ExcelFile(file, engine="openpyxl")
        ds_name = next((s for s in xl.sheet_names if "data sheet" in s.lower()), None)
        if not ds_name:
            st.error("Critical Failure: 'Data Sheet' tab not found.")
            return None
        
        df = pd.read_excel(xl, sheet_name=ds_name, header=None, dtype=str)
        data = {"company_name": str(df.iloc[0, 1]).strip()}
        data["sales_series"] = get_row_series(df, r"sales|revenue")
        data["pat_series"]   = get_row_series(df, r"net profit|profit after tax")
        
        sales = data["sales_series"][-1] if data["sales_series"] else 0
        pat   = data["pat_series"][-1] if data["pat_series"] else 0
        ebit  = get_latest(df, r"operating profit|ebit") or 0.0
        cfo   = get_latest(df, r"cash from operating|cfo") or 0.0
        pbt   = get_latest(df, r"profit before tax|pbt")
        
        borrowings = get_latest(df, r"borrowings|total debt") or 0.0
        reserves   = get_latest(df, r"reserves")
        share_cap  = get_latest(df, r"equity share capital|share capital")
        total_assets = get_latest(df, r"total assets")
        cash       = get_latest(df, r"cash equivalents|cash & bank|cash") or 0.0

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
        data["pe"] = div_safe(data["market_cap"], pat)
        data["cfo_pat"] = div_safe(cfo, pat)

        data["piotroski"] = get_tab_value(xl, "Health|Piotroski", "Piotroski F-Score")
        data["altman_zone"] = get_tab_value(xl, "Health|Piotroski", "Zone")
        data["dcf_val"] = get_tab_value(xl, "Intrinsic|Summary", "DCF")

        return data
    except Exception as e:
        st.error(f"Excel Processing Error: {e}")
        return None

# ─────────────────────────────────────────────────────────────────────────────
# 5. GEMINI AI ENGINE (FIXED: 429 RATE LIMIT & QUOTA FALLBACK)
# ─────────────────────────────────────────────────────────────────────────────

def get_gemini_summary(metrics_json, api_key):
    """
    Handles Gemini API calls with robust fallback for 429 (Quota) and 404 (Missing) errors.
    """
    if not GEMINI_AVAILABLE:
        st.error("The `google-genai` library is not installed.")
        return None
    
    if not api_key:
        st.warning("⚠️ No Gemini API Key found. Please add it to the sidebar.")
        return None

    # Priority List: Flash 1.5 is the most stable for Free Tiers. 
    # Flash 2.0/2.5 are newer and often have '0' limits for specific regions/keys.
    models_to_try = ["gemini-1.5-flash", "gemini-2.0-flash", "gemini-1.5-pro"]
    
    prompt_text = (
        f"Analyze this financial data: {json.dumps(metrics_json)}. "
        "Provide a 3-bullet executive summary covering Valuation, Health, and Momentum."
    )
    
    client = genai.Client(api_key=api_key)
    
    for model_name in models_to_try:
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=prompt_text
            )
            if response and response.text:
                return response.text
        except Exception as e:
            err_msg = str(e)
            if "429" in err_msg:
                # Quota exhausted for this specific model
                st.write(f"⚠️ {model_name} quota full. Retrying with next model...")
                time.sleep(2) # Short cooldown for rate limits
                continue
            elif "404" in err_msg or "not found" in err_msg.lower():
                # Model alias not recognized
                continue
            else:
                st.error(f"❌ Gemini Error ({model_name}): {err_msg}")
                return None
                
    st.error("❌ All Gemini models exhausted. Please try again in 60 seconds (API Rate Limit).")
    return None

# ─────────────────────────────────────────────────────────────────────────────
# 6. INVESTOR UI & SIDEBAR
# ─────────────────────────────────────────────────────────────────────────────

with st.sidebar:
    st.title("🛡️ Risk Controls")
    sidebar_key = st.text_input("Google Gemini API Key", type="password")
    resolved_key = resolve_gemini_key(sidebar_key)
    
    gov_ok = st.checkbox("Governance Verified", value=True)
    st.divider()
    up = st.file_uploader("Upload Screener.in Excel", type="xlsx")

if up:
    data = parse_file(up)
    
    if data:
        st.header(f"💎 {data['company_name']} | Strategic Analysis")
        
        # --- SCORECARD & AI SUMMARY ---
        s1 = data.get("roe", 0) >= 15
        s2 = data.get("cfo_pat", 0) >= 0.8
        s3 = data.get("pe", 100) <= (data.get("pe_5yr_avg", 20) * 1.1)
        score = sum([s1, s2, s3, gov_ok])

        col_score, col_ai = st.columns([1, 2])
        with col_score:
            st.metric("Fundamental Score", f"{score}/4")
            if score >= 3: st.success("Quality Approved")
            else: st.warning("High Risk")
        
        with col_ai:
            st.subheader("🤖 AI Strategic Narrative")
            if st.button("Generate Executive Summary"):
                llm_data = {
                    "PE": data['pe'], 
                    "ROIC": data['roic'], 
                    "Piotroski": data['piotroski'],
                    "DCF": data['dcf_val'],
                    "Zone": data['altman_zone']
                }
                with st.spinner("Rotating models to bypass rate limits..."):
                    summary = get_gemini_summary(llm_data, resolved_key)
                    if summary: st.info(summary)

        st.divider()

        # --- METRICS & DUPONT ---
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("ROIC %", fmt(data['roic'], 1, "%"))
        c2.metric("CFO/PAT", fmt(data['cfo_pat'], 2))
        c3.metric("Leverage", fmt(data['equity_multiplier'], 2))
        c4.metric("D/E Ratio", fmt(data['de'], 2))

        st.subheader("🔬 ROE Engineering (DuPont)")
        dup1, dup2, dup3 = st.columns(3)
        dup1.metric("Net Margin", fmt(data['net_margin'], 1, "%"))
        dup2.metric("Asset Turn", fmt(data['asset_turnover'], 2))
        dup3.metric("Equity Multiplier", fmt(data['equity_multiplier'], 2))

        # --- CHARTS ---
        if data["sales_series"]:
            with st.expander("📈 View Trends"):
                fig = go.Figure()
                fig.add_trace(go.Scatter(y=data["sales_series"], name="Revenue", line=dict(color="#00CC96")))
                fig.add_trace(go.Scatter(y=data["pat_series"], name="Net Profit", line=dict(color="#636EFA")))
                st.plotly_chart(fig, use_container_width=True)

else:
    st.title("🏛️ Strategic Equity Evaluator")
    st.info("Upload a Screener.in Excel file to begin.")
