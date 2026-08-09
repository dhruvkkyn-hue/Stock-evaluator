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
st.set_page_config(
    page_title="Institutional Equity Terminal", 
    layout="wide", 
    page_icon="💎"
)

def inject_custom_css():
    st.markdown("""
    <style>
        :root {
            --bg-dark: #0e1117;
            --card-bg: #161b22;
            --card-hover: #1c2128;
            --border-color: #30363d;
            --text-main: #c9d1d9;
            --text-heading: #ffffff;
            --accent-emerald: #10b981;
            --accent-blue: #3b82f6;
            --accent-orange: #f59e0b;
        }
        .stApp { background-color: var(--bg-dark); color: var(--text-main); }
        
        div[data-testid="stMetric"] {
            background-color: var(--card-bg);
            border: 1px solid var(--border-color);
            padding: 15px;
            border-radius: 8px;
            box-shadow: 0 2px 8px rgba(0, 0, 0, 0.2);
        }
        
        h1, h2, h3, h4 { 
            color: var(--text-heading) !important; 
            font-family: 'Inter', system-ui, -apple-system, sans-serif;
        }
        .hero-title {
            font-size: 2.1rem;
            font-weight: 800;
            background: linear-gradient(90deg, #ffffff, #94a3b8);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            margin-bottom: 0.1rem;
        }
        
        .stTabs [data-baseweb="tab-list"] { gap: 8px; }
        .stTabs [data-baseweb="tab"] {
            background-color: var(--card-bg);
            border-radius: 4px 4px 0 0;
            padding: 8px 16px;
        }
        
        .level-badge {
            padding: 2px 8px;
            border-radius: 12px;
            font-size: 0.75rem;
            font-weight: 700;
            text-transform: uppercase;
        }
        .badge-beginner { background-color: #065f46; color: #a7f3d0; }
        .badge-intermediate { background-color: #1e3a8a; color: #bfdbfe; }
        .badge-pro { background-color: #701a75; color: #f5d0fe; }

        .metric-card {
            background: var(--card-bg);
            padding: 1.2rem;
            border-radius: 10px;
            border: 1px solid var(--border-color);
            margin-bottom: 1rem;
        }
    </style>
    """, unsafe_allow_html=True)

inject_custom_css()

# ─────────────────────────────────────────────────────────────────────────────
# 2. QUANT ENGINE: CORE CALCULATIONS (RETAINED)
# ─────────────────────────────────────────────────────────────────────────────

def safe_float(val, default=0.0):
    if val is None: return default
    try:
        if isinstance(val, (int, float)): return float(val)
        s = str(val).replace(',', '').replace('₹', '').replace('Rs.', '').strip()
        if s.startswith('(') and s.endswith(')'): s = "-" + s[1:-1]
        return float(s) if s != '' else default
    except: return default

def safe_div(n, d, default=0.0):
    try:
        n_f = float(n) if n is not None else 0.0
        d_f = float(d) if d is not None else 0.0
        return n_f / d_f if d_f != 0 else default
    except: return default

def calculate_cagr(series, years):
    clean_series = [s for s in series if s is not None]
    if not clean_series or len(clean_series) < years + 1: return 0.0
    try:
        start_val = clean_series[-(years + 1)]
        end_val = clean_series[-1]
        if start_val <= 0 or end_val <= 0: return 0.0
        return ((end_val / start_val) ** (1 / years) - 1) * 100
    except: return 0.0

def find_row_series(ws, keywords):
    kw_lower = [k.lower() for k in keywords]
    for row in ws.iter_rows(min_row=1, max_row=ws.max_row, min_col=1, max_col=3):
        label = f"{str(row[0].value or '')} {str(row[1].value or '')} {str(row[2].value or '')}".lower()
        if any(k in label for k in kw_lower):
            row_idx = row[0].row
            series = []
            for c in range(2, ws.max_column + 1):
                val = ws.cell(row=row_idx, column=c).value
                series.append(safe_float(val, None))
            return series
    return None

