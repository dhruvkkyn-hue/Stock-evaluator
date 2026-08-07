import streamlit as st
import pandas as pd
import openpyxl
import io
import zipfile
import re
import plotly.express as px
import plotly.graph_objects as go
import traceback  # Required for enhanced debugging
from datetime import datetime

# ─────────────────────────────────────────────────────────────────────────────
# 1. UI/UX: INSTITUTIONAL CSS INJECTION
# ─────────────────────────────────────────────────────────────────────────────
st.set_page_config(page_title="Institutional Equity Terminal", layout="wide", page_icon="💎")

def inject_custom_css():
    st.markdown("""
    <style>
        :root {
            --bg-dark: #0e1117;
            --card-bg: #161b22;
            --border-color: #30363d;
            --text-main: #c9d1d9;
            --accent-emerald: #10b981;
        }
        .stApp { background-color: var(--bg-dark); color: var(--text-main); }
        div[data-testid="stMetric"] {
            background-color: var(--card-bg);
            border: 1px solid var(--border-color);
            padding: 15px;
            border-radius: 10px;
            box-shadow: 0 4px 6px rgba(0, 0, 0, 0.3);
        }
        h1, h2, h3 { color: #ffffff !important; font-family: 'Inter', sans-serif; }
        .hero-subtitle { color: #8b949e; font-size: 1.1rem; margin-bottom: 2rem; }
        .stTabs [data-baseweb="tab-list"] { gap: 8px; }
        .stTabs [data-baseweb="tab"] {
            background-color: var(--card-bg);
            border-radius: 4px 4px 0px 0px;
            padding: 10px 20px;
            color: var(--text-main);
        }
    </style>
    """, unsafe_allow_html=True)

inject_custom_css()

# ─────────────────────────────────────────────────────────────────────────────
# 2. QUANT ENGINE: SAFE MATH & HEURISTIC EXTRACTION
# ─────────────────────────────────────────────────────────────────────────────

def safe_float(val, default=0.0):
    if val is None: return default
    try:
        if isinstance(val, (int, float)): return float(val)
        s = str(val).replace(',', '').replace('₹', '').replace('Rs.', '').strip()
        if s.startswith('(') and s.endswith(')'): s = "-" + s[1:-1]
        return float(s)
    except: return default

def safe_div(n, d, default=0.0):
    try:
        n_f, d_f = float(n or 0), float(d or 0)
        return n_f / d_f if d_f != 0 else default
    except: return default

def calculate_cagr(series, years):
    if not series or len(series) < years + 1: return 0.0
    try:
        start_val = series[-(years + 1)]
        end_val = series[-1]
        if start_val <= 0 or end_val <= 0: return 0.0
        return ((end_val / start_val) ** (1 / years) - 1) * 100
    except: return 0.0

def find_row_series(ws, keywords):
    kw_lower = [k.lower() for k in keywords]
    for row in ws.iter_rows(min_row=1, max_row=ws.max_row, min_col=1, max_col=2):
        label = f"{str(row[0].value or '')} {str(row[1].value or '')}".lower()
        if any(k in label for k in kw_lower):
            row_idx = row[0].row
            return [safe_float(ws.cell(row=row_idx, column=c).value, None) 
                    for c in range(2, ws.max_column + 1) 
                    if ws.cell(row=row_idx, column=c).value is not None]
    return []

