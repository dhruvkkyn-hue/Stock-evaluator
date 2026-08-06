import streamlit as st
import pandas as pd
import openpyxl
import io
import zipfile
import plotly.express as px
import traceback
from datetime import datetime

# 1. UI/UX THEME & CONFIG
st.set_page_config(page_title="IERT Institutional Terminal v3.2", layout="wide", page_icon="💎")

def inject_custom_css():
    st.markdown("""
    <style>
        :root { --bg-dark: #0d1117; --card-bg: #161b22; --border-color: #30363d; --emerald: #10b981; --rose: #f85149; --gold: #f59e0b; }
        .stApp { background-color: var(--bg-dark); color: #c9d1d9; }
        div[data-testid="stMetric"] { background-color: var(--card-bg); border: 1px solid var(--border-color); padding: 20px; border-radius: 12px; }
        .stExpander { border: 1px solid var(--border-color) !important; background-color: var(--card-bg) !important; }
        .narrative-box { padding: 20px; border-left: 4px solid var(--emerald); background: #1c2128; border-radius: 0 8px 8px 0; margin-bottom: 20px; line-height: 1.6; }
        .bull-box { padding: 15px; border: 1px solid #238636; background: #0e2a14; border-radius: 8px; margin-bottom: 10px; }
        .bear-box { padding: 15px; border: 1px solid #da3633; background: #2d1110; border-radius: 8px; }
        .signal-buy { color: #3fb950; font-weight: bold; border: 1px solid #3fb950; padding: 10px; border-radius: 5px; background: #0e2a14; }
        .signal-sell { color: #f85149; font-weight: bold; border: 1px solid #f85149; padding: 10px; border-radius: 5px; background: #2d1110; }
    </style>
    """, unsafe_allow_html=True)
inject_custom_css()

# 2. CORE MATHEMATICAL & EXTRACTION HELPERS
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
    """Robust keyword search across Screener's varying label formats."""
    kw_lower = [k.lower() for k in keywords]
    # Check first 50 rows, columns 1 and 2 (where labels live)
    for row in ws.iter_rows(min_row=1, max_row=150, min_col=1, max_col=2):
        label = f"{str(row[0].value or '')} {str(row[1].value or '')}".lower().strip()
        if any(k == label or k in label for k in kw_lower):
            row_idx = row[0].row
            # Collect data from Column 3 (C) onwards
            return [safe_float(ws.cell(row=row_idx, column=c).value, None) 
                    for c in range(3, ws.max_column + 1) 
                    if ws.cell(row=row_idx, column=c).value is not None]
    return []

# 3. ADVANCED DYNAMIC NARRATIVE ENGINE
def generate_stock_specific_narrative(r):
    """Generates deeply contextual insights using actual stock data points."""
    name = r['Company']
    
    # Valuation Insight
    if r['PE'] > 50:
        val_comment = f"{name} is currently commanding a scarcity premium with a PE of {r['PE']:.1f}x. This suggests the market anticipates aggressive EPS compounding, leaving little room for operational misses."
    elif r['PE'] < 15:
        val_comment = f"Trading at a modest {r['PE']:.1f}x PE, {name} appears undervalued relative to its industrial peers, potentially due to temporary cyclical headwinds."
    else:
        val_comment = f"{name}'s PE of {r['PE']:.1f}x reflects a balanced market consensus on its current growth trajectory."

    # Solvency & Accrual Quality
    if r['Sloan %'] > 12:
        acc_comment = f"A critical red flag is detected in {name}'s earnings purity. The Sloan Ratio of {r['Sloan %']:.1f}% indicates that profits are being recognized significantly faster than cash is being collected."
    else:
        acc_comment = f"The Sloan Ratio for {name} ({r['Sloan %']:.1f}%) confirms high-quality earnings, where reported PAT is well-supported by cash inflows."

    # Capital Structure
    solv_status = "Distress" if r['Altman Z'] < 1.8 else "Safe"
    solv_comment = f"From a solvency perspective, {name} is in the {solv_status} zone (Z-Score: {r['Altman Z']:.2f}). "
    if r['D/E'] > 1.5:
        solv_comment += f"The high Debt/Equity of {r['D/E']:.2f} creates a structural vulnerability in a rising interest rate environment."
    else:
        solv_comment += f"The conservative leverage (D/E: {r['D/E']:.2f}) provides a robust buffer against economic downturns."

    return {
        "summary": f"{val_comment} {acc_comment} {solv_comment}",
        "bull": [
            f"Expansion of ROCE (currently {r['ROCE %']:.1f}%) through optimized asset utilization.",
            f"FCF Re-rating: Current FCF Yield of {r['FCF Yield %']:.1f}% suggests strong potential for dividend hikes.",
            f"Solvency Improvement: A Z-Score move above 3.0 would trigger institutional re-allocation."
        ],
        "bear": [
            f"Interest Coverage Risk: If coverage falls below 2.0x (currently {r['Int. Coverage']:.1f}x), credit ratings may be at risk.",
            f"Accounting Quality: The {r['Sloan %']:.1f}% Sloan Ratio could lead to future non-cash write-downs.",
            f"Margin Compression: Current OPM of {r['OPM %']:.1f}% is vulnerable to raw material volatility."
        ]
    }

