import streamlit as st
import pandas as pd
import re
import plotly.graph_objects as go
import json
import os  # Added for environment variable fallback

# ─────────────────────────────────────────────────────────────────────────────
# 1. SAFE OPENAI IMPORT
# ─────────────────────────────────────────────────────────────────────────────
try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False

# ─────────────────────────────────────────────────────────────────────────────
# 2. PAGE CONFIG
# ─────────────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Institutional Equity Terminal", 
    layout="wide", 
    page_icon="💎"
)

# ─────────────────────────────────────────────────────────────────────────────
# 3. AI STRATEGIC ENGINE (WITH KEY FALLBACK & 401 HANDLING)
# ─────────────────────────────────────────────────────────────────────────────

def get_ai_summary(metrics_json, api_key):
    """
    Safely handles OpenAI calls with the resolved API key.
    """
    if not OPENAI_AVAILABLE:
        st.error("The 'openai' library is not installed. Check requirements.txt.")
        return None
    
    # Validation Check: Ensure a key exists before trying to initialize
    if not api_key:
        st.warning("⚠️ Please enter a valid OpenAI API key in the sidebar to generate the AI Executive Summary.")
        return None
    
    try:
        # Initialize client with the resolved key
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
        # Specifically catch the 401 error among others
        error_msg = str(e)
        if "401" in error_msg or "invalid_api_key" in error_msg:
            st.error("🔐 **Invalid API Key:** The provided OpenAI key is incorrect or has expired. Please check your sidebar input.")
        else:
            st.error(f"❌ AI Engine Error: {error_msg}")
        return None

# ─────────────────────────────────────────────────────────────────────────────
# 4. EXTRACTION ENGINE & HELPERS (PRESERVED)
# ─────────────────────────────────────────────────────────────────────────────
# [Note: safe_num, div_safe, fmt, to_num, get_row_series, get_latest, get_tab_value, parse_file would be here as per previous versions]
# ... (Assuming helper functions from baseline remain intact) ...

# ─────────────────────────────────────────────────────────────────────────────
# 5. SIDEBAR & KEY RESOLUTION LOGIC
# ─────────────────────────────────────────────────────────────────────────────

with st.sidebar:
    st.title("🔐 Analyst Controls")
    
    # 1. Sidebar Input Field
    sidebar_api_key = st.text_input("Enter OpenAI API Key", type="password")
    
    # 2. Hierarchy Logic (Sidebar -> Secrets -> Environment)
    def resolve_api_key():
        if sidebar_api_key:
            return sidebar_api_key
        
        # Check Streamlit Secrets (for Cloud deployment)
        if "OPENAI_API_KEY" in st.secrets:
            return st.secrets["OPENAI_API_KEY"]
            
        # Check OS Environment variables (Local testing)
        return os.getenv("OPENAI_API_KEY")

    resolved_key = resolve_api_key()

    gov_ok = st.checkbox("Governance Verified", value=True)
    st.divider()
    up = st.file_uploader("Upload Screener Excel", type="xlsx")

# ─────────────────────────────────────────────────────────────────────────────
# 6. MAIN UI LOGIC
# ─────────────────────────────────────────────────────────────────────────────

if up:
    # (Assuming parse_file is defined as in your previous working script)
    data = parse_file(up) # type: ignore
    
    if data:
        st.header(f"💎 {data['company_name']}")
        
        # ── SCORE & AI TRIGGER ──
        s1 = data.get("roe", 0) >= 15
        s2 = data.get("cfo_pat", 0) >= 0.8
        s3 = data.get("pe", 100) <= (data.get("pe_5yr_avg", 20) * 1.1)
        score = sum([s1, s2, s3, gov_ok])

        col_score, col_ai = st.columns([1, 2])
        with col_score:
            st.metric("Fundamental Score", f"{score}/4")
        
        with col_ai:
            st.subheader("🤖 AI Strategic Narrative")
            if st.button("Generate AI Executive Summary"):
                # Pass the metrics and the RESOLVED key
                llm_data = {"Valuation": data['pe'], "ROIC": data['roic'], "Health": data['piotroski']} # type: ignore
                
                with st.spinner("Consulting AI Analyst..."):
                    summary = get_ai_summary(llm_data, resolved_key)
                    if summary:
                        st.info(summary)
            else:
                st.caption("Click to generate a qualitative narrative via GPT-4o.")

        # ... (Rest of the DuPont, Charts, and Investor Plan code) ...