def process_workbook(file_bytes, filename):
    try:
        res = {} # Initialize cleanly
        wb = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True)
        ds_name = next((s for s in wb.sheetnames if "data sheet" in s.lower()), None)
        if not ds_name: return None, None
        ws = wb[ds_name]

        # Company Name Safeguard
        extracted_name = ws.cell(row=1, column=2).value
        res["Company"] = str(extracted_name).strip() if extracted_name else str(filename).replace(".xlsx", "")

        data_map = {
            "mcap": ["Market Capitalization", "Market Cap"],
            "sales": ["Sales", "Revenue"],
            "op": ["Operating Profit", "EBITDA"],
            "pat": ["Net Profit", "Profit after tax"],
            "pbt": ["Profit before tax", "PBT"],
            "interest": ["Interest", "Finance Costs"],
            "depr": ["Depreciation"],
            "debt": ["Borrowings", "Total Debt"],
            "equity": ["Equity Share Capital", "Share Capital"],
            "reserves": ["Reserves"],
            "cfo": ["Cash from Operating", "CFO"],
            "cfi": ["Cash from Investing", "CFI"],
            "cwip": ["Capital Work in Progress", "CWIP"],
            "net_block": ["Net Block", "Fixed Assets"],
            "liab": ["Other Liabilities"],
            "assets": ["Total Assets"],
            "receivables": ["Receivables", "Trade Receivables"],
            "inventory": ["Inventory"]
        }

        # 1. Extraction
        raw = {k: find_row_series(ws, v) for k, v in data_map.items()}
        curr = {k: (raw[k][-1] if raw[k] else 0.0) for k in raw}
        
        # 2. Intermediate Variables (Isolated from Dictionary)
        local_equity = curr['equity'] + curr['reserves']
        local_debt = curr['debt']
        local_assets = curr['assets'] if curr['assets'] else (local_equity + local_debt + curr['liab'])
        local_pat = curr['pat']
        local_cfo = curr['cfo']
        local_sales = curr['sales']
        local_mcap = curr['mcap']
        
        # 3. Calculations
        res["Market Cap"] = local_mcap
        res["Sales"] = local_sales
        res["Net Profit"] = local_pat
        res["OPM %"] = safe_div(curr['op'], local_sales) * 100
        res["PE"] = safe_div(local_mcap, local_pat)
        res["D/E"] = safe_div(local_debt, local_equity)
        res["ROCE %"] = safe_div(curr['pbt'] + curr['interest'], local_equity + local_debt) * 100
        res["Interest Coverage"] = safe_div(curr['pbt'] + curr['interest'], curr['interest'], default=999.0)
        res["FCF"] = local_cfo - abs(curr['cfi'])
        res["FCF Yield %"] = safe_div(res["FCF"], local_mcap) * 100
        res["CWIP to Net Block %"] = safe_div(curr['cwip'], curr['net_block']) * 100
        res["3Yr Sales CAGR %"] = calculate_cagr(raw['sales'], 3)
        res["3Yr PAT CAGR %"] = calculate_cagr(raw['pat'], 3)
        res["Sloan %"] = safe_div(local_pat - local_cfo, local_assets) * 100
        
        # 4. Altman Z-Score Calculation (Isolated)
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
        
        # 5. Piotroski Score Calculation (Isolated)
        p_score = 0
        if local_pat > 0: p_score += 1
        if local_cfo > 0: p_score += 1
        if local_cfo > local_pat: p_score += 1
        if res["3Yr PAT CAGR %"] > 0: p_score += 1
        
        # Leverage condition (Compare curr D/E vs Prev D/E)
        if len(raw['debt']) > 1 and len(raw['equity']) > 1 and len(raw['reserves']) > 1:
            prev_eq = raw['equity'][-2] + raw['reserves'][-2]
            prev_de = safe_div(raw['debt'][-2], prev_eq)
            if res["D/E"] < prev_de: p_score += 1
            
        if res["ROCE %"] > 15: p_score += 1
        if res["3Yr Sales CAGR %"] > 0: p_score += 1
        if local_assets > 0: p_score += 1
        res["Piotroski"] = p_score

        return res, file_bytes

    except Exception as e:
        # Enhanced Debugging with Traceback
        err_msg = f"Error in {filename}: {str(e)}\n{traceback.format_exc()}"
        st.error(err_msg)
        return None, None

# ─────────────────────────────────────────────────────────────────────────────
# 3. UI LAYOUT
# ─────────────────────────────────────────────────────────────────────────────

with st.sidebar:
    st.header("📂 Batch Ingestion")
    uploads = st.file_uploader("Upload Screener Excels", type="xlsx", accept_multiple_files=True)
    st.divider()
    st.caption(f"Terminal v2.6 | {datetime.now().year}")

