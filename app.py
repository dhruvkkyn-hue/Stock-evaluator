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
st.set_page_config(page_title="IERT Institutional Terminal v3.0", layout="wide", page_icon="💎")

def inject_custom_css():
    st.markdown("""
    <style>
        :root { --bg-dark: #0d1117; --card-bg: #161b22; --border-color: #30363d; --emerald: #10b981; --rose: #f85149; --gold: #f59e0b; }
        .stApp { background-color: var(--bg-dark); color: #c9d1d9; }
        div[data-testid="stMetric"] { background-color: var(--card-bg); border: 1px solid var(--border-color); padding: 20px; border-radius: 12px; }
        .stExpander { border: 1px solid var(--border-color) !important; background-color: var(--card-bg) !important; }
        .narrative-box { padding: 20px; border-left: 4px solid var(--emerald); background: #1c2128; border-radius: 0 8px 8px 0; margin-bottom: 20px; }
        .bull-box { padding: 15px; border: 1px solid #238636; background: #0e2a14; border-radius: 8px; }
        .bear-box { padding: 15px; border: 1px solid #da3633; background: #2d1110; border-radius: 8px; }
        .buy-rule { color: #3fb950; font-weight: bold; }
        .sell-rule { color: #f85149; font-weight: bold; }
    </style>
    """, unsafe_allow_html=True)
inject_custom_css()

# 2. CORE CRASH-PROOF HELPERS
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
            return [safe_float(ws.cell(row=row_idx, column=c).value, None) for c in range(3, ws.max_column + 1) if ws.cell(row=row_idx, column=c).value is not None]
    return []

# 3. NARRATIVE INTELLIGENCE ENGINE
def generate_equity_narrative(r):
    """Generates institutional-grade qualitative analysis based on row data."""
    
    # PE & Valuation Narrative
    val_status = "Premium" if r['PE'] > 40 else "Moderate" if r['PE'] > 15 else "Value/Distressed"
    val_text = f"The stock trades at a {val_status} valuation of {r['PE']:.1f}x. "
    if r['PE'] > 40 and r['ROCE %'] > 20:
        val_text += "This high multiple is supported by superior capital efficiency, suggesting the market is pricing in sustained compound growth."
    elif r['PE'] < 15 and r['Zone'] == 'Safe':
        val_text += "The low multiple combined with a 'Safe' Altman Z-Score suggests a potential 'Value Buy' where the market may be underestimating the balance sheet strength."
    else:
        val_text += "Valuation appears synchronized with current fundamental output."

    # Capital Efficiency & Sloan Ratio
    sloan_status = "Aggressive" if r['Sloan %'] > 10 else "Conservative" if r['Sloan %'] < -5 else "Neutral"
    accrual_text = f"The Sloan Accrual Ratio stands at {r['Sloan %']:.1f}% ({sloan_status}). "
    if r['Sloan %'] > 10:
        accrual_text += "Warning: Net income is significantly higher than Cash from Operations. This 'Accounting Gap' suggests earnings may be driven by non-cash items or aggressive revenue recognition."
    else:
        accrual_text += "Earnings show high purity, with PAT closely tracking actual cash inflows, reducing the risk of future earnings restatements."

    # Solvency & Leverage
    solvency_text = f"With an Altman Z-Score of {r['Altman Z']:.2f} ({r['Zone']}) and a D/E of {r['D/E']:.2f}, "
    if r['Zone'] == 'Safe' and r['Int. Coverage'] > 5:
        solvency_text += "the company maintains a 'Fortress Balance Sheet'. It can comfortably withstand interest rate hikes and economic downturns."
    elif r['Zone'] == 'Distress' or r['D/E'] > 1.5:
        solvency_text += "the structural integrity of the balance sheet is under pressure. High leverage combined with low solvency scores indicates significant refinancing risk."
    else:
        solvency_text += "the company maintains a standard industrial leverage profile with manageable servicing obligations."

    return {
        "val": val_text,
        "accrual": accrual_text,
        "solvency": solvency_text
    }

