import streamlit as st
import pandas as pd
import sqlite3
import re
import plotly.graph_objects as go

# ─────────────────────────────────────────────────────────────────────────────
# UI Helpers & Formatting
# ─────────────────────────────────────────────────────────────────────────────
def fmt(v, d=2, sfx=""):
    """Safely format numeric values. Returns 'N/A' if missing."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "N/A"
    try:
        return f"{float(v):,.{d}f}{sfx}"
    except (ValueError, TypeError):
        return "N/A"

def to_num(val):
    """Clean Screener.in formatting into floats."""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    s = str(val).strip().replace(",", "").replace("₹", "").replace("Rs.", "")
    s = re.sub(r"\s*(cr|crores?|%|x|times)\.?\s*$", "", s, flags=re.I)
    if s.startswith("(") and s.endswith(")"):
        s = "-" + s[1:-1]
    try:
        return float(s)
    except:
        return None

# ─────────────────────────────────────────────────────────────────────────────
# Data Extraction Logic (Targeting "Data Sheet")
# ─────────────────────────────────────────────────────────────────────────────
def get_row_series(df, label_query):
    """Finds a row by label and returns a list of all numeric values (B column onwards)."""
    label_query = label_query.lower().strip()
    for r_idx in range(len(df)):
        cell_label = str(df.iloc[r_idx, 0]).lower().strip()
        if label_query in cell_label:
            # Extract row values, converting to float, filtering out non-numeric noise
            return [to_num(val) for val in df.iloc[r_idx, 1:] if to_num(val) is not None]
    return []

def parse_file(file):
    try:
        xl = pd.ExcelFile(file, engine="openpyxl")
        ds_name = next((s for s in xl.sheet_names if "data sheet" in s.lower()), None)
        if not ds_name:
            st.error("Sheet 'Data Sheet' not found.")
            return None
        df = pd.read_excel(xl, sheet_name=ds_name, header=None, dtype=str)
    except Exception as e:
        st.error(f"Excel Error: {e}")
        return None

    data = {}
    data["company_name"] = str(df.iloc[0, 1]).strip()
    
    # Static Metadata
    data["cmp"] = (get_row_series(df, "Current Price") or [None])[-1]
    data["market_cap"] = (get_row_series(df, "Market Capitalization") or [None])[-1]
    data["pe_5yr_avg"] = (get_row_series(df, "5 Year Avg PE") or [20.0])[-1]

    # Time Series Extraction (10 Years)
    data["sales_series"] = get_row_series(df, "Sales")
    data["pat_series"] = get_row_series(df, "Net Profit")
    data["cfo_series"] = get_row_series(df, "Cash from Operating Activity")
    
    # Raw components for ratios
    pat = data["pat_series"][-1] if data["pat_series"] else None
    cfo = data["cfo_series"][-1] if data["cfo_series"] else None
    eq_cap = (get_row_series(df, "Equity Share Capital") or [None])[-1]
    reserves = (get_row_series(df, "Reserves") or [None])[-1]
    borrowings = (get_row_series(df, "Borrowings") or [0.0])[-1]
    capex = (get_row_series(df, "Fixed assets purchased") or [0.0])[-1]

    # Ratio Computation
    try:
        total_equity = (eq_cap + reserves) if (eq_cap and reserves) else None
        data["roe"] = (pat / total_equity * 100) if (total_equity and pat) else None
        data["pe"] = (data["market_cap"] / pat) if (data["market_cap"] and pat and pat > 0) else None
        data["de"] = (borrowings / total_equity) if total_equity else 0.0
        data["cfo_pat"] = (cfo / pat) if (cfo and pat and pat != 0) else None
        data["fcf_val"] = (cfo - abs(capex)) if cfo is not None else None
        data["fcf_yield"] = (data["fcf_val"] / data["market_cap"] * 100) if (data.get("fcf_val") and data["market_cap"]) else 0.0
    except:
        pass

    return data

# ─────────────────────────────────────────────────────────────────────────────
# Streamlit Interface
# ─────────────────────────────────────────────────────────────────────────────
st.set_page_config(page_title="Master Stock Terminal", layout="wide")
st.title("🏦 Master Quantitative & Business Risk Evaluator")

uploaded_file = st.file_uploader("Upload 'Data Sheet' Excel", type="xlsx")

if uploaded_file:
    data = parse_file(uploaded_file)
    if data:
        st.header(f"🏢 {data.get('company_name')}")
        
        # 1. KPI Dashboard
        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("Current Price", f"₹{fmt(data.get('cmp'))}")
        m2.metric("ROE %", fmt(data.get('roe'), 1, "%"))
        m3.metric("P/E Ratio", fmt(data.get('pe'), 1))
        m4.metric("D/E Ratio", fmt(data.get('de'), 2))
        m5.metric("FCF Yield %", fmt(data.get('fcf_yield'), 1, "%"))

        st.markdown("---")

        # 2. Scorecard & Action Plan
        s1_pass = (data.get("roe") or 0) >= 15
        s2_pass = (data.get("cfo_pat") or 0) >= 0.8
        s3_pass = (data.get("pe") or 100) <= (data.get("pe_5yr_avg") or 20) * 1.1
        score = sum([s1_pass, s2_pass, s3_pass])

        st.subheader("🎯 Master Framework Scorecard")
        c1, c2, c3 = st.columns(3)
        c1.write(f"**Step 1: Quality (ROE)** — {'✅' if s1_pass else '❌'}")
        c2.write(f"**Step 2: Cash Realism** — {'✅' if s2_pass else '❌'}")
        c3.write(f"**Step 3: Valuation** — {'✅' if s3_pass else '❌'}")

        # 3. Visualization Section (New)
        st.markdown("---")
        st.subheader("📊 Historical Financial Trends")
        
        v1, v2 = st.columns(2)
        
        with v1:
            st.markdown("**Revenue vs. Net Profit Growth (10Y)**")
            if data.get("sales_series") and data.get("pat_series"):
                fig1 = go.Figure()
                fig1.add_trace(go.Scatter(y=data["sales_series"], name="Sales (Cr)", line=dict(color="#00CC96", width=3)))
                fig1.add_trace(go.Scatter(y=data["pat_series"], name="Net Profit (Cr)", line=dict(color="#636EFA", width=3)))
                fig1.update_layout(template="plotly_white", margin=dict(l=0, r=0, t=20, b=0), height=350, legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
                st.plotly_chart(fig1, use_container_width=True)
            else:
                st.info("Insufficient historical P&L data for line chart.")

        with v2:
            st.markdown("**Earnings Quality: Net Profit (PAT) vs. Cash Flow (CFO)**")
            if data.get("pat_series") and data.get("cfo_series"):
                # Align lengths just in case
                min_len = min(len(data["pat_series"]), len(data["cfo_series"]))
                pats = data["pat_series"][-min_len:]
                cfos = data["cfo_series"][-min_len:]
                
                fig2 = go.Figure()
                fig2.add_trace(go.Bar(y=pats, name="Net Profit (PAT)", marker_color="#636EFA"))
                fig2.add_trace(go.Bar(y=cfos, name="Cash from Ops (CFO)", marker_color="#FFA15A"))
                fig2.update_layout(barmode='group', template="plotly_white", margin=dict(l=0, r=0, t=20, b=0), height=350, legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
                st.plotly_chart(fig2, use_container_width=True)
            else:
                st.info("Insufficient historical Cash Flow data for bar chart.")

        # 4. Actionable Thesis Container
        st.markdown("---")
        with st.expander("💡 Comprehensive Investment Thesis & Action Plan", expanded=True):
            ta, tb, tc = st.columns(3)
            with ta:
                st.markdown("### 🎯 The Core Value Idea")
                if s1_pass and s2_pass:
                    st.write(f"High-conviction setup. The ROE of {fmt(data.get('roe'), 1)}% combined with high cash conversion ({fmt(data.get('cfo_pat'), 2)}x) suggests the company possesses a sustainable competitive advantage.")
                else:
                    st.write("Caution recommended. The disconnect between reported earnings and cash or returns suggests a weakening business model or aggressive accounting.")
            
            with tb:
                st.markdown("### ⚠️ Analytical Risks")
                if data.get("de", 0) > 0.5: st.warning(f"**Debt Exposure:** D/E of {data['de']:.2f} is high. Verify interest coverage ratios.")
                if (data.get("cfo_pat") or 1) < 0.8: st.warning("**Cash Lock-up:** CFO is lagging PAT. Check inventory days and receivables.")
                if not (data.get("de", 0) > 0.5 or (data.get("cfo_pat") or 1) < 0.8): st.success("No major quantitative red flags detected in leverage or cash cycles.")

            with tc:
                st.markdown("### 📋 Actionable Next Steps")
                st.write("1. **Verify Pledging:** Ensure 0% promoter pledging on Screener.in.")
                st.write("2. **Peer Check:** Compare current P/E to the nearest sector rival.")
                st.write("3. **Margin Trend:** Review if OPM % has been expanding or contracting over the charts above.")