st.title("🏛️ Institutional Research Terminal")
st.markdown("<p class='hero-subtitle'>Dynamic Quantitative Auditor</p>", unsafe_allow_html=True)

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
        tab1, tab2, tab3, tab4, tab5 = st.tabs(["📊 Matrix", "🕵️ Deep-Dive", "📈 Visuals", "🚨 Audit", "📄 Export"])

        with tab1:
            st.subheader("Institutional Comparison Grid")
            st.dataframe(df.style.format({
                "Market Cap": "₹{:,.0f}Cr", "Sales": "₹{:,.0f}Cr", "Net Profit": "₹{:,.0f}Cr",
                "ROCE %": "{:.1f}%", "PE": "{:.1f}x", "D/E": "{:.2f}", "3Yr Sales CAGR %": "{:.1f}%",
                "FCF Yield %": "{:.1f}%", "Altman Z": "{:.2f}", "Interest Coverage": "{:.1f}x"
            }).background_gradient(subset=["Piotroski"], cmap="RdYlGn"))

        with tab2:
            selection = st.multiselect("Select for Narrative Analysis:", df["Company"].unique(), default=df["Company"].unique()[:min(3, len(df))])
            if selection:
                subset = df[df["Company"].isin(selection)]
                for _, row in subset.iterrows():
                    with st.expander(f"Strategic Narrative: {row['Company']}", expanded=True):
                        c1, c2 = st.columns([1, 2])
                        c1.metric("Piotroski", f"{row['Piotroski']}/8")
                        c1.metric("ROCE", f"{row['ROCE %']:.1f}%")
                        c2.markdown(f"**Equity View:** {row['Company']} trades at {row['PE']:.1f}x PE with a FCF Yield of {row['FCF Yield %']:.1f}%. "
                                    f"Current leverage (D/E) is {row['D/E']:.2f}. "
                                    f"Health zone is currently classified as **{row['Zone']}**.")

        with tab3:
            c1, c2 = st.columns(2)
            with c1:
                fig1 = px.scatter(df, x="PE", y="OPM %", size="Market Cap", color="Zone",
                                 hover_name="Company", title="PE vs. Operating Margin",
                                 color_discrete_map={"Safe": "#10b981", "Grey": "#fbbf24", "Distress": "#ef4444"})
                st.plotly_chart(fig1, use_container_width=True)
            with c2:
                fig2 = go.Figure(data=[
                    go.Bar(name='Piotroski', x=df['Company'], y=df['Piotroski'], marker_color='#10b981'),
                    go.Bar(name='Altman Z', x=df['Company'], y=df['Altman Z'], marker_color='#3b82f6')
                ])
                fig2.update_layout(title="Quality vs. Solvency", barmode='group', template="plotly_dark")
                st.plotly_chart(fig2, use_container_width=True)

        with tab4:
            st.subheader("🚨 Automated Risk Auditor")
            for _, row in df.iterrows():
                st.write(f"### {row['Company']}")
                cols = st.columns(4)
                if row['Net Profit'] > 0 and row['FCF'] < 0:
                    cols[0].error("⚠️ Cash Conversion\nNegative FCF despite PAT.")
                else: cols[0].success("✅ Cash Flow OK")

                if row['D/E'] > 1.2 and row['Interest Coverage'] < 2.5:
                    cols[1].error("⚠️ Solvency Risk\nHigh Debt / Low Coverage.")
                else: cols[1].success("✅ Solvency OK")

                if row['Sloan %'] > 10:
                    cols[2].warning("⚠️ Accrual Risk\nSloan Ratio > 10%.")
                else: cols[2].success("✅ Accruals OK")

                if row['CWIP to Net Block %'] > 40:
                    cols[3].warning("⚠️ Execution Risk\nExtreme CWIP Level.")
                else: cols[3].success("✅ Asset Health OK")
                st.divider()

        with tab5:
            report = "# Institutional Summary Report\n\n"
            for _, row in df.iterrows():
                report += f"## {row['Company']}\n- Score: {row['Piotroski']}/8 | Health: {row['Zone']}\n- ROCE: {row['ROCE %']:.1f}% | PE: {row['PE']:.1f}x\n\n"
            st.download_button("📥 Download Report (.md)", data=report, file_name="Terminal_Report.md")
            
            zip_io = io.BytesIO()
            with zipfile.ZipFile(zip_io, 'w') as zf:
                for fname, content in raw_files: zf.writestr(f"Processed_{fname}", content)
            st.download_button("📥 Download ZIP Package", data=zip_io.getvalue(), file_name="Research_Batch.zip")
else:
    st.info("👋 Upload Screener.in Excel exports to begin analysis.")

