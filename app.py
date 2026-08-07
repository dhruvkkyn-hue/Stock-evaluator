import streamlit as st
import pandas as pd
import openpyxl
import io
import zipfile
import re
import plotly.express as px
import plotly.graph_objects as go
import traceback
from datetime import datetime

# ─────────────────────────────────────────────────────────────────────────────
# 1. UI/UX: INSTITUTIONAL CSS INJECTION
# ─────────────────────────────────────────────────────────────────────────────
st.set_page_config(page_title="IERT Institutional Terminal v3.5", layout="wide", page_icon="💎")

def inject_custom_css():
    st.markdown("""
    <style>
        :root {
            --bg-dark: #0e1117;
            --card-bg: #161b22;
            --border-color: #30363d;
            --text-main: #c9d1d9;
            --emerald: #10b981;
            --rose: #f85149;
            --gold: #f59e0b;
        }
        .stApp { background-color: var(--bg-dark); color: var(--text-main); }
        div[data-testid="stMetric"] {
            background-color: var(--card-bg);
            border: 1px solid var(--border-color);
            padding: 15px; border-radius: 10px;
        }
        .narrative-box {
            padding: 20px; border-left: 4px solid var(--emerald);
            background: #1c2128; border-radius: 0 8px 8px 0;
            margin-bottom: 20px; line-height: 1.6;
        }
        .bull-box { padding: 15px; border: 1px solid #238636; background: #0e2a14; border-radius: 8px; margin-bottom: 10px; }
        .bear-box { padding: 15px; border: 1px solid #da3633; background: #2d1110; border-radius: 8px; }
        .buy-trigger { color: #3fb950; font-weight: bold; border: 1px solid #3fb950; padding: 10px; border-radius: 5px; background: #0e2a14; }
        .sell-trigger { color: #f85149; font-weight: bold; border: 1px solid #f85149; padding: 10px; border-radius: 5px; background: #2d1110; }
    </style>
    """, unsafe_allow_html=True)

inject_custom_css()

# ─────────────────────────────────────────────────────────────────────────────
# 2. QUANT ENGINE: SAFE MATH & HEURISTIC EXTRACTION
# ─────────────────────────────────────────────────────────────────────────────

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
    for row in ws.iter_rows(min_row=1, max_row=150, min_col=1, max_col=2):
        label = f"{str(row[0].value or '')} {str(row[1].value or '')}".lower().strip()
        if any(k == label or k in label for k in kw_lower):
            row_idx = row[0].row
            # Data usually starts in Col 3 (C) in Screener Data Sheet
            return [safe_float(ws.cell(row=row_idx, column=c).value, None) 
                    for c in range(3, ws.max_column + 1) 
                    if ws.cell(row=row_idx, column=c).value is not None]
    return []

# ─────────────────────────────────────────────────────────────────────────────
# 3. NARRATIVE INTELLIGENCE LOGIC
# ─────────────────────────────────────────────────────────────────────────────

def get_qualitative_analysis(r):
    """Generates deep, stock-specific commentary."""
    name = r['Company']
    
    # Valuation Perspective
    if r['PE'] > 45:
        val_view = f"{name} is commanding a significant growth premium ({r['PE']:.1f}x PE). This implies the market expects flawless execution and superior earnings compounding."
    elif r['PE'] < 15 and r['PE'] > 0:
        val_view = f"At {r['PE']:.1f}x PE, {name} appears to be in 'Value Territory'. This could be a mispricing or a reflection of cyclical headwinds."
    else:
        val_view = f"The valuation of {r['PE']:.1f}x for {name} aligns with current industrial standard multiples."

    # Cash & Accruals
    if r['Sloan %'] > 10:
        accrual_view = f"Warning: {name} shows a high Sloan Ratio of {r['Sloan %']:.1f}%, indicating that reported profits are significantly ahead of cash collections."
    else:
        accrual_view = f"The Sloan Ratio of {r['Sloan %']:.1f}% suggests high earnings purity for {name}."

    # Solvency
    solv_comment = f"With an Altman Z-Score of {r['Altman Z']:.2f}, the firm is structurally '{r['Zone']}'."
    
    return {
        "overview": f"{val_view} {accrual_view} {solv_comment}",
        "bull": [
            f"Sustained ROCE of {r['ROCE %']:.1f}% could trigger a valuation re-rating.",
            f"Strong FCF Yield of {r['FCF Yield %']:.1f}% provides massive room for dividends/buybacks.",
            f"If 3-Yr Sales CAGR of {r['3Yr Sales CAGR %']:.1f}% accelerates, EPS expansion will be non-linear."
        ],
        "bear": [
            f"Debt/Equity of {r['D/E']:.2f} is high; a spike in interest rates would crush margins.",
            f"Inventory/Receivable buildup could further degrade the Sloan Ratio.",
            f"Low Interest Coverage ({r['Interest Coverage']:.1f}x) leaves little margin for error in a downturn."
        ]
    }