# 4. PROCESSING ENGINE
def process_workbook(file_bytes, filename):
    try:
        wb = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True)
        ds_name = next((s for s in wb.sheetnames if "data sheet" in s.lower()), None)
        if not ds_name: return None
        ws = wb[ds_name]

        # ID Metadata
        e_name = ws.cell(row=1, column=2).value
        comp_name = str(e_name).strip() if e_name else str(filename).replace(".xlsx", "")

        # EXHAUSTIVE KEYWORD MAPPING
        kw_map = {
            "mcap": ["market capitalization", "market cap", "mar cap", "current market cap"],
            "price": ["current price", "cmp", "stock price"],
            "shares": ["number of equity shares", "no. of equity shares", "shares outstanding"],
            "sales": ["sales", "revenue", "interest earned", "total income"],
            "op": ["operating profit", "ebitda", "pbit", "operating profit (adj)"],
            "pat": ["net profit", "pat", "profit after tax", "profit for the period"],
            "pbt": ["profit before tax", "pbt"],
            "int": ["interest", "finance costs"],
            "debt": ["borrowings", "total debt", "short term borrowings"],
            "eq": ["equity share capital", "share capital"],
            "res": ["reserves", "other equity"],
            "cfo": ["cash from operating activity", "operating cash flow", "cash flow from operations", "net cash from operating"],
            "cfi": ["cash from investing activity", "net cash from investing", "purchase of fixed assets", "capex"],
            "assets": ["total assets"],
            "liab": ["other liabilities", "current liabilities", "total liabilities"],
            "recv": ["receivables", "trade receivables"],
            "inv": ["inventory", "inventories"],
            "cash": ["cash & bank", "cash equivalents", "bank balance"]
        }

        # Raw Extraction
        raw = {k: find_row_series(ws, v) for k, v in kw_map.items()}
        cur = {k: (raw[k][-1] if raw[k] else 0.0) for k in raw}
        prev = {k: (raw[k][-2] if (raw[k] and len(raw[k]) > 1) else cur[k]) for k in raw}
        
        # 🚨 FALLBACK LOGIC FOR MARKET CAP (Issue 1 Fix)
        if cur['mcap'] == 0 and cur['price'] > 0 and cur['shares'] > 0:
            cur['mcap'] = cur['price'] * cur['shares']
        
        # Intermediate Math
        eq_total = cur['eq'] + cur['res']
        assets_total = cur['assets'] if cur['assets'] > 0 else (eq_total + cur['debt'] + cur['liab'])
        fcf = cur['cfo'] - abs(cur['cfi'])

        res = {"Company": comp_name}
        res["Market Cap"] = cur['mcap']
        res["PE"] = safe_div(cur['mcap'], cur['pat'])
        res["D/E"] = safe_div(cur['debt'], eq_total)
        res["ROCE %"] = safe_div(cur['pbt'] + cur['int'], eq_total + cur['debt']) * 100
        res["OPM %"] = safe_div(cur['op'], cur['sales']) * 100
        res["Sloan %"] = safe_div(cur['pat'] - cur['cfo'], assets_total) * 100
        res["FCF Yield %"] = safe_div(fcf, cur['mcap']) * 100
        res["Int. Coverage"] = safe_div(cur['pbt'] + cur['int'], cur['int'], default=99.0)

        # Altman Z (Z = 1.2A + 1.4B + 3.3C + 0.6D + 1.0E)
        wc = (cur['recv'] + cur['inv'] + cur['cash']) - cur['liab']
        z = (1.2 * safe_div(wc, assets_total)) + \
            (1.4 * safe_div(cur['res'], assets_total)) + \
            (3.3 * safe_div(cur['op'], assets_total)) + \
            (0.6 * safe_div(cur['mcap'], cur['debt'] + cur['liab'])) + \
            (1.0 * safe_div(cur['sales'], assets_total))
        res["Altman Z"] = round(z, 2)
        res["Zone"] = "Safe" if z > 2.99 else "Grey" if z >= 1.81 else "Distress"

        # Piotroski
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
        st.error(f"Failed to process {filename}")
        return None

