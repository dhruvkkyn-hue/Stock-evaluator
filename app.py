import streamlit as st
import pandas as pd
import openpyxl
import io
import zipfile
import re
import plotly.express as px
import json

# ─────────────────────────────────────────────────────────────────────────────
# 1. CORE CONFIGURATION & SAFE MATH
# ─────────────────────────────────────────────────────────────────────────────
st.set_page_config(page_title="Institutional Quant Terminal", layout="wide", page_icon="⚖️")

def safe_float(val, default=0.0):
    """Robust conversion of Excel cells to float, handling currency and accounting parens."""
    if val is None: return default
    try:
        if isinstance(val, (int, float)): return float(val)
        s = str(val).replace(',', '').replace('₹', '').replace('Rs.', '').strip()
        if s.startswith('(') and s.endswith(')'):
            s = "-" + s[1:-1]
        return float(s)
    except (ValueError, TypeError):
        return default

def safe_div(n, d, default=0.0):
    """Prevents ZeroDivisionError."""
    try:
        n_f, d_f = float(n or 0), float(d or 0)
        return n_f / d_f if d_f != 0 else default
    except:
        return default

# ─────────────────────────────────────────────────────────────────────────────
# 2. HEURISTIC DATA EXTRACTION ENGINE
# ─────────────────────────────────────────────────────────────────────────────

def find_row_series(ws, keywords):
    """
    Scans Column A and B for labels. 
    Returns the full list of numeric values found in that row across columns.
    """
    kw_lower = [k.lower() for k in keywords]
    
    for row in ws.iter_rows(min_row=1, max_row=ws.max_row, min_col=1, max_col=2):
        label_a = str(row[0].value or "").strip().lower()
        label_b = str(row[1].value or "").strip().lower()
        combined = f"{label_a} {label_b}"
        
        if any(k in combined for k in kw_lower):
            row_idx = row[0].row
            # Extract all numeric values across the row starting from column 2
            vals = []
            for col_idx in range(2, ws.max_column + 1):
                val = safe_float(ws.cell(row=row_idx, column=col_idx).value, None)
                if val is not None:
                    vals.append(val)
            return vals
    return []

def get_latest(series, default=0.0):
    return series[-1] if series else default

def get_prev(series, default=0.0):
    return series[-2] if len(series) > 1 else get_latest(series, default)

# ─────────────────────────────────────────────────────────────────────────────
# 3. PROCESSING WORKFLOW
# ─────────────────────────────────────────────────────────────────────────────