# ─────────────────────────────────────────────────────────────────────────────
# 4. PROCESSING ENGINE
# ─────────────────────────────────────────────────────────────────────────────

def process_workbook(file_bytes, filename):
    try:
        wb = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True)
        ds_name = next((s for s in wb.sheetnames if "data sheet" in s.lower()), None)
        if not ds_name: return None, None
        ws = wb[ds_name]

        extracted_name = ws.cell(row=1, column=2).value
        comp_name = str(extracted_name).strip() if extracted_name else str(filename).replace(".xlsx", "")

        # EXHAUSTIVE KEYWORD MAPPING (Fix for Issue 1)
        data_map = {
            "mcap": ["market capitalization", "market cap", "mar cap", "current market cap"],
            "price": ["current price", "cmp", "stock price"],
            "shares": ["number of equity shares", "no. of equity shares", "shares outstanding"],
            "sales": ["sales", "revenue", "interest earned", "total income"],
            "op": ["operating profit", "ebitda", "pbit", "financing profit"],
            "pat": ["net profit", "pat", "profit after tax"],
            "pbt": ["profit before tax", "pbt"],
            "interest": ["interest", "finance costs"],
            "debt": ["borrowings", "total debt"],
            "equity": ["equity share capital", "share capital"],
            "reserves": ["reserves", "other equity"],
            "cfo": ["cash from operating activity", "cash flow from operations", "cfo", "cash from operating"],
            "cfi": ["cash from investing activity", "cash from investing", "cfi", "purchase of fixed assets"],
            "cwip": ["capital work in progress", "cwip"],
            "net_block": ["net block", "fixed assets"],
            "liab": ["other liabilities", "total liabilities"],
            "assets": ["total assets"],
            "receivables": ["receivables", "trade receivables"],
            "inventory": ["inventory", "inventories"],
            "cash": ["cash & bank", "cash equivalents"]
        }

        raw = {k: find_row_series(ws, v) for k, v in data_map.items()}
        curr = {k: (raw[k][-1] if raw[k] else 0.0) for k in raw}
        
        # 🚨 FALLBACK: CALCULATE MARKET CAP IF MISSING
        if curr['mcap'] == 0 and curr['price'] > 0 and curr['shares'] > 0:
            curr['mcap'] = curr['price'] * curr['shares']
        
        # 🚨 SECTOR DETECTION
        is_bank = any(kw in str(ws.cell(row=i, column=1).value).lower() 
                     for i in range(1, 20) for kw in ["interest earned", "financing profit"])

        # Calculations
        local_equity = curr['equity'] + curr['reserves']
        local_debt = curr['debt']
        local_assets = curr['assets'] if curr['assets'] else (local_equity + local_debt + curr['liab'])
        
        res = {"Company": comp_name, "Sector": "Finance" if is_bank else "Industrial"}
        res["Market Cap"] = curr['mcap']
        res["Sales"] = curr['sales']
        res["Net Profit"] = curr['pat']
        res["PE"] = safe_div(curr['mcap'], curr['pat'])
        res["D/E"] = safe_div(local_debt, local_equity)
        res["ROCE %"] = safe_div(curr['pbt'] + curr['interest'], local_equity + local_debt) * 100
        res["OPM %"] = safe_div(curr['op'], curr['sales']) * 100
        res["Interest Coverage"] = safe_div(curr['pbt'] + curr['interest'], curr['interest'], default=99.0)
        res["FCF"] = curr['cfo'] - abs(curr['cfi'])
        res["FCF Yield %"] = safe_div(res["FCF"], curr['mcap']) * 100
        res["Sloan %"] = safe_div(curr['pat'] - curr['cfo'], local_assets) * 100
        res["3Yr Sales CAGR %"] = calculate_cagr(raw['sales'], 3)
        res["3Yr PAT CAGR %"] = calculate_cagr(raw['pat'], 3)
        res["CWIP %"] = safe_div(curr['cwip'], curr['net_block']) * 100

        # Altman Z
        wc = (curr['receivables'] + curr['inventory'] + curr['cash']) - curr['liab']
        z_val = (1.2 * safe_div(wc, local_assets)) + (1.4 * safe_div(curr['reserves'], local_assets)) + \
                (3.3 * safe_div(curr['op'], local_assets)) + (0.6 * safe_div(curr['mcap'], local_debt + curr['liab'])) + \
                (1.0 * safe_div(curr['sales'], local_assets))
        res["Altman Z"] = round(z_val, 2)
        res["Zone"] = "Safe" if z_val > 2.99 else "Grey" if z_val >= 1.81 else "Distress"

        # Piotroski F-Score (8-pt adaptation)
        f = 0
        if curr['pat'] > 0: f += 1
        if curr['cfo'] > 0: f += 1
        if curr['cfo'] > curr['pat']: f += 1
        if res["ROCE %"] > 15: f += 1
        if res["D/E"] < 1.0: f += 1
        if res["3Yr Sales CAGR %"] > 0: f += 1
        if res["OPM %"] > (safe_div(raw['op'][-2], raw['sales'][-2])*100 if len(raw['op'])>1 else 0): f += 1
        if res["Sloan %"] < 10: f += 1
        res["Piotroski"] = f

        return res, file_bytes
    except Exception as e:
        st.error(f"Error processing {filename}: {str(e)}")
        return None, None

