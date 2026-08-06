import streamlit as st
import pandas as pd
import openpyxl
import io
import zipfile
import plotly.express as px
import plotly.graph_objects as go
import traceback
from datetime import datetime

# 1. UI/UX THEME & CONFIG
st.set_page_config(page_title="IERT Institutional Terminal", layout="wide", page_icon="💎")

def inject_custom_css():
    st.markdown("""
    <style>
        :root { --bg-dark: #0e1117; --card-bg: #161b22; --border-color: #30363d; --emerald: #10b981; --rose: #f85149; }
        .stApp { background-color: var(--bg-dark); color: #c9d1d9; }
        div[data-testid="stMetric"] { background-color: var(--card-bg); border: 1px solid var(--border-color); padding: 15px; border-radius: 10px; }
        .reportview-container .main { background: var(--bg-dark); }
        .stTabs [data-baseweb="tab-list"] { gap: 8px; }
        .stTabs [data-baseweb="tab"] { background-color: var(--card-bg); border: 1px solid var(--border-color); border-radius: 5px 5px 0 0; padding: 10px 20px; }
    </style>
    """, unsafe_allow_html=True)
inject_custom_css()

# 2. CORE MATHEMATICAL HELPERS
def safe_float(val, default=0.0):
    if val is None or val == "": return default
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

def find_row_series(ws, keywords):
    kw_lower = [k.lower() for k in keywords]
    for row in ws.iter_rows(min_row=1, max_row=ws.max_row, min_col=1, max_col=2):
        label = f"{str(row[0].value or '')} {str(row[1].value or '')}".lower()
        if any(k in label for k in kw_lower):
            row_idx = row[0].row
            # Collect columns from C onwards (Screener data starts at Col 3)
            return [safe_float(ws.cell(row=row_idx, column=c).value, None) for c in range(3, ws.max_column + 1) if ws.cell(row=row_idx, column=c).value is not None]
    return []

# 3. THE ANALYTIC ENGINE
def process_workbook(file_bytes, filename):
    try:
        wb = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True)
        ds_name = next((s for s in wb.sheetnames if "data sheet" in s.lower()), None)
        if not ds_name: return None
        ws = wb[ds_name]

        # Metadata
        e_name = ws.cell(row=1, column=2).value
        comp_name = str(e_name).strip() if e_name else str(filename).replace(".xlsx", "")

        # Expanded Keyword Map for Sector Diversity (Steel, Banks, IT)
        m = {
            "mcap": ["Market Capitalization", "Market Cap"],
            "sales": ["Sales", "Revenue", "Interest Earned"],
            "op": ["Operating Profit", "EBITDA", "PBIT"],
            "pat": ["Net Profit", "PAT", "Profit after tax"],
            "pbt": ["Profit before tax", "PBT"],
            "int": ["Interest", "Finance Costs"],
            "debt": ["Borrowings", "Total Debt"],
            "eq": ["Equity Share Capital", "Share Capital"],
            "res": ["Reserves", "Other Equity"],
            "cfo": ["Cash from Operating", "CFO"],
            "cfi": ["Cash from Investing", "CFI"],
            "assets": ["Total Assets"],
            "liab": ["Other Liabilities", "Current Liabilities"],
            "recv": ["Receivables", "Trade Receivables"],
            "inv": ["Inventory", "Inventories"],
            "cash": ["Cash & Bank", "Cash Equivalents"]
        }

        raw = {k: find_row_series(ws, v) for k, v in m.items()}
        cur = {k: (raw[k][-1] if raw[k] else 0.0) for k in raw}
        prev = {k: (raw[k][-2] if (raw[k] and len(raw[k]) > 1) else cur[k]) for k in raw}
        
        # Financial Structural Logic
        eq_total = cur['eq'] + cur['res']
        assets_total = cur['assets'] if cur['assets'] > 0 else (eq_total + cur['debt'] + cur['liab'])
        
        final = {"Company": comp_name}
        final["Market Cap"] = cur['mcap']
        final["PE"] = safe_div(cur['mcap'], cur['pat'])
        final["D/E"] = safe_div(cur['debt'], eq_total)
        final["ROCE %"] = safe_div(cur['pbt'] + cur['int'], eq_total + cur['debt']) * 100
        final["OPM %"] = safe_div(cur['op'], cur['sales']) * 100
        final["Sloan %"] = safe_div(cur['pat'] - cur['cfo'], assets_total) * 100
        final["FCF"] = cur['cfo'] - abs(cur['cfi'])
        final["Int. Coverage"] = safe_div(cur['pbt'] + cur['int'], cur['int'], default=99.0)

        # Altman Z-Score Calculation (Industrial Model)
        wc = (cur['recv'] + cur['inv'] + cur['cash']) - cur['liab']
        z = (1.2 * safe_div(wc, assets_total)) + \
            (1.4 * safe_div(cur['res'], assets_total)) + \
            (3.3 * safe_div(cur['op'], assets_total)) + \
            (0.6 * safe_div(cur['mcap'], cur['debt'] + cur['liab'])) + \
            (1.0 * safe_div(cur['sales'], assets_total))
        final["Altman Z"] = round(z, 2)
        final["Zone"] = "Safe" if z > 2.99 else "Grey" if z >= 1.81 else "Distress"

        # Piotroski F-Score (8-point adaptation)
        f = 0
        if cur['pat'] > 0: f += 1 # Profitability
        if cur['cfo'] > 0: f += 1 # Cash flow
        if cur['cfo'] > cur['pat']: f += 1 # Accrual quality
        if safe_div(cur['pat'], assets_total) > safe_div(prev['pat'], assets_total): f += 1 # ROA Improving
        if cur['debt'] <= prev['debt']: f += 1 # Leverage
        if cur['sales'] > prev['sales']: f += 1 # Growth
        if cur['op'] > prev['op']: f += 1 # Efficiency
        if safe_div(cur['op'], cur['sales']) > safe_div(prev['op'], prev['sales']): f += 1 # Margin
        final["Piotroski"] = f

        return final
    except Exception:
        st.error(f"Error processing {filename}: {traceback.format_exc()}")
        return None

