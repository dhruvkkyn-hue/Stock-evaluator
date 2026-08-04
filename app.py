import streamlit as st
import pandas as pd
import openpyxl
import io
import zipfile
import re
import plotly.express as px
import plotly.graph_objects as go

# ─────────────────────────────────────────────────────────────────────────────
# 1. CORE CONFIGURATION & HELPERS
# ─────────────────────────────────────────────────────────────────────────────
st.set_page_config(page_title="Quant-Fundamental Terminal", layout="wide", page_icon="⚖️")

def safe_div(n, d):
    """Prevents ZeroDivisionError and handles None values."""
    try:
        n = float(n) if n is not None else 0.0
        d = float(d) if d is not None else 0.0
        return n / d if d != 0 else 0.0
    except (ValueError, TypeError):
        return 0.0

def safe_float(v):
    """Safely converts Excel cell values to float."""
    if v is None: return 0.0
    try:
        if isinstance(v, str):
            v = v.replace(',', '').replace('₹', '').strip()
            if '(' in v and ')' in v: # Handle accounting negatives
                v = "-" + v.replace('(', '').replace(')', '')
        return float(v)
    except (ValueError, TypeError):
        return 0.0

def find_row_series(ws, keywords):
    """Searches Column A for keywords and returns the full numeric series."""
    for row in ws.iter_rows(min_col=1, max_col=1):
        label = str(row[0].value).lower() if row[0].value else ""
        if any(k.lower() in label for k in keywords):
            # Extract numeric values from columns 2 to max
            series = [safe_float(ws.cell(row=row[0].row, column=c).value) 
                      for c in range(2, ws.max_column + 1)]
            # Filter out trailing zeros/empty columns if necessary, but keep the series
            return [x for x in series if x is not None]
    return []

# ─────────────────────────────────────────────────────────────────────────────
# 2. DATA EXTRACTION & QUANT ENGINE
# ─────────────────────────────────────────────────────────────────────────────

def process_workbook(file_bytes, filename):
    try:
        wb = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True)
        ds_name = next((s for s in wb.sheetnames if "data sheet" in s.lower()), None)
        if not ds_name: return None
        ws = wb[ds_name]

        # Dynamic Extraction Map
        extract = {
            "mcap": find_row_series(ws, ["Market Capitalization", "Market Cap", "Mar Cap"]),
            "sales": find_row_series(ws, ["Sales", "Revenue"]),
            "op": find_row_series(ws, ["Operating Profit", "EBITDA", "EBIT", "Operating Profit / (Loss)"]),
            "pat": find_row_series(ws, ["Net Profit", "Profit after tax", "PAT"]),
            "debt": find_row_series(ws, ["Borrowings", "Total Debt", "Long term borrowings"]),
            "liab": find_row_series(ws, ["Other Liabilities", "Current Liabilities"]),
            "reserves": find_row_series(ws, ["Reserves", "Retained Earnings"]),
            "equity": find_row_series(ws, ["Equity Share Capital", "Share Capital"]),
            "cfo": find_row_series(ws, ["Cash from Operating", "Operating Cash Flow", "CFO"]),
            "receivables": find_row_series(ws, ["Receivables", "Trade Receivables"]),
            "inventory": find_row_series(ws, ["Inventory", "Stock"]),
            "cash": find_row_series(ws, ["Cash & Bank", "Cash Equivalents"]),
            "interest": find_row_series(ws, ["Interest", "Finance Costs"])
        }

        # Select latest and previous for YoY calculations
        def get_last(key): return extract[key][-1] if extract[key] else 0.0
        def get_prev(key): return extract[key][-2] if len(extract[key]) > 1 else get_last(key)

        curr = {k: get_last(k) for k in extract}
        prev = {k: get_prev(k) for k in extract}
        
        # Total Assets Proxy (Equity + Reserves + Debt + Other Liab)
        total_assets = curr['equity'] + curr['reserves'] + curr['debt'] + curr['liab']
        prev_assets = prev['equity'] + prev['reserves'] + prev['debt'] + prev['liab']

        # ── Quantitative Metrics ──
        res = {"Company": str(ws.cell(row=1, column=2).value).strip()}
        res["Market Cap (Cr)"] = curr['mcap']
        res["Sales (Cr)"] = curr['sales']
        res["Net Profit (Cr)"] = curr['pat']
        res["CFO (Cr)"] = curr['cfo']
        res["OPM %"] = safe_div(curr['op'], curr['sales']) * 100
        res["PE"] = safe_div(curr['mcap'], curr['pat'])
        res["EV/EBITDA"] = safe_div(curr['mcap'] + curr['debt'] - curr['cash'], curr['op'])
        res["Debt/Equity"] = safe_div(curr['debt'], curr['equity'] + curr['reserves'])
        res["Interest Coverage"] = safe_div(curr['op'], curr['interest'])
        
        # Sloan Accrual
        res["Sloan %"] = safe_div(curr['pat'] - curr['cfo'], total_assets) * 100

        # Altman Z-Score (Standardized for General Corp)
        x1 = safe_div((curr['receivables'] + curr['inventory'] + curr['cash']) - curr['liab'], total_assets)
        x2 = safe_div(curr['reserves'], total_assets)
        x3 = safe_div(curr['op'], total_assets)
        x4 = safe_div(curr['mcap'], curr['debt'] + curr['liab'])
        x5 = safe_div(curr['sales'], total_assets)
        res["Altman Z"] = (1.2 * x1) + (1.4 * x2) + (3.3 * x3) + (0.6 * x4) + (0.99 * x5)
        
        if res["Altman Z"] > 2.99: res["Zone"] = "Safe"
        elif res["Altman Z"] >= 1.81: res["Zone"] = "Grey"
        else: res["Zone"] = "Distress"

        # Piotroski F-Score (8-Point)
        f = 0
        if curr['pat'] > 0: f += 1
        if curr['cfo'] > 0: f += 1
        if curr['cfo'] > curr['pat']: f += 1
        if safe_div(curr['pat'], total_assets) > safe_div(prev['pat'], prev_assets): f += 1
        if curr['debt'] <= prev['debt']: f += 1
        if safe_div(curr['op'], curr['sales']) > safe_div(prev['op'], prev['sales']): f += 1
        if curr['sales'] > prev['sales']: f += 1
        if total_assets > 0: f += 1
        res["Piotroski"] = f

        return res, file_bytes
    except Exception as e:
        st.error(f"Error processing {filename}: {e}")
        return None, None