def detect_financial_entity(ws, filename, extracted_name, raw_data):
    fin_keywords = ["bank", "nbfc", "advances", "deposits", "interest earned", "nii", "provisions"]
    ws_text_sample = ""
    for r in range(1, min(30, ws.max_row + 1)):
        for c in range(1, min(4, ws.max_column + 1)):
            if ws.cell(row=r, column=c).value: ws_text_sample += f" {str(ws.cell(row=r, column=c).value).lower()}"
    if any(kw in ws_text_sample for kw in fin_keywords): return True
    combined_name = f"{extracted_name} {filename}".lower()
    if any(term in combined_name for term in ["bank", "finance", "fin", "nbfc", "capital"]): return True
    return False

def process_workbook(file_bytes, filename):
    try:
        wb = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True)
        ds_name = next((s for s in wb.sheetnames if "data sheet" in s.lower()), wb.sheetnames[0])
        ws = wb[ds_name]
        extracted_name = ws.cell(row=1, column=2).value
        company_name = str(extracted_name).strip() if extracted_name else str(filename).replace(".xlsx", "")
        
        data_map = {
            "mcap": ["Market Capitalization", "Market Cap"],
            "sales": ["Sales", "Revenue", "Interest Earned"],
            "op": ["Operating Profit", "EBITDA"],
            "pat": ["Net Profit", "PAT"],
            "pbt": ["Profit before tax", "PBT"],
            "interest": ["Interest", "Finance Costs"],
            "debt": ["Borrowings", "Total Debt"],
            "equity": ["Equity Share Capital", "Share Capital"],
            "reserves": ["Reserves", "Other Equity"],
            "cfo": ["Cash from Operating", "CFO"],
            "cfi": ["Cash from Investing", "CFI"],
            "capex": ["Capital Expenditure", "Purchase of fixed assets"],
            "cwip": ["Capital Work in Progress", "CWIP"],
            "net_block": ["Net Block", "Fixed Assets"],
            "assets": ["Total Assets"],
            "receivables": ["Receivables"],
            "inventory": ["Inventory"]
        }

        raw = {k: find_row_series(ws, v) for k, v in data_map.items()}
        curr = {k: (raw[k][-1] if raw[k] and raw[k][-1] is not None else 0.0) for k in raw}
        is_fin = detect_financial_entity(ws, filename, company_name, raw)
        
        local_equity = curr['equity'] + curr['reserves']
        local_debt = curr['debt']
        local_assets = curr['assets'] if curr['assets'] > 0 else (local_equity + local_debt)
        local_pat = curr['pat']
        local_sales = curr['sales']
        
        res = {"Company": company_name, "Is_Financial": is_fin, "Sector_Type": "Financial" if is_fin else "Industrial"}
        res["Market Cap"] = curr['mcap']
        res["Sales"] = local_sales
        res["Net Profit"] = local_pat
        res["PE"] = safe_div(curr['mcap'], local_pat) if local_pat > 0 else -1.0
        res["EV/EBITDA"] = safe_div(curr['mcap'] + local_debt, curr['op']) if curr['op'] > 0 else -1.0
        res["D/E"] = safe_div(local_debt, local_equity)
        res["ROE %"] = safe_div(local_pat, local_equity) * 100
        res["ROCE %"] = safe_div(curr['op'], local_equity + local_debt) * 100
        res["Interest Coverage"] = safe_div(curr['op'], curr['interest']) if curr['interest'] > 0 else 999.0
        res["3Yr Sales CAGR %"] = calculate_cagr(raw['sales'], 3)
        res["3Yr PAT CAGR %"] = calculate_cagr(raw['pat'], 3)
        res["FCF"] = curr['cfo'] - abs(curr['cfi'] if curr['cfi'] < 0 else curr['capex'])
        res["FCF Yield %"] = safe_div(res["FCF"], curr['mcap']) * 100
        res["Sloan %"] = safe_div(local_pat - curr['cfo'], local_assets) * 100
        res["CWIP to Net Block %"] = safe_div(curr['cwip'], curr['net_block']) * 100
        
        # Altman Z
        if not is_fin:
            wc = (curr['receivables'] + curr['inventory']) - (local_assets * 0.1) # Proxy WC
            z = (1.2 * safe_div(wc, local_assets)) + (1.4 * safe_div(curr['reserves'], local_assets)) + \
                (3.3 * safe_div(curr['op'], local_assets)) + (0.6 * safe_div(curr['mcap'], local_debt)) + \
                (0.99 * safe_div(local_sales, local_assets))
            res["Altman Z"] = z
            res["Zone"] = "Safe" if z > 2.99 else "Grey" if z >= 1.81 else "Distress"
        else:
            res["Altman Z"], res["Zone"] = None, "N/A"

        # Piotroski
        p = 0
        if local_pat > 0: p += 1
        if curr['cfo'] > 0: p += 1
        if curr['cfo'] > local_pat: p += 1
        if res["3Yr PAT CAGR %"] > 0: p += 1
        if res["D/E"] < 1.0: p += 1
        if res["ROE %"] > 15: p += 1
        if res["3Yr Sales CAGR %"] > 0: p += 1
        if local_assets > 0: p += 1
        res["Piotroski"] = p

        return res, file_bytes
    except Exception as e:
        st.error(f"Error parsing {filename}: {e}")
        return None, None