def process_workbook(file_bytes, filename):
    try:
        # data_only=True is critical to read the results of formulas saved by Screener
        wb = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True)
        ds_name = next((s for s in wb.sheetnames if "data sheet" in s.lower()), None)
        if not ds_name: return None, None
        ws = wb[ds_name]

        # --- KEYWORD DICTIONARY MAPPING ---
        data_map = {
            "mcap": find_row_series(ws, ["Market Capitalization", "Market Cap", "Mar Cap", "Current Market", "CMP"]),
            "sales": find_row_series(ws, ["Sales", "Revenue", "Total Revenue", "Interest Earned", "Income"]),
            "op": find_row_series(ws, ["Operating Profit", "EBITDA", "EBIT", "Operating Loss", "Financing Profit"]),
            "pat": find_row_series(ws, ["Net Profit", "Profit after tax", "PAT", "PAT for the year"]),
            "debt": find_row_series(ws, ["Borrowings", "Total Debt", "Long term borrowings", "Short term borrowings"]),
            "liab": find_row_series(ws, ["Other Liabilities", "Current Liabilities", "Total Liabilities"]),
            "reserves": find_row_series(ws, ["Reserves", "Retained Earnings", "Other Equity"]),
            "equity": find_row_series(ws, ["Equity Share Capital", "Share Capital", "Equity Capital"]),
            "cfo": find_row_series(ws, ["Cash from Operating", "Operating Cash Flow", "CFO", "Cash flow from operations"]),
            "receivables": find_row_series(ws, ["Receivables", "Trade Receivables", "Sundry Debtors"]),
            "inventory": find_row_series(ws, ["Inventory", "Stock", "Inventories"]),
            "cash": find_row_series(ws, ["Cash & Bank", "Cash Equivalents", "Bank Balance"]),
            "interest": find_row_series(ws, ["Interest", "Finance Costs", "Interest Expensed"])
        }

        # Latest Year Snapshot
        cur = {k: get_latest(v) for k, v in data_map.items()}
        # Previous Year (for YoY Momentum)
        pre = {k: get_prev(v) for k, v in data_map.items()}

        total_eq = cur['equity'] + cur['reserves']
        total_assets = total_eq + cur['debt'] + cur['liab']
        prev_assets = (pre['equity'] + pre['reserves'] + pre['debt'] + pre['liab']) or total_assets

        # ── Quantitative Ratios ──
        res = {"Company": str(ws.cell(row=1, column=2).value).strip()}
        res["Market Cap (Cr)"] = cur['mcap']
        res["Sales (Cr)"] = cur['sales']
        res["Net Profit (Cr)"] = cur['pat']
        res["CFO (Cr)"] = cur['cfo']
        res["OPM %"] = safe_div(cur['op'], cur['sales']) * 100
        res["P/E"] = safe_div(cur['mcap'], cur['pat'])
        res["D/E"] = safe_div(cur['debt'], total_eq)
        res["Sloan %"] = safe_div(cur['pat'] - cur['cfo'], total_assets) * 100
        res["EV/EBITDA"] = safe_div(cur['mcap'] + cur['debt'] - cur['cash'], cur['op'])
        
        # Altman Z-Score Proxy
        x1 = safe_div((cur['receivables'] + cur['inventory'] + cur['cash']) - cur['liab'], total_assets)
        x2 = safe_div(cur['reserves'], total_assets)
        x3 = safe_div(cur['op'], total_assets)
        x4 = safe_div(cur['mcap'], cur['debt'] + cur['liab'])
        x5 = safe_div(cur['sales'], total_assets)
        res["Altman Z"] = (1.2 * x1) + (1.4 * x2) + (3.3 * x3) + (0.6 * x4) + (0.99 * x5)
        res["Zone"] = "Safe" if res["Altman Z"] > 2.99 else "Grey" if res["Altman Z"] >= 1.81 else "Distress"

        # Piotroski F-Score (8-Point)
        f = 0
        if cur['pat'] > 0: f += 1
        if cur['cfo'] > 0: f += 1
        if cur['cfo'] > cur['pat']: f += 1
        if safe_div(cur['pat'], total_assets) > safe_div(pre['pat'], prev_assets): f += 1
        if cur['debt'] <= pre['debt']: f += 1
        if safe_div(cur['op'], cur['sales']) > safe_div(pre['op'], pre['sales']): f += 1
        if cur['sales'] > pre['sales']: f += 1
        if total_assets > 0: f += 1
        res["Piotroski"] = f

        return res, file_bytes
    except Exception as e:
        st.error(f"Error parsing {filename}: {str(e)}")
        return None, None

# ─────────────────────────────────────────────────────────────────────────────
# 4. DASHBOARD UI
# ─────────────────────────────────────────────────────────────────────────────

st.title("🏛️ Institutional Quant Terminal")
st.sidebar.header("Batch Ingestion")
up_files = st.sidebar.file_uploader("Upload Screener Excels", type="xlsx", accept_multiple_files=True)