# ─────────────────────────────────────────────────────────────────────────────
# 5. UI LAYOUT & TABS
# ─────────────────────────────────────────────────────────────────────────────

with st.sidebar:
    st.header("📂 Batch Ingestion")
    uploads = st.file_uploader("Upload Screener Excels", type="xlsx", accept_multiple_files=True)
    st.divider()
    st.caption(f"Terminal v3.5 | Institutional Grade")

st.title("🏛️ Institutional Research Terminal")

if uploads:
    results, raw_files = [], []
    for up in uploads:
        data, b_content = process_workbook(up.getvalue(), up.name)
        if data:
            results.append(data)
            raw_files.append((up.name, b_content))

    if results:
        df = pd.DataFrame(results)
        t1, t2, t3, t4, t5 = st.tabs(["📊 Matrix", "🕵️ Deep-Dive", "📈 Visuals", "🚨 Audit", "📄 Export"])

        with t1:
            st.dataframe(df.style.format({
                "Market Cap": "₹{:,.0f}Cr", "Sales": "₹{:,.0f}Cr", "Net Profit": "₹{:,.0f}Cr",
                "ROCE %": "{:.1f}%", "PE": "{:.1f}x", "D/E": "{:.2f}", "3Yr Sales CAGR %": "{:.1f}%",
                "FCF Yield %": "{:.1f}%", "Altman Z": "{:.2f}", "Interest Coverage": "{:.1f}x", "Sloan %": "{:.1f}%"
            }).background_gradient(subset=["Piotroski"], cmap="RdYlGn", vmin=0, vmax=8))

        with t2:
            st.subheader("Qualitative Intelligence Engine")
            target = st.selectbox("Select Target Company:", df["Company"].unique())
            r = df[df["Company"] == target].iloc[0]
            analysis = get_qualitative_analysis(r)

            c1, c2 = st.columns([2, 1])
            with c1:
                st.markdown(f"### 🧬 Strategic DNA: {target}")
                st.markdown(f"<div class='narrative-box'>{analysis['overview']}</div>", unsafe_allow_html=True)
                
                bc1, bc2 = st.columns(2)
                with bc1:
                    st.markdown("<div class='bull-box'><b>🐂 Bull Case catalysts</b><ul>" + 
                                "".join([f"<li>{x}</li>" for x in analysis['bull']]) + "</ul></div>", unsafe_allow_html=True)
                with bc2:
                    st.markdown("<div class='bear-box'><b>🐻 Bear Case risks</b><ul>" + 
                                "".join([f"<li>{x}</li>" for x in analysis['bear']]) + "</ul></div>", unsafe_allow_html=True)
            with c2:
                st.markdown("### 🚦 Actionable Triggers")
                st.markdown(f"<div class='buy-trigger'>ACCUMULATE IF:<br>• PE drops below {(r['PE']*0.85):.1f}x<br>• Piotroski Score ≥ 7<br>• FCF Yield > 5%</div>", unsafe_allow_html=True)
                st.write("")
                st.markdown(f"<div class='sell-trigger'>LIQUIDATE/TRIM IF:<br>• Sloan Ratio > 15%<br>• Altman Z enters 'Distress'<br>• D/E exceeds 1.5x</div>", unsafe_allow_html=True)

        with t3:
            c1, c2 = st.columns(2)
            with c1:
                fig1 = px.scatter(df, x="PE", y="OPM %", size="Market Cap", color="Zone",
                                 hover_name="Company", title="Valuation vs. Profitability",
                                 color_discrete_map={"Safe": "#10b981", "Grey": "#fbbf24", "Distress": "#ef4444"}, template="plotly_dark")
                st.plotly_chart(fig1, use_container_width=True)
            with c2:
                fig2 = go.Figure(data=[
                    go.Bar(name='Piotroski (Quality)', x=df['Company'], y=df['Piotroski'], marker_color='#10b981'),
                    go.Bar(name='Altman Z (Solvency)', x=df['Company'], y=df['Altman Z'], marker_color='#3b82f6')
                ])
                fig2.update_layout(title="Quality vs. Solvency Comparison", barmode='group', template="plotly_dark")
                st.plotly_chart(fig2, use_container_width=True)

        with t4:
            st.subheader("🛡️ Scenario Allocation Matrix")
            top_safe = df.sort_values("Altman Z", ascending=False).iloc[0]['Company']
            top_growth = df.sort_values("Piotroski", ascending=False).iloc[0]['Company']
            
            sc1, sc2 = st.columns(2)
            sc1.metric("🛡️ Bear Market / Rate Hike Pick", top_safe, "Strongest Solvency")
            sc2.metric("🚀 Bull Market / Growth Pick", top_growth, "Highest Quality Score")
            
            st.divider()
            for _, row in df.iterrows():
                flags = []
                if row['Sloan %'] > 12: flags.append("Critical Accrual Risk")
                if row['D/E'] > 1.5: flags.append("Extreme Leverage")
                if row['Zone'] == 'Distress': flags.append("Solvency Danger")
                if flags: st.error(f"**{row['Company']} Red Flags:** " + " | ".join(flags))
                else: st.success(f"**{row['Company']}**: Quantitative audit passed.")

        with t5:
            report_md = "# 🏛️ Institutional Research Executive Summary\n\n"
            for _, row in df.iterrows():
                report_md += f"## {row['Company']} ({row['Sector']})\n"
                report_md += f"- **PE**: {row['PE']:.1f}x | **ROCE**: {row['ROCE %']:.1f}%\n"
                report_md += f"- **Health**: {row['Zone']} (Z: {row['Altman Z']:.2f})\n"
                report_md += f"- **Piotroski**: {row['Piotroski']}/8\n\n"
            
            st.download_button("📥 Download Executive Report (.md)", data=report_md, file_name="Institutional_Report.md")
            
            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED, False) as zip_file:
                for fname, content in raw_files: zip_file.writestr(f"ANALYZED_{fname}", content)
            st.download_button("📥 Download Analyzed ZIP Package", data=zip_buffer.getvalue(), file_name="Research_Bundle.zip")
else:
    st.info("👋 Upload Screener.in Excel files to initialize the Terminal.")