# 4. PROCESSING ENGINE
def process_workbook(file_bytes, filename):
    try:
        wb = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True)
        ds_name = next((s for s in wb.sheetnames if "data sheet" in s.lower()), None)
        if not ds_name: return None
        ws = wb[ds_name]

        e_name = ws.cell(row=1, column=2).value
        comp_name = str(e_name).strip() if e_name else str(filename).replace(".xlsx", "")

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
        
        eq_total = cur['eq'] + cur['res']
        assets_total = cur['assets'] if cur['assets'] > 0 else (eq_total + cur['debt'] + cur['liab'])
        
        res = {"Company": comp_name}
        res["Market Cap"] = cur['mcap']
        res["Sales"] = cur['sales']
        res["PE"] = safe_div(cur['mcap'], cur['pat'])
        res["D/E"] = safe_div(cur['debt'], eq_total)
        res["ROCE %"] = safe_div(cur['pbt'] + cur['int'], eq_total + cur['debt']) * 100
        res["OPM %"] = safe_div(cur['op'], cur['sales']) * 100
        res["Sloan %"] = safe_div(cur['pat'] - cur['cfo'], assets_total) * 100
        res["FCF Yield %"] = safe_div(cur['cfo'] - abs(cur['cfi']), cur['mcap']) * 100
        res["Int. Coverage"] = safe_div(cur['pbt'] + cur['int'], cur['int'], default=99.0)

        # Altman Z
        wc = (cur['recv'] + cur['inv'] + cur['cash']) - cur['liab']
        z = (1.2 * safe_div(wc, assets_total)) + (1.4 * safe_div(cur['res'], assets_total)) + \
            (3.3 * safe_div(cur['op'], assets_total)) + (0.6 * safe_div(cur['mcap'], cur['debt'] + cur['liab'])) + \
            (1.0 * safe_div(cur['sales'], assets_total))
        res["Altman Z"] = round(z, 2)
        res["Zone"] = "Safe" if z > 2.99 else "Grey" if z >= 1.81 else "Distress"

        # Piotroski F-Score
        f = 0
        if cur['pat'] > 0: f += 1
        if cur['cfo'] > 0: f += 1
        if cur['cfo'] > cur['pat']: f += 1
        if safe_div(cur['pat'], assets_total) > safe_div(prev['pat'], assets_total): f += 1
        if cur['debt'] <= prev['debt']: f += 1
        if cur['sales'] > prev['sales']: f += 1
        if safe_div(cur['op'], cur['sales']) > safe_div(prev['op'], prev['sales']): f += 1
        res["Piotroski"] = f

        return res
    except:
        return None

# 5. APP LAYOUT
st.title("🏛️ Institutional Research Terminal v3.0")
with st.sidebar:
    st.header("📂 Data Ingestion")
    files = st.file_uploader("Upload Screener Excels", type="xlsx", accept_multiple_files=True)
    st.divider()
    st.caption("Strategic Decision Engine Active")