# ─────────────────────────────────────────────────────────────────────────────
# 3. QUALITATIVE GENERATORS: 3-TIER ARCHITECTURE
# ─────────────────────────────────────────────────────────────────────────────

def get_benchmark_badge(val, metric_type):
    thresholds = {
        "ROE %": (18, 12), "ROCE %": (15, 10), "Piotroski": (6, 4), 
        "D/E": (0.5, 1.2), "PE": (15, 35), "FCF Yield %": (5, 2)
    }
    if metric_type not in thresholds: return ""
    high, mid = thresholds[metric_type]
    if metric_type in ["D/E", "PE"]: # Lower is better
        if val <= high: return "[🟢 STRONG]"
        if val <= mid: return "[🟡 AVERAGE]"
        return "[🔴 WEAK]"
    else: # Higher is better
        if val >= high: return "[🟢 STRONG]"
        if val >= mid: return "[🟡 AVERAGE]"
        return "[🔴 WEAK]"

def render_metric_logic(row, metric_key, level):
    val = row[metric_key]
    is_fin = row["Is_Financial"]
    
    content = {
        "PE": {
            "Beginner": f"**Analogy:** The price tag per ₹1 of profit. \n- **Status:** {get_benchmark_badge(val, 'PE')} \n- **Meaning:** You pay ₹{val:.1f} for every ₹1 the company earns. \n- **The Lie:** A 'cheap' low PE might mean the business is dying.",
            "Intermediate": f"Trading at {val:.1f}x earnings. Relative to sector peers, this multiple reflects { 'a premium' if val > 25 else 'value' } orientation.",
            "Pro": f"**Formula:** Market Cap / PAT. \n- Current: {val:.1f}x. \n- Yield Equiv: {safe_div(1, val)*100:.2f}%."
        },
        "ROE %": {
            "Beginner": f"**Analogy:** The interest rate the company earns on its own money. \n- **Status:** {get_benchmark_badge(val, 'ROE %')} \n- **Meaning:** For every ₹100 of its own cash, it generates ₹{val:.1f} profit. \n- **The Lie:** High ROE can be faked by taking massive, dangerous bank loans.",
            "Intermediate": f"Return on Equity is {val:.1f}%. This indicates efficient internal compounding of shareholder capital.",
            "Pro": f"**DuPont Component:** {val:.1f}%. Reflects Net Margin x Asset Turnover x Equity Multiplier."
        },
        "Sloan %": {
            "Beginner": f"**Analogy:** The 'Real Cash' detector. \n- **Meaning:** { 'Profits are backed by real cash' if val < 10 else 'Warning: Profits might just be paper promises' }. \n- **The Lie:** Growing companies sometimes have high accruals naturally during expansion.",
            "Intermediate": f"Sloan Ratio: {val:.1f}%. { 'Earnings quality is high.' if val < 10 else 'Potential accrual accounting inflation detected.' }",
            "Pro": f"**Accrual Math:** (NI - CFO) / Total Assets. Current: {val:.1f}%. Threshold > 10% indicates aggressive revenue recognition."
        }
    }
    return content.get(metric_key, {}).get(level.split()[1], "Metric data unavailable for this level.")

