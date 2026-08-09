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
            padding: 18px;
            border-radius: 10px;
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.35);
            transition: transform 0.2s ease, border-color 0.2s ease;
        }
        div[data-testid="stMetric"]:hover {
            border-color: var(--accent-emerald);
            transform: translateY(-2px);
        }
        
        h1, h2, h3, h4 { 
            color: var(--text-heading) !important; 
            font-family: 'Inter', system-ui, -apple-system, sans-serif;
            font-weight: 700;
        }
        .hero-title {
            font-size: 2.3rem;
            font-weight: 800;
            background: linear-gradient(90deg, #ffffff, #94a3b8);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            margin-bottom: 0.2rem;
        }
        .hero-subtitle { 
            color: #8b949e; 
            font-size: 1.05rem; 
            margin-bottom: 1.8rem; 
        }
        
        .stTabs [data-baseweb="tab-list"] { 
            gap: 10px; 
            border-bottom: 1px solid var(--border-color);
        }
        .stTabs [data-baseweb="tab"] {
            background-color: var(--card-bg);
            border: 1px solid var(--border-color);
            border-radius: 6px 6px 0px 0px;
            padding: 10px 24px;
            color: var(--text-main);
            font-weight: 600;
        }
        .stTabs [aria-selected="true"] {
            background-color: var(--accent-emerald) !important;
            color: #ffffff !important;
            border-color: var(--accent-emerald) !important;
        }
        
        .sector-badge {
            background-color: #1e293b;
            color: #38bdf8;
            padding: 3px 8px;
            border-radius: 4px;
            font-size: 0.8rem;
            font-weight: 600;
            border: 1px solid #0284c7;
        }
        
        .signal-tag-strong-buy {
            background-color: rgba(16, 185, 129, 0.2);
            color: #10b981;
            padding: 6px 14px;
            border-radius: 6px;
            font-size: 1.1rem;
            font-weight: 800;
            border: 1px solid #10b981;
            display: inline-block;
            margin-bottom: 12px;
        }
        .signal-tag-accumulate {
            background-color: rgba(59, 130, 246, 0.2);
            color: #3b82f6;
            padding: 6px 14px;
            border-radius: 6px;
            font-size: 1.1rem;
            font-weight: 800;
            border: 1px solid #3b82f6;
            display: inline-block;
            margin-bottom: 12px;
        }
        .signal-tag-hold {
            background-color: rgba(245, 158, 11, 0.2);
            color: #f59e0b;
            padding: 6px 14px;
            border-radius: 6px;
            font-size: 1.1rem;
            font-weight: 800;
            border: 1px solid #f59e0b;
            display: inline-block;
            margin-bottom: 12px;
        }
        .signal-tag-avoid {
            background-color: rgba(239, 68, 68, 0.2);
            color: #ef4444;
            padding: 6px 14px;
            border-radius: 6px;
            font-size: 1.1rem;
            font-weight: 800;
            border: 1px solid #ef4444;
            display: inline-block;
            margin-bottom: 12px;
        }
    </style>
    """, unsafe_allow_html=True)

inject_custom_css()

# ─────────────────────────────────────────────────────────────────────────────
# 2. QUANT ENGINE: SAFE MATH & FINANCIAL SECTOR PARSING (PRESERVED)
# ─────────────────────────────────────────────────────────────────────────────

def safe_float(val, default=0.0):
    if val is None: 
        return default
    try:
        if isinstance(val, (int, float)): 
            return float(val)
        s = str(val).replace(',', '').replace('₹', '').replace('Rs.', '').strip()
        if s.startswith('(') and s.endswith(')'): 
            s = "-" + s[1:-1]
        return float(s) if s != '' else default
    except: 
        return default

def safe_div(n, d, default=0.0):
    try:
        n_f = float(n) if n is not None else 0.0
        d_f = float(d) if d is not None else 0.0
        return n_f / d_f if d_f != 0 else default
    except: 
        return default

def calculate_cagr(series, years):
    clean_series = [s for s in series if s is not None]
    if not clean_series or len(clean_series) < years + 1: 
        return 0.0
    try:
        start_val = clean_series[-(years + 1)]
        end_val = clean_series[-1]
        if start_val <= 0 or end_val <= 0: 
            return 0.0
        return ((end_val / start_val) ** (1 / years) - 1) * 100
    except: 
        return 0.0

def find_row_series(ws, keywords):
    kw_lower = [k.lower() for k in keywords]
    for row in ws.iter_rows(min_row=1, max_row=ws.max_row, min_col=1, max_col=3):
        label = f"{str(row[0].value or '')} {str(row[1].value or '')} {str(row[2].value or '')}".lower()
        if any(k in label for k in kw_lower):
            row_idx = row[0].row
            series = []
            for c in range(2, ws.max_column + 1):
                val = ws.cell(row=row_idx, column=c).value
                if val is not None:
                    series.append(safe_float(val, None))
            if series:
                return series
    return None

def detect_financial_entity(ws, filename, extracted_name, raw_data):
    fin_keywords = [
        "bank", "nbfc", "advances", "deposits", "interest earned", "interest expended", 
        "net interest income", "nii", "provisions & contingencies", "gross npa", 
        "net npa", "capital adequacy", "housing finance", "microfinance"
    ]
    
    ws_text_sample = ""
    for r in range(1, min(40, ws.max_row + 1)):
        for c in range(1, min(4, ws.max_column + 1)):
            val = ws.cell(row=r, column=c).value
            if val:
                ws_text_sample += f" {str(val).lower()}"
                
    if any(kw in ws_text_sample for kw in fin_keywords):
        return True

    combined_name = f"{extracted_name} {filename}".lower()
    name_fin_terms = ["bank", "finance", "fin", "nbfc", "capital", "housing fin", "lending"]
    if any(term in combined_name for term in name_fin_terms):
        return True

    return False

def process_workbook(file_bytes, filename):
    try:
        res = {}
        wb = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True)
        ds_name = next((s for s in wb.sheetnames if "data sheet" in s.lower()), wb.sheetnames[0])
        ws = wb[ds_name]

        extracted_name = ws.cell(row=1, column=2).value
        company_name = str(extracted_name).strip() if extracted_name else str(filename).replace(".xlsx", "").replace(".xls", "")
        res["Company"] = company_name

        data_map = {
            "mcap": ["Market Capitalization", "Market Cap"],
            "sales": ["Sales", "Revenue", "Interest Earned", "Total Revenue", "Gross Revenue"],
            "op": ["Operating Profit", "EBITDA", "EBIT", "Operating Profit / (Loss)"],
            "pat": ["Net Profit", "Profit after tax", "PAT"],
            "pbt": ["Profit before tax", "PBT"],
            "interest": ["Interest", "Finance Costs"],
            "depr": ["Depreciation", "Depreciation & Amortization"],
            "debt": ["Borrowings", "Total Debt", "Debt"],
            "equity": ["Equity Share Capital", "Share Capital"],
            "reserves": ["Reserves", "Other Equity"],
            "cfo": ["Cash from Operating", "CFO", "Cash flow from operating activities"],
            "cfi": ["Cash from Investing", "CFI", "Cash flow from investing activities"],
            "capex": ["Capital Expenditure", "Fixed Assets Purchased", "CapEx", "Purchase of fixed assets"],
            "cwip": ["Capital Work in Progress", "CWIP"],
            "net_block": ["Net Block", "Fixed Assets", "Property Plant and Equipment"],
            "liab": ["Other Liabilities", "Total Liabilities", "Current Liabilities"],
            "assets": ["Total Assets"],
            "receivables": ["Receivables", "Trade Receivables"],
            "inventory": ["Inventory", "Inventories"]
        }

        raw = {k: find_row_series(ws, v) for k, v in data_map.items()}
        curr = {k: (raw[k][-1] if raw[k] and raw[k][-1] is not None else 0.0) for k in raw}
        
        is_fin = detect_financial_entity(ws, filename, company_name, raw)
        res["Is_Financial"] = is_fin
        res["Sector_Type"] = "Financial / Banking" if is_fin else "Industrial / Commercial"

        local_equity = curr['equity'] + curr['reserves']
        local_debt = curr['debt']
        local_assets = curr['assets'] if curr['assets'] > 0 else (local_equity + local_debt + curr['liab'])
        local_pat = curr['pat']
        local_pbt = curr['pbt'] if curr['pbt'] != 0 else local_pat
        local_cfo = curr['cfo']
        local_sales = curr['sales']
        local_mcap = curr['mcap']
        
        raw_capex = curr['capex']
        if raw_capex > 0:
            capex_val = raw_capex
        elif curr['cfi'] != 0:
            capex_val = abs(curr['cfi'])
        else:
            capex_val = 0.0

        fcf_val = local_cfo - capex_val
        res["CapEx"] = capex_val
        res["FCF"] = fcf_val
        res["FCF Yield %"] = safe_div(fcf_val, local_mcap) * 100

        if is_fin:
            local_ebit = local_pbt if local_pbt != 0 else local_pat
            res["Interest Coverage"] = None
        else:
            local_ebit = (curr['pbt'] + curr['interest']) if (curr['pbt'] != 0 or curr['interest'] != 0) else curr['op']
            res["Interest Coverage"] = safe_div(local_ebit, curr['interest'], default=999.0) if curr['interest'] > 0 else 999.0

        res["Market Cap"] = local_mcap
        res["Sales"] = local_sales
        res["Net Profit"] = local_pat
        res["PE"] = safe_div(local_mcap, local_pat) if local_pat > 0 else -1.0
        
        ev = local_mcap + local_debt
        ebitda = curr['op'] if curr['op'] > 0 else local_ebit
        res["EV/EBITDA"] = safe_div(ev, ebitda) if ebitda > 0 else -1.0

        res["D/E"] = safe_div(local_debt, local_equity)
        
        if is_fin:
            res["OPM %"] = safe_div(local_pat, local_sales) * 100
            res["ROE %"] = safe_div(local_pat, local_equity) * 100
            res["ROCE %"] = safe_div(local_ebit, local_equity + local_debt) * 100
        else:
            res["OPM %"] = safe_div(curr['op'], local_sales) * 100
            res["ROE %"] = safe_div(local_pat, local_equity) * 100
            res["ROCE %"] = safe_div(local_ebit, local_equity + local_debt) * 100

        res["CWIP to Net Block %"] = safe_div(curr['cwip'], curr['net_block']) * 100 if curr['net_block'] > 0 else 0.0
        res["3Yr Sales CAGR %"] = calculate_cagr(raw['sales'], 3)
        res["3Yr PAT CAGR %"] = calculate_cagr(raw['pat'], 3)
        
        if is_fin:
            res["Sloan %"] = None
        else:
            res["Sloan %"] = safe_div(local_pat - local_cfo, local_assets) * 100

        if is_fin:
            res["Altman Z"] = None
            res["Zone"] = "N/A (Financial)"
        else:
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

        p_score = 0
        if local_pat > 0: p_score += 1
        if local_cfo > 0: p_score += 1
        if local_cfo > local_pat: p_score += 1
        if res["3Yr PAT CAGR %"] > 0: p_score += 1
        
        if raw['debt'] and len(raw['debt']) > 1 and raw['equity'] and len(raw['equity']) > 1 and raw['reserves'] and len(raw['reserves']) > 1:
            prev_eq = (raw['equity'][-2] or 0.0) + (raw['reserves'][-2] or 0.0)
            prev_de = safe_div(raw['debt'][-2], prev_eq)
            if res["D/E"] <= prev_de: p_score += 1
            
        if res["ROCE %"] > 12: p_score += 1
        if res["3Yr Sales CAGR %"] > 0: p_score += 1
        if local_assets > 0: p_score += 1
        res["Piotroski"] = p_score

        return res, file_bytes

    except Exception as e:
        err_msg = f"Error in {filename}: {str(e)}\n{traceback.format_exc()}"
        st.error(err_msg)
        return None, None

def dataframe_to_markdown_table(df_sub):
    headers = list(df_sub.columns)
    header_row = "| " + " | ".join(headers) + " |"
    sep_row = "| " + " | ".join(["---"] * len(headers)) + " |"
    data_rows = []
    for _, row in df_sub.iterrows():
        r_str = [str(val) for val in row.values]
        data_rows.append("| " + " | ".join(r_str) + " |")
    return "\n".join([header_row, sep_row] + data_rows)

# ─────────────────────────────────────────────────────────────────────────────
# 3. EXPERTISE TIER CONTENT GENERATORS
# ─────────────────────────────────────────────────────────────────────────────

def get_metric_interpretation(row, metric_key, complexity):
    comp = row["Company"]
    is_fin = row["Is_Financial"]
    val = row[metric_key]

    # Content for Beginner
    beginner_map = {
        "PE": {
            "analogy": "How many years of profit it takes to pay back your stock purchase price.",
            "lie": "A low P/E can be a 'Value Trap' if the industry is dying or earnings are about to crash.",
            "status": "[🟢 STRONG]" if (val > 0 and val <= 20) else "[🟡 AVERAGE]" if (val <= 40) else "[🔴 WEAK]"
        },
        "ROE %": {
            "analogy": "Interest dollars your savings account gives you per $100 of your own money.",
            "lie": "High ROE can be faked by taking on massive bank debt, which makes equity look small.",
            "status": "[🟢 STRONG]" if val >= 18 else "[🟡 AVERAGE]" if val >= 12 else "[🔴 WEAK]"
        },
        "D/E": {
            "analogy": "Comparing your credit card debt to the cash in your savings account.",
            "lie": "Utilities and infrastructure firms naturally have high debt but safe, steady income.",
            "status": "[🟢 STRONG]" if (val <= 0.5 or (is_fin and val <= 6)) else "[🔴 WEAK]"
        }
    }

    if complexity == "🌱 Beginner Investor":
        if metric_key in beginner_map:
            m = beginner_map[metric_key]
            return f"- **Status:** {m['status']}\n- 💡 **Analogy:** {m['analogy']}\n- ⚠️ **When it can lie:** {m['lie']}"
        return f"- **Value:** {val}"

    elif complexity == "📈 Intermediate Investor":
        return f"- **Insight:** Analyzing {metric_key} relative to sector cyclicality and operational efficiency. Current: {val}"

    else: # Pro
        return f"- **Institutional Check:** {metric_key} input for DCF/LBO modeling. Raw Data: {val}. Sensitivity: High."

def generate_dynamic_analysis(row, complexity):
    is_fin = row["Is_Financial"]
    
    with st.expander("▸ Valuation & Pricing Power (P/E, EV/EBITDA, OPM %)", expanded=True):
        st.markdown(f"**P/E Ratio:**\n{get_metric_interpretation(row, 'PE', complexity)}")
        st.markdown(f"**EV/EBITDA:**\n{get_metric_interpretation(row, 'EV/EBITDA', complexity)}")
        st.markdown(f"**Operating Margin (OPM %):**\n{get_metric_interpretation(row, 'OPM %', complexity)}")

    with st.expander("▸ Capital Efficiency & Cash Quality (ROE, ROCE, Sloan Ratio, FCF Yield)"):
        st.markdown(f"**ROE %:**\n{get_metric_interpretation(row, 'ROE %', complexity)}")
        st.markdown(f"**ROCE %:**\n{get_metric_interpretation(row, 'ROCE %', complexity)}")
        st.markdown(f"**FCF Yield %:**\n{get_metric_interpretation(row, 'FCF Yield %', complexity)}")
        if not is_fin:
            st.markdown(f"**Sloan Accrual %:**\n{get_metric_interpretation(row, 'Sloan %', complexity)}")

    with st.expander("▸ Solvency & Operational Momentum (Altman Z, Piotroski, D/E)"):
        st.markdown(f"**Piotroski Score:**\n{get_metric_interpretation(row, 'Piotroski', complexity)}")
        st.markdown(f"**Debt-to-Equity:**\n{get_metric_interpretation(row, 'D/E', complexity)}")
        if not is_fin:
            st.markdown(f"**Altman Z-Score:**\n{get_metric_interpretation(row, 'Altman Z', complexity)}")

def generate_action_block(row):
    comp = row["Company"]
    is_fin = row["Is_Financial"]
    roe = row["ROE %"]
    pe = row["PE"]
    de = row["D/E"]
    p_score = row["Piotroski"]
    fcf_y = row["FCF Yield %"]

    score = 0
    if roe >= 15: score += 1
    if pe > 0 and pe <= 25: score += 1
    if de <= 0.8 or (is_fin and de <= 7.0): score += 1
    if p_score >= 6: score += 1
    if fcf_y >= 3.0: score += 1

    if score >= 4:
        verdict = f"<div class='signal-tag-strong-buy'>🟢 FINAL VERDICT: [STRONG BUY]</div>"
    elif score >= 3:
        verdict = f"<div class='signal-tag-accumulate'>🔵 FINAL VERDICT: [ACCUMULATE ON DIPS]</div>"
    elif score >= 2:
        verdict = f"<div class='signal-tag-hold'>🟡 FINAL VERDICT: [HOLD / WATCHLIST]</div>"
    else:
        verdict = f"<div class='signal-tag-avoid'>🔴 FINAL VERDICT: [AVOID / EXIT]</div>"
    
    st.markdown(verdict, unsafe_allow_html=True)
    
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**🟢 Exact BUY Triggers:**")
        st.write(f"1. Entry below {pe*0.9:.1f}x P/E.")
        st.write(f"2. ROCE sustained above 15%.")
        st.write(f"3. Positive FCF generation.")
    with c2:
        st.markdown("**🔴 Exact SELL Triggers:**")
        st.write(f"1. D/E crossing {de*1.5:.2f}.")
        st.write(f"2. Piotroski score drops below 4.")
        st.write(f"3. OPM contraction > 300bps.")
    
    st.markdown("**🔄 Game-Changer Events:**")
    st.caption("Commissioning of major CWIP projects; Debt-free status attainment; Change in promoter holding.")

# ─────────────────────────────────────────────────────────────────────────────
# 4. MAIN UI LAYOUT
# ─────────────────────────────────────────────────────────────────────────────

with st.sidebar:
    st.header("📂 Batch Ingestion")
    uploads = st.file_uploader("Upload Screener Excels", type=["xlsx", "xls"], accept_multiple_files=True)
    st.divider()
    
    st.header("🛠️ Analysis Framework")
    complexity = st.sidebar.radio("Select Analysis Complexity:", 
                                ["🌱 Beginner Investor", "📈 Intermediate Investor", "🏛️ Pro / Institutional Analyst"])
    
    st.divider()
    max_pe_bound = st.slider("Scatter Plot Max P/E Axis Limit", 50, 300, 150, 25)
    st.caption(f"Institutional Terminal v6.0 | {datetime.now().year}")

st.markdown("<h1 class='hero-title'>🏛️ Institutional Research Terminal</h1>", unsafe_allow_html=True)
st.markdown(f"<p class='hero-subtitle'>Dynamic Quantitative Auditor — Mode: <b>{complexity}</b></p>", unsafe_allow_html=True)

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
        
        tab_matrix, tab_deep, tab_thesis, tab_risk, tab_visual, tab_export = st.tabs([
            "📊 Master Matrix", "🔍 Metric Deep-Dive", "🏛️ Bull & Bear Thesis", 
            "🛡️ Forensic Risk", "📈 Visuals", "📄 Export"
        ])

        with tab_matrix:
            st.dataframe(df[[
                "Company", "Sector_Type", "Market Cap", "PE", "ROE %", "ROCE %", "D/E", "Piotroski", "Zone"
            ]].style.background_gradient(subset=["Piotroski"], cmap="RdYlGn"), use_container_width=True)

        with tab_deep:
            selection = st.selectbox("Select Company for Deep-Dive:", df["Company"].unique())
            row = df[df["Company"] == selection].iloc[0]
            generate_dynamic_analysis(row, complexity)

        with tab_thesis:
            selection_multi = st.multiselect("Compare Action Triggers:", df["Company"].unique(), default=df["Company"].unique()[:2])
            cols = st.columns(len(selection_multi)) if selection_multi else [st.empty()]
            for i, sel in enumerate(selection_multi):
                with cols[i]:
                    st.subheader(sel)
                    row_sel = df[df["Company"] == sel].iloc[0]
                    generate_action_block(row_sel)

        with tab_risk:
            st.subheader("🚨 Automated Forensic Risk Auditor")
            for _, r in df.iterrows():
                with st.expander(f"Risk Profile: {r['Company']}"):
                    c1, c2, c3 = st.columns(3)
                    if r['Net Profit'] > 0 and r['FCF'] < 0: c1.error("Cash Conversion: FAIL")
                    else: c1.success("Cash Conversion: PASS")
                    
                    if not r['Is_Financial']:
                        if r['D/E'] > 1.2: c2.error("Solvency: HIGH DEBT")
                        else: c2.success("Solvency: STABLE")
                        if r['Sloan %'] and r['Sloan %'] > 10: c3.warning("Accruals: AGGRESSIVE")
                        else: c3.success("Accruals: CLEAN")
                    else:
                        c2.info("Financial Entity: Check CAR")
                        c3.info("Sloan N/A for Banks")

        with tab_visual:
            c1, c2 = st.columns(2)
            with c1:
                scatter_df = df.copy()
                scatter_df["Plot_PE"] = scatter_df["PE"].apply(lambda x: min(x, max_pe_bound) if x > 0 else 0)
                fig1 = px.scatter(scatter_df, x="Plot_PE", y="ROE %", size="Market Cap", color="Zone", 
                                 hover_name="Company", title="Valuation vs. Quality")
                fig1.update_layout(template="plotly_dark")
                st.plotly_chart(fig1, use_container_width=True)
            with c2:
                fig2 = go.Figure()
                fig2.add_trace(go.Bar(x=df['Company'], y=df['Piotroski'], name='Piotroski Score', marker_color='#10b981'))
                fig2.update_layout(template="plotly_dark", title="Operational Quality Score")
                st.plotly_chart(fig2, use_container_width=True)

        with tab_export:
            st.subheader("📄 Generate Research Report")
            report_md = f"# RESEARCH REPORT: {complexity}\nGenerated: {datetime.now()}\n\n"
            report_md += dataframe_to_markdown_table(df[["Company", "PE", "ROE %", "D/E", "Piotroski"]])
            
            st.download_button("📥 Download .md Report", data=report_md, 
                               file_name=f"Report_{complexity.replace(' ', '_')}.md")
            
            zip_io = io.BytesIO()
            with zipfile.ZipFile(zip_io, 'w') as zf:
                for fname, content in raw_files: 
                    zf.writestr(f"Processed_{fname}", content)
            st.download_button("📥 Download Raw Data (.zip)", data=zip_io.getvalue(), file_name="Data_Package.zip")

else:
    st.info("👋 Please upload Screener.in Excel files to begin analysis.")