if up_files:
    results = []
    zip_bytes = io.BytesIO()
    
    with zipfile.ZipFile(zip_bytes, 'w') as zf:
        for f in up_files:
            data, b_content = process_workbook(f.getvalue(), f.name)
            if data:
                results.append(data)
                zf.writestr(f"Processed_{f.name}", b_content)

    if results:
        df = pd.DataFrame(results)
        
        # --- Summary Viz ---
        c1, c2 = st.columns([2,1])
        with c1:
            st.subheader("📊 Piotroski Momentum & Health Zone")
            fig = px.bar(df, x="Company", y="Piotroski", color="Zone",
                         color_discrete_map={"Safe": "#2ecc71", "Grey": "#f39c12", "Distress": "#e74c3c"},
                         text_auto=True)
            st.plotly_chart(fig, use_container_width=True)
        with c2:
            st.subheader("📥 Export")
            st.download_button("Download ZIP Package", zip_bytes.getvalue(), "Quant_Batch.zip", "application/zip")

        # --- Master Table ---
        st.subheader("📋 Master Quant Comparison")
        st.dataframe(df.style.format({
            "Market Cap (Cr)": "₹{:,.0f}", "Sales (Cr)": "₹{:,.0f}", "Net Profit (Cr)": "₹{:,.0f}",
            "P/E": "{:.1f}x", "D/E": "{:.2f}", "Sloan %": "{:.2f}%", "Altman Z": "{:.2f}", "OPM %": "{:.1f}%"
        }).background_gradient(subset=["Piotroski"], cmap="RdYlGn"))

        # ─────────────────────────────────────────────────────────────────────
        # 5. ENGLISH COMPARISON ENGINE
        # ─────────────────────────────────────────────────────────────────────
        st.divider()
        st.header("🕵️ Comparative Strategic Deep-Dive")
        
        sel_col1, sel_col2 = st.columns(2)
        sa_name = sel_col1.selectbox("Benchmark Stock (A)", df["Company"].unique(), index=0)
        sb_name = sel_col2.selectbox("Comparison Stock (B)", df["Company"].unique(), index=min(1, len(df)-1))
        
        A = df[df["Company"] == sa_name].iloc[0]
        B = df[df["Company"] == sb_name].iloc[0]

        # --- A. Snapshot ---
        st.subheader("1. Head-to-Head Summary")
        safest = sa_name if (A['Piotroski'] + A['Altman Z']) > (B['Piotroski'] + B['Altman Z']) else sb_name
        cheapest = sa_name if (0 < A['P/E'] < B['P/E']) or (B['P/E'] <= 0) else sb_name
        
        sn1, sn2 = st.columns(2)
        sn1.metric("Financial Health Leader", safest)
        sn2.metric("Valuation Lead (P/E)", cheapest)

        # --- B. Metric Logic ---
        st.subheader("2. Detailed Qualitative Breakdown")
        t1, t2, t3 = st.tabs(["Operational Momentum", "Insolvency Risk", "Earnings Quality"])
        
        with t1:
            st.write(f"**Piotroski Score:** {sa_name} ({A['Piotroski']}/8) vs {sb_name} ({B['Piotroski']}/8)")
            st.write(f"A higher score indicates superior internal management and consistent YoY improvements in profitability and leverage.")
        
        with t2:
            st.write(f"**Altman Z Risk:** {sa_name} is in the **{A['Zone']}** Zone (Z: {A['Altman Z']:.2f}). {sb_name} is in the **{B['Zone']}** Zone (Z: {B['Altman Z']:.2f}).")
            st.caption("Safe > 2.99 | Grey 1.8-2.9 | Distress < 1.8. Low scores signal potential bankruptcy risk.")

        with t3:
            st.write(f"**Sloan Accrual Ratio:** {sa_name} ({A['Sloan %']:.1f}%) | {sb_name} ({B['Sloan %']:.1f}%)")
            st.write("A Sloan ratio under 10% indicates 'Clean' accounting where profits are backed by actual cash flow. Values above 10% suggest 'Paper Profits' driven by non-cash accruals.")

        # --- C. Pros & Cons ---
        st.subheader("3. Institutional Strengths & Weaknesses")
        pa, pb = st.columns(2)
        for stock, col in [(A, pa), (B, pb)]:
            with col:
                st.markdown(f"**{stock['Company']}**")
                # Strengths
                if stock['Piotroski'] >= 7: st.markdown("- 🟢 Top-tier operational efficiency.")
                if stock['Altman Z'] > 2.99: st.markdown("- 🟢 Balance sheet is a defensive fortress.")
                if stock['D/E'] < 0.3: st.markdown("- 🟢 Virtually no debt risk.")
                if abs(stock['Sloan %']) < 5: st.markdown("- 🟢 High-quality cash-backed earnings.")
                # Weaknesses
                if stock['P/E'] > 50: st.markdown("- 🔴 Aggressive valuation; zero margin of safety.")
                if stock['D/E'] > 1.2: st.markdown("- 🔴 High leverage; sensitive to interest rates.")
                if stock['Zone'] == "Distress": st.markdown("- 🔴 Critical insolvency warning signals.")

        # --- D. Framework ---
        st.subheader("4. Strategic Decision Matrix")
        f1, f2 = st.columns(2)
        with f1:
            st.markdown(f"#### 🏆 Favor {sa_name} if:")
            if A['P/E'] < B['P/E']: st.write("- You prioritize lower entry multiples and value.")
            if A['Altman Z'] > B['Altman Z']: st.write("- You are building a defensive portfolio.")
        with f2:
            st.markdown(f"#### 🏆 Favor {sb_name} if:")
            if B['OPM %'] > A['OPM %']: st.write("- You are backing superior pricing power and market dominance.")
            if B['Piotroski'] > A['Piotroski']: st.write("- You prefer stocks with accelerating operational momentum.")

        st.warning(f"**Macro Inversion:** A sharp rise in interest rates will penalize **{sa_name if A['D/E'] > B['D/E'] else sb_name}** more significantly due to their debt profile.")
else:
    st.info("👋 Welcome. Upload Screener.in Excel files to begin analysis.")