def render_thesis_content(row, level):
    comp = row["Company"]
    if "Beginner" in level:
        return f"### ⚖️ Simple Pros & Cons\n**Pros:**\n- 🟢 Strong {row['Piotroski']}/8 quality score.\n- 🟢 Generates ₹{row['FCF']:.0f}Cr in spare cash.\n\n**Cons:**\n- 🔴 Debt is {row['D/E']:.2f}x its own cash.\n- 🔴 P/E of {row['PE']:.1f} is { 'expensive' if row['PE']>30 else 'fair' }."
    elif "Intermediate" in level:
        return f"### 🐂 Bull vs 🐻 Bear\n**Bull Case:** Capital efficiency (ROCE: {row['ROCE %']:.1f}%) suggests a wide moat. 3Yr Sales growth of {row['3Yr Sales CAGR %']:.1f}% shows momentum.\n\n**Bear Case:** Sloan ratio of {row['Sloan %']:.1f}% indicates { 'potential earnings quality issues.' if row['Sloan %']>10 else 'no major red flags.' }"
    else:
        return f"### 🏛️ Institutional Risk Matrix\n- **Forensic:** Altman Z ({row['Altman Z'] if row['Altman Z'] else 'N/A'}) puts entity in {row['Zone']} zone.\n- **Capital:** Interest coverage at {row['Interest Coverage']:.1f}x.\n- **Valuation:** EV/EBITDA of {row['EV/EBITDA']:.1f}x relative to {row['3Yr PAT CAGR %']:.1f}% growth."

def render_action_triggers(row, level):
    if "Beginner" in level:
        return f"**When to Buy:** If the stock price drops and P/E goes below 20.\n\n**When to Sell:** If the business starts losing money or debt doubles."
    elif "Intermediate" in level:
        return f"**Entry Trigger:** Accumulate on 10% dips if ROE remains > 15%.\n\n**Exit Trigger:** Structural decline in OPM % or Sloan Ratio exceeding 15%."
    else:
        return f"**Allocation:** Core position if FCF Yield > 5% and Piotroski >= 7.\n\n**Catalyst Watch:** CWIP at {row['CWIP to Net Block %']:.1f}% - monitor for commissioning."

# ─────────────────────────────────────────────────────────────────────────────
# 4. MAIN INTERFACE
# ─────────────────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("<h2 style='margin-top:0;'>⚙️ Control Panel</h2>", unsafe_allow_html=True)
    level = st.sidebar.radio("Select Analysis Complexity:", ["🌱 Beginner Investor", "📈 Intermediate Investor", "🏛️ Pro / Institutional Analyst"])
    st.divider()
    uploads = st.file_uploader("Upload Screener Excels", type=["xlsx"], accept_multiple_files=True)
    st.divider()
    st.caption(f"Terminal v6.0 | {datetime.now().strftime('%Y-%m-%d')}")

st.markdown("<h1 class='hero-title'>🏛️ Institutional Research Terminal</h1>", unsafe_allow_html=True)