# ─────────────────────────────────────────────────────────────────────────────
# 3. UI & DASHBOARD
# ─────────────────────────────────────────────────────────────────────────────

st.title("🏛️ Institutional Quant-Fundamental Terminal")
st.sidebar.header("Data Ingestion")
uploads = st.sidebar.file_uploader("Upload Screener Excels", type="xlsx", accept_multiple_files=True)

if uploads:
    all_data = []
    processed_files = []
    
    for up in uploads:
        data, b_content = process_workbook(up.getvalue(), up.name)
        if data:
            all_data.append(data)
            processed_files.append((up.name, b_content))
    
    if all_data:
        df = pd.DataFrame(all_data)
        
        # --- TOP LEVEL DASHBOARD ---
        col1, col2 = st.columns([2, 1])
        
        with col1:
            st.subheader("📊 Fundamental Scoring Comparison")
            # Piotroski Chart color coded by Altman
            color_map = {"Safe": "#2ecc71", "Grey": "#f39c12", "Distress": "#e74c3c"}
            fig = px.bar(df, x="Company", y="Piotroski", color="Zone",
                         color_discrete_map=color_map, 
                         title="Piotroski F-Score by Financial Health Zone",
                         text_auto=True)
            st.plotly_chart(fig, use_container_width=True)

        with col2:
            st.subheader("📦 Batch Export")
            zip_io = io.BytesIO()
            with zipfile.ZipFile(zip_io, 'w') as zf:
                for fname, content in processed_files:
                    zf.writestr(f"Processed_{fname}", content)
            
            st.download_button("Download All Processed Files (.zip)", 
                             data=zip_io.getvalue(), 
                             file_name="Quant_Batch_Export.zip", 
                             mime="application/zip")

        # --- DATA TABLE ---
        st.subheader("📋 Detailed Quantitative Readout")
        st.dataframe(df.style.format({
            "Market Cap (Cr)": "₹{:,.0f}",
            "Sales (Cr)": "₹{:,.0f}",
            "Net Profit (Cr)": "₹{:,.0f}",
            "OPM %": "{:.1f}%",
            "PE": "{:.1f}x",
            "EV/EBITDA": "{:.1f}x",
            "Debt/Equity": "{:.2f}",
            "Interest Coverage": "{:.2f}",
            "Altman Z": "{:.2f}",
            "Sloan %": "{:.2f}%"
        }))

        # ─────────────────────────────────────────────────────────────────────
        # 4. QUALITATIVE ANALYSIS ENGINE
        # ─────────────────────────────────────────────────────────────────────
        st.divider()
        st.header("🕵️ Comparative Strategic Deep-Dive")
        
        c_sel1, c_sel2 = st.columns(2)
        stock_a_name = c_sel1.selectbox("Select Benchmark (Stock A)", df["Company"].unique(), index=0)
        stock_b_name = c_sel2.selectbox("Select Comparison (Stock B)", df["Company"].unique(), index=min(1, len(df)-1))
        
        a = df[df["Company"] == stock_a_name].iloc[0]
        b = df[df["Company"] == stock_b_name].iloc[0]

        # --- A. EXECUTIVE SNAPSHOT ---
        st.subheader("1. Executive Snapshot")
        safety_winner = stock_a_name if (a['Piotroski'] + a['Altman Z']) > (b['Piotroski'] + b['Altman Z']) else stock_b_name
        value_winner = stock_a_name if (a['PE'] > 0 and a['PE'] < b['PE']) or (b['PE'] <= 0) else stock_b_name
        
        snap1, snap2 = st.columns(2)
        snap1.metric("Financial Safety Leader", safety_winner)
        snap2.metric("Earnings Valuation Leader", value_winner)

        # --- B. DETAILED BREAKDOWN ---
        st.subheader("2. Detailed Quantitative Interpretation")
        
        tab1, tab2, tab3 = st.tabs(["Scale & Pricing Power", "Accounting Quality", "Solvency Risk"])
        
        with tab1:
            st.write(f"**Scale & Valuation:** {stock_a_name} operates at a Market Cap of ₹{a['Market Cap (Cr)']:,.0f} Cr with an OPM of {a['OPM %']:.1f}%, while {stock_b_name} maintains ₹{b['Market Cap (Cr)']:,.0f} Cr at {b['OPM %']:.1f}% margin.")
            st.write(f"**Interpretation:** A higher Operating Margin (OPM) suggests {'Stock A' if a['OPM %'] > b['OPM %'] else 'Stock B'} has superior pricing power and structural cost advantages in its supply chain.")
            
        with tab2:
            st.write(f"**Sloan Accrual Analysis:** {stock_a_name} Sloan: {a['Sloan %']:.2f}% | {stock_b_name} Sloan: {b['Sloan %']:.2f}%")
            for stock, name in [(a, stock_a_name), (b, stock_b_name)]:
                if abs(stock['Sloan %']) < 10:
                    st.write(f"✅ **{name}:** High-quality earnings. Profits are effectively backed by CFO.")
                else:
                    st.write(f"🚩 **{name}:** Aggressive accruals. High risk that non-cash items are inflating PAT.")
                    
        with tab3:
            st.write(f"**Risk Profile:** {stock_a_name} is in the **{a['Zone']}** Zone (Z: {a['Altman Z']:.2f}), compared to {stock_b_name} in the **{b['Zone']}** Zone (Z: {b['Altman Z']:.2f}).")
            st.write(f"**Leverage:** {stock_a_name} has a Debt/Equity of {a['Debt/Equity']:.2f} and an Interest Coverage of {a['Interest Coverage']:.2f}.")

        # --- C. PROS & CONS ---
        st.subheader("3. Institutional Strengths & Constraints")
        pc1, pc2 = st.columns(2)
        
        for stock, col, name in [(a, pc1, stock_a_name), (b, pc2, stock_b_name)]:
            with col:
                st.markdown(f"**{name}**")
                # Strengths
                if stock['Piotroski'] >= 7: st.markdown("- 🟢 Strong operational momentum (F-Score 7+)")
                if stock['Altman Z'] > 2.99: st.markdown("- 🟢 Fortress balance sheet (Safe Zone)")
                if stock['Interest Coverage'] > 5: st.markdown("- 🟢 Robust interest coverage")
                if stock['Sloan %'] < 5: st.markdown("- 🟢 Excellent cash conversion quality")
                
                # Weaknesses
                if stock['Debt/Equity'] > 1: st.markdown("- 🔴 High financial leverage (>1.0 D/E)")
                if stock['PE'] > 50: st.markdown("- 🔴 Aggressive valuation (>50x PE)")
                if stock['Altman Z'] < 1.81: st.markdown("- 🔴 Potential solvency distress signals")
                if stock['OPM %'] < 10: st.markdown("- 🔴 Thin margins; vulnerable to cost spikes")

        # --- D. DECISION MATRIX ---
        st.subheader("4. Multi-Scenario Decision Matrix")
        m1, m2 = st.columns(2)
        
        with m1:
            st.markdown(f"#### 🏆 Favor {stock_a_name} Over {stock_b_name} IF:")
            if a['PE'] < b['PE'] and a['PE'] > 0: st.write("- You prioritize **Margin of Safety** and lower entry multiples.")
            if a['Sloan %'] < b['Sloan %']: st.write("- You demand **Clean Accounting** and higher cash flow conversion.")
            if a['Altman Z'] > b['Altman Z']: st.write("- You seek a **Defensive Fortress** during economic uncertainty.")
            
        with m2:
            st.markdown(f"#### 🏆 Favor {stock_b_name} Over {stock_a_name} IF:")
            if b['OPM %'] > a['OPM %']: st.write("- You are backing **Pricing Power** and dominant market leadership.")
            if b['Piotroski'] > a['Piotroski']: st.write("- You follow **Operational Momentum** and internal efficiency trends.")
            if b['Debt/Equity'] < a['Debt/Equity']: st.write("- You are cautious about **Interest Rate Tightening** cycles.")

        st.warning(f"**⚠️ Thesis Inversion Triggers:** An inversion of this thesis would occur if interest rates spike (harming {stock_a_name if a['Debt/Equity'] > b['Debt/Equity'] else stock_b_name} more) or if industry OPMs contract by 5% (harming {stock_a_name if a['OPM %'] < b['OPM %'] else stock_b_name} more).")

else:
    st.info("👋 Welcome. Please upload one or more Screener.in Excel exports to generate the Institutional Terminal.")