# 4. APP INTERFACE
st.title("🏛️ Institutional Research Terminal")
st.markdown("<p style='color:#8b949e; font-size:1.1rem;'>Zero-Crash Quantitative Analysis Engine v2.6</p>", unsafe_allow_html=True)

with st.sidebar:
    st.header("📂 Data Ingestion")
    uploaded_files = st.file_uploader("Upload Screener Excels", type="xlsx", accept_multiple_files=True)
    st.divider()
    st.info("💡 Pro Tip: Upload both Bank and Industrial files. The engine detects 'Interest Earned' vs 'Sales' automatically.")

if uploaded_files:
    processed_results = []
    for f in uploaded_files:
        res = process_workbook(f.getvalue(), f.name)
        if res: processed_results.append(res)

    if processed_results:
        df = pd.DataFrame(processed_results)
        
        tab1, tab2, tab3, tab4 = st.tabs(["📊 Matrix Analysis", "📈 Risk Visuals", "🚨 Audit Trail", "📄 Export"])

        with tab1:
            st.subheader("Fundamental Master-Matrix")
            styled_df = df.style.format({
                "Market Cap": "₹{:,.0f}Cr", "PE": "{:.1f}x", "D/E": "{:.2f}", 
                "ROCE %": "{:.1f}%", "OPM %": "{:.1f}%", "Altman Z": "{:.2f}", "Sloan %": "{:.1f}%"
            }).background_gradient(subset=["Piotroski"], cmap="RdYlGn", vmin=0, vmax=8)
            st.dataframe(styled_df, use_container_width=True, height=400)

        with tab2:
            st.subheader("Quality vs. Valuation Map")
            fig = px.scatter(df, x="PE", y="ROCE %", size="Market Cap", color="Zone",
                             hover_name="Company", text="Company",
                             color_discrete_map={"Safe": "#10b981", "Grey": "#f59e0b", "Distress": "#ef4444"},
                             title="Bubble Size = Market Cap | Color = Solvency Zone")
            fig.update_layout(template="plotly_dark", plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)')
            st.plotly_chart(fig, use_container_width=True)

        with tab3:
            cols = st.columns(2)
            for i, row in df.iterrows():
                with cols[i % 2].expander(f"Audit: {row['Company']}", expanded=True):
                    c1, c2, c3 = st.columns(3)
                    c1.metric("F-Score", f"{row['Piotroski']}/8")
                    c2.metric("Solvency", row['Zone'])
                    c3.metric("Accruals", f"{row['Sloan %']:.1f}%")
                    
                    if row['Piotroski'] >= 6: st.success("✅ Strong Operational Momentum")
                    if row['Sloan %'] > 10: st.warning("⚠️ High Accruals: Check Earnings Purity")
                    if row['D/E'] > 1.5: st.error("❌ High Leverage Risk")

        with tab4:
            st.subheader("Generate Terminal Report")
            csv = df.to_csv(index=False).encode('utf-8')
            
            # Create ZIP in memory
            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED, False) as zip_file:
                zip_file.writestr("Analysis_Summary.csv", csv)
            
            st.download_button(
                label="📥 Download Research Bundle (ZIP)",
                data=zip_buffer.getvalue(),
                file_name=f"Research_Bundle_{datetime.now().strftime('%Y%m%d')}.zip",
                mime="application/zip"
            )
else:
    st.info("👋 System Ready. Please upload Screener.in Excel files to initialize analysis.")