if files:
    data = []
    for f in files:
        out = process_workbook(f.getvalue(), f.name)
        if out: data.append(out)

    if data:
        df = pd.DataFrame(data)
        t1, t2, t3, t4 = st.tabs(["📊 Matrix", "🧠 Intelligence Terminal", "🚨 Risk Audit", "📥 Export"])

        with t1:
            st.dataframe(df.style.format({
                "Market Cap": "₹{:,.0f}Cr", "PE": "{:.1f}x", "D/E": "{:.2f}", 
                "ROCE %": "{:.1f}%", "OPM %": "{:.1f}%", "Altman Z": "{:.2f}", 
                "Sloan %": "{:.1f}%", "FCF Yield %": "{:.1f}%"
            }).background_gradient(subset=["Piotroski"], cmap="RdYlGn", vmin=0, vmax=8))

        with t2:
            st.subheader("Strategic Deep-Dive Narrative")
            selected_stock = st.selectbox("Select Target Company:", df["Company"].unique())
            r = df[df["Company"] == selected_stock].iloc[0]
            nar = generate_equity_narrative(r)

            col1, col2 = st.columns([2, 1])
            with col1:
                st.markdown(f"### 🧬 Fundamental DNA: {selected_stock}")
                st.markdown(f"<div class='narrative-box'><b>Valuation Strategy:</b><br>{nar['val']}</div>", unsafe_allow_html=True)
                st.markdown(f"<div class='narrative-box'><b>Capital Efficiency & Purity:</b><br>{nar['accrual']}</div>", unsafe_allow_html=True)
                st.markdown(f"<div class='narrative-box'><b>Solvency & Resilience:</b><br>{nar['solvency']}</div>", unsafe_allow_html=True)
            
            with col2:
                st.markdown("### 🚦 Decision Rules")
                st.info(f"**Consider BUYING if:**\n- P/E slides below {r['PE']*0.8:.1f}x\n- ROCE holds > 18%\n- Piotroski score stays >= 7")
                st.warning(f"**Consider SELLING if:**\n- Sloan Ratio exceeds 12%\n- Interest Coverage < 3.0x\n- Altman Z drops to 'Grey'")

            st.divider()
            b1, b2 = st.columns(2)
            with b1:
                st.markdown("<div class='bull-box'><h4>🐂 Bull Case Expansion</h4>"
                            "<ul><li><b>Operating Leverage:</b> OPM expansion via raw material softening.</li>"
                            "<li><b>Market Share:</b> MCAP growth driven by industry consolidation.</li>"
                            "<li><b>De-leveraging:</b> Accelerated debt repayment from FCF.</li></ul></div>", unsafe_allow_html=True)
            with b2:
                st.markdown("<div class='bear-box'><h4>🐻 Bear Case Risks</h4>"
                            "<ul><li><b>Margin Compression:</b> Inability to pass on costs to customers.</li>"
                            "<li><b>Working Capital:</b> Bloated inventory dragging down FCF.</li>"
                            "<li><b>Governance:</b> High Sloan ratio indicating 'Paper Profits'.</li></ul></div>", unsafe_allow_html=True)

        with t3:
            st.subheader("Regime Allocation Matrix")
            # Logic for Top Pick
            top_growth = df.sort_values("ROCE %", ascending=False).iloc[0]["Company"]
            top_safe = df.sort_values("Altman Z", ascending=False).iloc[0]["Company"]
            top_value = df.sort_values("FCF Yield %", ascending=False).iloc[0]["Company"]

            c1, c2, c3 = st.columns(3)
            c1.metric("🔥 Bull Market Leader", top_growth, "Growth & ROCE Focus")
            c2.metric("🛡️ Bear Market Fortress", top_safe, "Solvency Focus")
            c3.metric("💰 Value/Income Play", top_value, "FCF Yield Focus")

            st.write("### 🚨 Quantitative Red Flags")
            for _, row in df.iterrows():
                flags = []
                if row['Sloan %'] > 10: flags.append("⚠️ Poor Earnings Purity (Sloan)")
                if row['D/E'] > 1.2: flags.append("⚠️ Excessive Leverage")
                if row['Int. Coverage'] < 2.5: flags.append("❌ Dangerous Interest Burden")
                if row['Zone'] == 'Distress': flags.append("💀 Critical Solvency Risk")
                
                if flags:
                    st.error(f"**{row['Company']}:** " + " | ".join(flags))
                else:
                    st.success(f"**{row['Company']}:** No immediate quantitative red flags detected.")

        with t4:
            csv = df.to_csv(index=False).encode('utf-8')
            st.download_button("📥 Download Analytical Summary (CSV)", csv, "Research_Export.csv", "text/csv")
            
else:
    st.info("👋 System Idle. Please upload Excel data sheets to initialize the Institutional Engine.")
