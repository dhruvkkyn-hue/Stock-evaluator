import streamlit as st
import pandas as pd
import openpyxl
import io
import zipfile
import re
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime

# ─────────────────────────────────────────────────────────────────────────────
# 1. UI/UX: INSTITUTIONAL CSS INJECTION
# ─────────────────────────────────────────────────────────────────────────────
st.set_page_config(page_title="Institutional Equity Terminal", layout="wide", page_icon="💎")

def inject_custom_css():
    st.markdown("""
    <style>
        /* Main Theme Colors */
        :root {
            --bg-dark: #0e1117;
            --card-bg: #161b22;
            --border-color: #30363d;
            --text-main: #c9d1d9;
            --accent-emerald: #10b981;
        }

        .stApp { background-color: var(--bg-dark); color: var(--text-main); }
        
        /* Metric Card Styling */
        div[data-testid="stMetric"] {
            background-color: var(--card-bg);
            border: 1px solid var(--border-color);
            padding: 15px;
            border-radius: 10px;
            box-shadow: 0 4px 6px rgba(0, 0, 0, 0.3);
        }
        
        /* Custom Badges */
        .badge {
            padding: 4px 12px;
            border-radius: 20px;
            font-weight: 600;
            font-size: 0.85rem;
            display: inline-block;
        }
        .badge-safe { background-color: #1b4332; color: #70e000; border: 1px solid #2d6a4f; }
        .badge-grey { background-color: #3d2e00; color: #ffb703; border: 1px solid #5c4500; }
        .badge-distress { background-color: #4a0e17; color: #ff4d6d; border: 1px solid #800f2f; }
        
        /* Headers */
        h1, h2, h3 { color: #ffffff !important; font-family: 'Inter', sans-serif; }
        .hero-subtitle { color: #8b949e; font-size: 1.1rem; margin-bottom: 2rem; }
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
    if len(series) < years + 1: return 0.0
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
            return [safe_float(ws.cell(row=row_idx, column=c).value, None) for c in range(2, ws.max_column + 1) if ws.cell(row=row_idx, column=c).value is not None]
    return []

def process_workbook(file_bytes, filename):
    try:
        wb = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True)
        ds_name = next((s for s in wb.sheetnames if "data sheet" in s.lower()), None)
        if not ds_name: return None
        ws = wb[ds_name]

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

        raw = {k: find_row_series(ws, v) for k, v in data_map.items()}
        curr = {k: (raw[k][-1] if raw[k] else 0.0) for k in raw}
        
        # ── CORE CALCULATIONS ──
        total_eq = curr['equity'] + curr['reserves']
        total_debt = curr['debt']
        total_assets = curr['assets'] if curr['assets'] else (total_eq + total_debt + curr['liab'])
        
        res = {"Company": str(ws.cell(row=1, column=2).value).strip()}
        res["Market Cap"] = curr['mcap']
        res["Sales"] = curr['sales']
        res["Net Profit"] = curr['pat']
        res["OPM %"] = safe_div(curr['op'], curr['sales']) * 100
        res["PE"] = safe_div(curr['mcap'], curr['pat'])
        res["D/E"] = safe_div(total_debt, total_eq)
        
        # New Metrics
        res["ROCE %"] = safe_div(curr['pbt'] + curr['interest'], total_eq + total_debt) * 100
        res["Interest Coverage"] = safe_div(curr['pbt'] + curr['interest'], curr['interest'], default=999.0)
        res["FCF"] = curr['cfo'] - abs(curr['cfi'])
        res["FCF Yield %"] = safe_div(res["FCF"], curr['mcap']) * 100
        res["CWIP to Net Block %"] = safe_div(curr['cwip'], curr['net_block']) * 100
        res["3Yr Sales CAGR %"] = calculate_cagr(raw['sales'], 3)
        res["3Yr PAT CAGR %"] = calculate_cagr(raw['pat'], 3)
        res["Sloan %"] = safe_div(curr['pat'] - curr['cfo'], total_assets) * 100
        
        # Health Scores
        x1 = safe_div((curr['receivables'] + curr['inventory'] + (total_assets * 0.05)) - curr['liab'], total_assets) # 0.05 is cash proxy
        res["Altman Z"] = (1.2 * x1) + (1.4 * safe_div(curr['reserves'], total_assets)) + (3.3 * safe_div(curr['op'], total_assets)) + (0.6 * safe_div(curr['mcap'], total_debt + curr['liab'])) + (0.99 * safe_div(curr['sales'], total_assets))
        res["Zone"] = "Safe" if res["Altman Z"] > 2.99 else "Grey" if res["Altman Z"] >= 1.81 else "Distress"
        
        f = 0
        if curr['pat'] > 0: f += 1
        if curr['cfo'] > 0: f += 1
        if curr['cfo'] > curr['pat']: f += 1
        if res["3Yr PAT CAGR %"] > 0: f += 1
        if res["D/E"] < (safe_div(raw['debt'][-2], (raw['equity'][-2] + raw['res'][-2])) if len(raw['debt']) > 1 else 1): f += 1
        if res["ROCE %"] > 15: f += 1
        if res["3Yr Sales CAGR %"] > 0: f += 1
        if total_assets > 0: f += 1
        res["Piotroski"] = f

        return res, file_bytes
    except Exception as e:
        st.error(f"Error in {filename}: {e}")
        return None, None

# ─────────────────────────────────────────────────────────────────────────────
# 3. UI LAYOUT & TABS
# ─────────────────────────────────────────────────────────────────────────────

st.title("🏛️ Institutional Research Terminal")
st.markdown("<p class='hero-subtitle'>Precision Quantitative Analysis & Multi-Company Risk Auditor</p>", unsafe_allow_html=True)

with st.sidebar:
    st.header("📂 Batch Ingestion")
    uploads = st.file_uploader("Upload Screener Excels", type="xlsx", accept_multiple_files=True)
    st.divider()
    st.caption("Terminal v2.5 | Real-time Risk Auditor")

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

        # ── TAB 1: MASTER MATRIX ──
        with tab1:
            st.subheader("Institutional Comparison Grid")
            st.dataframe(df.style.format({
                "Market Cap": "₹{:,.0f}Cr", "Sales": "₹{:,.0f}Cr", "Net Profit": "₹{:,.0f}Cr",
                "ROCE %": "{:.1f}%", "PE": "{:.1f}x", "D/E": "{:.2f}", "3Yr Sales CAGR %": "{:.1f}%",
                "FCF Yield %": "{:.1f}%", "Altman Z": "{:.2f}"
            }).background_gradient(subset=["Piotroski"], cmap="RdYlGn"))

        # ── TAB 2: NARRATIVE DEEP-DIVE ──
        with tab2:
            selected_companies = st.multiselect("Select for Narrative Analysis:", df["Company"].unique(), default=df["Company"].unique()[:min(3, len(df))])
            if len(selected_companies) >= 2:
                subset = df[df["Company"].isin(selected_companies)]
                for _, row in subset.iterrows():
                    with st.expander(f"Strategic Narrative: {row['Company']}", expanded=True):
                        c1, c2 = st.columns([1, 2])
                        with c1:
                            st.write(f"**Piotroski:** {row['Piotroski']}/8")
                            st.write(f"**Altman Z:** {row['Altman Z']:.2f}")
                            st.write(f"**ROCE:** {row['ROCE %']:.1f}%")
                        with c2:
                            st.markdown(f"**Analysis:** {row['Company']} is currently trading at a P/E of {row['PE']:.1f}x with a 3-year revenue CAGR of {row['3Yr Sales CAGR %']:.1f}%. "
                                        f"Its capital structure is {('conservative' if row['D/E'] < 0.5 else 'highly geared')} with a D/E of {row['D/E']:.2f}. "
                                        f"The Sloan Accrual of {row['Sloan %']:.1f}% suggests {('high' if abs(row['Sloan %']) < 10 else 'poor')} earnings quality.")

        # ── TAB 3: VISUALIZATIONS ──
        with tab3:
            c1, c2 = st.columns(2)
            with c1:
                fig1 = px.scatter(df, x="PE", y="OPM %", size="Market Cap", color="Zone",
                                 hover_name="Company", title="Valuation vs. Operating Efficiency",
                                 color_discrete_map={"Safe": "#10b981", "Grey": "#fbbf24", "Distress": "#ef4444"})
                st.plotly_chart(fig1, use_container_width=True)
            with c2:
                fig2 = go.Figure(data=[
                    go.Bar(name='Piotroski (Operational)', x=df['Company'], y=df['Piotroski'], marker_color='#10b981'),
                    go.Bar(name='Altman Z (Solvency)', x=df['Company'], y=df['Altman Z'], marker_color='#3b82f6')
                ])
                fig2.update_layout(title="Strength vs. Solvency Profile", barmode='group', template="plotly_dark")
                st.plotly_chart(fig2, use_container_width=True)

            # DuPont
            st.subheader("DuPont Components (Simplified)")
            df['Profit_Margin'] = df['Net Profit'] / df['Sales']
            fig3 = px.bar(df, x="Company", y="Profit_Margin", title="Profitability Component", template="plotly_dark")
            st.plotly_chart(fig3, use_container_width=True)

        # ── TAB 4: RED-FLAG AUDIT ──
        with tab4:
            st.subheader("🚨 Automated Risk Auditor")
            for _, row in df.iterrows():
                with st.container():
                    st.write(f"### {row['Company']}")
                    cols = st.columns(4)
                    
                    # Flag 1: Earnings Quality
                    if row['Net Profit'] > 0 and row['FCF'] < 0:
                        cols[0].error("⚠️ Earnings Quality\nProfit reported but FCF is Negative.")
                    else: cols[0].success("✅ Cash Quality OK")
                    
                    # Flag 2: Debt Stress
                    if row['D/E'] > 1.2 and row['Interest Coverage'] < 2.5:
                        cols[1].error("⚠️ Debt Stress\nHigh D/E & Weak Interest Coverage.")
                    else: cols[1].success("✅ Debt Profile OK")
                    
                    # Flag 3: Accrual Risk
                    if row['Sloan %'] > 10:
                        cols[2].warning("⚠️ Accrual Risk\nSloan Ratio > 10% (Non-cash PAT).")
                    else: cols[2].success("✅ Accruals OK")
                    
                    # Flag 4: CapEx Trap
                    if row['CWIP to Net Block %'] > 35:
                        cols[3].warning("⚠️ CapEx Trap\nHeavy CWIP relative to Net Block.")
                    else: cols[3].success("✅ Asset Expansion OK")
                st.divider()

        # ── TAB 5: EXPORT ──
        with tab5:
            st.subheader("Generate Executive Summary")
            report = f"# Institutional Equity Research Report\nGenerated: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
            for _, row in df.iterrows():
                report += f"## {row['Company']}\n"
                report += f"- Score: {row['Piotroski']}/8 | Health: {row['Zone']}\n"
                report += f"- ROCE: {row['ROCE %']:.1f}% | 3Yr Sales CAGR: {row['3Yr Sales CAGR %']:.1f}%\n"
                report += f"- PE: {row['PE']:.1f}x | FCF Yield: {row['FCF Yield %']:.1f}%\n"
                report += "- Flags: " + ("RED FLAGS DETECTED" if (row['Sloan %'] > 10 or row['D/E'] > 1.2) else "No Major Flags") + "\n\n"
            
            st.download_button("📥 Download Executive Report (.md)", data=report, file_name="Institutional_Report.md")
            
            zip_io = io.BytesIO()
            with zipfile.ZipFile(zip_io, 'w') as zf:
                for fname, content in raw_files: zf.writestr(f"Processed_{fname}", content)
            st.download_button("📥 Download Processed Excels (.zip)", data=zip_io.getvalue(), file_name="Quant_Batch.zip")

else:
    st.info("👋 Welcome to the Terminal. Upload Screener.in Excel exports in the sidebar to begin.")