if uploads:
    results, raw_files = [], []
    for up in uploads:
        data, b_content = process_workbook(up.getvalue(), up.name)
        if data:
            results.append(data)
            raw_files.append((up.name, b_content))

    if results:
        df = pd.DataFrame(results)
        
        # 1. Top Level KPI Badges
        st.subheader("🏆 Cohort Leaders")
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Top ROE", df.loc[df['ROE %'].idxmax()]['Company'], f"{df['ROE %'].max():.1f}%")
        k2.metric("Best Quality", df.loc[df['Piotroski'].idxmax()]['Company'], f"Score {df['Piotroski'].max()}")
        k3.metric("FCF King", df.loc[df['FCF Yield %'].idxmax()]['Company'], f"{df['FCF Yield %'].max():.1f}%")
        safe_z = df[df['Altman Z'].notnull()]
        if not safe_z.empty:
            k4.metric("Safest Solvency", safe_z.loc[safe_z['Altman Z'].idxmax()]['Company'], f"Z {safe_z['Altman Z'].max():.2f}")

        # 2. Comparative Matrix
        with st.expander("📊 Full Quantitative Matrix (Raw Data)", expanded=False):
            st.dataframe(df.drop(columns=["Is_Financial"]), use_container_width=True)

        st.divider()
        
        # 3. Tabbed Deep-Dive
        selection = st.multiselect("Select Companies for Deep Analysis:", df["Company"].unique(), default=df["Company"].unique()[:2])
        
        if selection:
            t1, t2, t3, t4 = st.tabs(["📊 Metric Deep-Dive", "🏛️ Bull & Bear Thesis", "🚦 Action Triggers", "🛡️ Risk Auditor"])
            
            sub = df[df["Company"].isin(selection)]
            
            with t1:
                for _, row in sub.iterrows():
                    st.markdown(f"### {row['Company']} <span class='level-badge badge-{'beginner' if 'Beginner' in level else 'intermediate' if 'Intermediate' in level else 'pro'}'>{level}</span>", unsafe_allow_html=True)
                    e1, e2, e3 = st.columns(3)
                    with e1:
                        with st.expander("💎 Valuation & Pricing", expanded=True):
                            st.write(render_metric_logic(row, "PE", level))
                    with e2:
                        with st.expander("⚡ Capital & Cash", expanded=True):
                            st.write(render_metric_logic(row, "ROE %", level))
                    with e3:
                        with st.expander("🛡️ Quality & Accruals", expanded=True):
                            st.write(render_metric_logic(row, "Sloan %", level))
                    st.divider()

            with t2:
                cols = st.columns(len(sub))
                for i, (_, row) in enumerate(sub.iterrows()):
                    with cols[i]:
                        st.markdown(f"#### {row['Company']}")
                        st.info(render_thesis_content(row, level))

            with t3:
                cols = st.columns(len(sub))
                for i, (_, row) in enumerate(sub.iterrows()):
                    with cols[i]:
                        st.markdown(f"#### {row['Company']}")
                        st.success(render_action_triggers(row, level))

            with t4:
                for _, row in sub.iterrows():
                    c1, c2, c3, c4 = st.columns(4)
                    c1.write(f"**{row['Company']}**")
                    c2.write(f"Altman Zone: **{row['Zone']}**")
                    c3.write(f"Piotroski: **{row['Piotroski']}/8**")
                    c4.write(f"D/E: **{row['D/E']:.2f}**")
                    if not row['Is_Financial'] and row['Sloan %'] > 10: st.error("🚨 FORENSIC ALERT: High Accrual Ratio detected.")
                    if row['Interest Coverage'] < 2: st.warning("⚠️ SOLVENCY ALERT: Low Interest Coverage.")
                    st.divider()

        # 4. Visuals (Retained)
        st.subheader("📈 Visual Intelligence")
        vc1, vc2 = st.columns(2)
        with vc1:
            fig = px.scatter(df, x="PE", y="ROE %", size="Market Cap", color="Sector_Type", hover_name="Company", title="ROE vs Valuation")
            st.plotly_chart(fig, use_container_width=True)
        with vc2:
            fig2 = px.bar(df, x="Company", y="Piotroski", color="Piotroski", title="Quality Scores")
            st.plotly_chart(fig2, use_container_width=True)

        # 5. Export Report
        st.divider()
        report = f"# Research Report: {level}\nGenerated: {datetime.now()}\n\n"
        for _, row in sub.iterrows():
            report += f"## {row['Company']}\n"
            report += f"{render_thesis_content(row, level)}\n\n"
            report += f"### Action Plan\n{render_action_triggers(row, level)}\n\n"
            report += "---\n"
        
        st.download_button("📥 Export Dynamic Report (.md)", data=report, file_name=f"Report_{level.split()[1]}.md")

else:
    st.info("👋 Upload Excel files in the sidebar to begin analysis.")