# 5. APP INTERFACE
st.title("🏛️ Institutional Research Terminal v3.2")
with st.sidebar:
    st.header("📂 Data Ingestion")
    uploaded_files = st.file_uploader("Upload Screener Excels", type="xlsx", accept_multiple_files=True)
    st.divider()
    st.caption(f"Extraction Engine v3.2 | {datetime.now().strftime('%Y')}")

if uploaded_files:
    data = []
    for f in uploaded_files:
        res = process_workbook(f.getvalue(), f.name)
        if res: data.append(res)

    if data:
        df = pd.DataFrame(data)
        
        tab1, tab2, tab3 = st.tabs(["📊 Fundamental Matrix", "🧠 Deep-Dive Intelligence", "🚨 Audit & Export"])

        with tab1:
            # Styled Matrix
            st.dataframe(df.style.format({
                "Market Cap": "₹{:,.0f}Cr", "PE": "{:.1f}x", "D/E": "{:.2f}", 
                "ROCE %": "{:.1f}%", "OPM %": "{:.1f}%", "Altman Z": "{:.2f}", 
                "Sloan %": "{:.1f}%", "FCF Yield %": "{:.1f}%"
            }).background_gradient(subset=["Piotroski"], cmap="RdYlGn", vmin=0, vmax=8), 
            use_container_width=True, height=450)

        with tab2:
            st.subheader("Strategic Deep-Dive Commentary")
            target = st.selectbox("Select Target Company for Analysis:", df["Company"].unique())
            r_data = df[df["Company"] == target].iloc[0]
            nar = generate_stock_specific_narrative(r_data)

            # Narrative Column
            c1, c2 = st.columns([2, 1])
            with c1:
                st.markdown(f"### 🧪 Equity DNA: {target}")
                st.markdown(f"<div class='narrative-box'>{nar['summary']}</div>", unsafe_allow_html=True)
                
                # Bull/Bear Cards
                bc1, bc2 = st.columns(2)
                with bc1:
                    st.markdown("<div class='bull-box'><b>🐂 Bull Case Drivers</b><ul>" + "".join([f"<li>{x}</li>" for x in nar['bull']]) + "</ul></div>", unsafe_allow_html=True)
                with bc2:
                    st.markdown("<div class='bear-box'><b>🐻 Bear Case Risks</b><ul>" + "".join([f"<li>{x}</li>" for x in nar['bear']]) + "</ul></div>", unsafe_allow_html=True)

            with c2:
                st.markdown("### 🚦 Actionable Triggers")
                # Dynamic Buying Rule
                st.markdown(f"<div class='signal-buy'>CONSIDER ACCUMULATING IF:<br>• PE drops to {(r_data['PE']*0.85):.1f}x<br>• Piotroski Score ≥ 7<br>• ROCE sustains > 15%</div>", unsafe_allow_html=True)
                st.write("")
                # Dynamic Selling Rule
                st.markdown(f"<div class='signal-sell'>CONSIDER TRIMMING IF:<br>• D/E exceeds 1.2x<br>• Z-Score drops to 'Distress'<br>• Sloan Ratio > 10%</div>", unsafe_allow_html=True)

        with tab3:
            st.subheader("Quantitative Audit Trail")
            for _, row in df.iterrows():
                with st.expander(f"Audit Log: {row['Company']}"):
                    cols = st.columns(4)
                    cols[0].metric("F-Score", f"{row['Piotroski']}/8")
                    cols[1].metric("Z-Score", row['Altman Z'], row['Zone'])
                    cols[2].metric("FCF Yield", f"{row['FCF Yield %']:.1f}%")
                    cols[3].metric("Sloan Ratio", f"{row['Sloan %']:.1f}%")
            
            st.divider()
            csv = df.to_csv(index=False).encode('utf-8')
            st.download_button("📥 Export Analysis to CSV", csv, "Terminal_Export.csv", "text/csv")

else:
    st.info("👋 Upload Screener.in Excel files in the sidebar to begin terminal analysis.")
