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
        
        h1, h2, h3 { 
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
    </style>
    """, unsafe_allow_html=True)

inject_custom_css()

# ─────────────────────────────────────────────────────────────────────────────
# 2. QUANT ENGINE: SAFE MATH & FINANCIAL SECTOR PARSING
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
    """
    Searches for keywords in sheet rows and returns time-series list.
    Returns None if no matching row is found (distinguishing missing from zero).
    """
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
    """
    Robust Financial Sector Detection:
    - Scans workbook content, sheet titles, and company names for explicit Banking/NBFC indicators.
    - Avoids inferring financial status solely from zero OP or zero Inventory.
    """
    fin_keywords = [
        "bank", "nbfc", "advances", "deposits", "interest earned", "interest expended", 
        "net interest income", "nii", "provisions & contingencies", "gross npa", 
        "net npa", "capital adequacy", "housing finance", "microfinance"
    ]
    
    # 1. Text scan in Workbook headers/labels
    ws_text_sample = ""
    for r in range(1, min(40, ws.max_row + 1)):
        for c in range(1, min(4, ws.max_column + 1)):
            val = ws.cell(row=r, column=c).value
            if val:
                ws_text_sample += f" {str(val).lower()}"
                
    if any(kw in ws_text_sample for kw in fin_keywords):
        return True

    # 2. Check Name Suffixes / Specific Keywords
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

        # Extract Company Name
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

        # 1. Extraction (Returns None for missing metrics, preserving zero as genuine numeric 0)
        raw = {k: find_row_series(ws, v) for k, v in data_map.items()}
        curr = {k: (raw[k][-1] if raw[k] and raw[k][-1] is not None else 0.0) for k in raw}
        
        # 2. Sector Adaptability Check
        is_fin = detect_financial_entity(ws, filename, company_name, raw)
        res["Is_Financial"] = is_fin
        res["Sector_Type"] = "Financial / Banking" if is_fin else "Industrial / Commercial"

        # 3. Intermediate Capital Variables
        local_equity = curr['equity'] + curr['reserves']
        local_debt = curr['debt']
        local_assets = curr['assets'] if curr['assets'] > 0 else (local_equity + local_debt + curr['liab'])
        local_pat = curr['pat']
        local_pbt = curr['pbt'] if curr['pbt'] != 0 else local_pat
        local_cfo = curr['cfo']
        local_sales = curr['sales']
        local_mcap = curr['mcap']
        
        # CapEx & FCF Extraction with Fallback
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

        # 4. EBIT & Interest Coverage Calculations
        # User Request: Non-financials EBIT = PBT + Interest; Financials EBIT = PBT or Net Profit directly!
        if is_fin:
            local_ebit = local_pbt if local_pbt != 0 else local_pat
            res["Interest Coverage"] = None  # Interest is operating cost for banks
        else:
            local_ebit = (curr['pbt'] + curr['interest']) if (curr['pbt'] != 0 or curr['interest'] != 0) else curr['op']
            res["Interest Coverage"] = safe_div(local_ebit, curr['interest'], default=999.0) if curr['interest'] > 0 else 999.0

        # 5. Core Performance Metrics
        res["Market Cap"] = local_mcap
        res["Sales"] = local_sales
        res["Net Profit"] = local_pat
        res["PE"] = safe_div(local_mcap, local_pat) if local_pat > 0 else -1.0
        res["D/E"] = safe_div(local_debt, local_equity)
        
        # Profitability Margins & Returns
        if is_fin:
            res["OPM %"] = safe_div(local_pat, local_sales) * 100  # Net margin proxy for banks
            res["ROE %"] = safe_div(local_pat, local_equity) * 100
            res["ROCE %"] = safe_div(local_ebit, local_equity + local_debt) * 100
        else:
            res["OPM %"] = safe_div(curr['op'], local_sales) * 100
            res["ROE %"] = safe_div(local_pat, local_equity) * 100
            res["ROCE %"] = safe_div(local_ebit, local_equity + local_debt) * 100

        res["CWIP to Net Block %"] = safe_div(curr['cwip'], curr['net_block']) * 100 if curr['net_block'] > 0 else 0.0
        res["3Yr Sales CAGR %"] = calculate_cagr(raw['sales'], 3)
        res["3Yr PAT CAGR %"] = calculate_cagr(raw['pat'], 3)
        
        # 6. Sloan Accrual Ratio
        if is_fin:
            res["Sloan %"] = None  # Accrual ratio formula is non-standard for banks
        else:
            res["Sloan %"] = safe_div(local_pat - local_cfo, local_assets) * 100

        # 7. Altman Z-Score Calculation (Isolated for Industrial vs. Banking)
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

        # 8. Piotroski Score Calculation
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
    """Clean markdown table generator independent of tabulate package."""
    headers = list(df_sub.columns)
    header_row = "| " + " | ".join(headers) + " |"
    sep_row = "| " + " | ".join(["---"] * len(headers)) + " |"
    data_rows = []
    for _, row in df_sub.iterrows():
        r_str = [str(val) for val in row.values]
        data_rows.append("| " + " | ".join(r_str) + " |")
    return "\n".join([header_row, sep_row] + data_rows)

# ─────────────────────────────────────────────────────────────────────────────
# 3. UI & CONTROL FLOW
# ─────────────────────────────────────────────────────────────────────────────

with st.sidebar:
    st.header("📂 Batch Ingestion")
    uploads = st.file_uploader("Upload Screener Excels", type=["xlsx", "xls"], accept_multiple_files=True)
    st.divider()
    st.markdown("### ⚙️ Terminal Settings")
    max_pe_bound = st.slider("Scatter Plot Max P/E Axis Limit", min_value=50, max_value=300, value=150, step=25, 
                             help="Clips scatter plot x-axis upper bound to prevent valuation outliers from compressing the chart.")
    st.divider()
    st.caption(f"Institutional Terminal v3.0 | {datetime.now().year}")

st.markdown("<h1 class='hero-title'>🏛️ Institutional Research Terminal</h1>", unsafe_allow_html=True)
st.markdown("<p class='hero-subtitle'>Dynamic Quantitative Auditor & Multi-Asset Valuation Architecture</p>", unsafe_allow_html=True)

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
        
        tab1, tab2, tab3, tab4, tab5 = st.tabs(["📊 Matrix", "🕵️ Deep-Dive", "📈 Visuals", "🚨 Risk Audit", "📄 Export Report"])

        # ─────────────────────────────────────────────────────────────────────────
        # TAB 1: MASTER QUANTITATIVE MATRIX
        # ─────────────────────────────────────────────────────────────────────────
        with tab1:
            st.subheader("Master Quantitative Grid")
            
            disp_df = df.copy()
            st.dataframe(
                disp_df[[
                    "Company", "Sector_Type", "Market Cap", "Sales", "Net Profit", 
                    "PE", "ROE %", "ROCE %", "D/E", "Interest Coverage", 
                    "FCF Yield %", "Piotroski", "Altman Z", "Zone"
                ]].style.format({
                    "Market Cap": "₹{:,.0f}Cr", 
                    "Sales": "₹{:,.0f}Cr", 
                    "Net Profit": "₹{:,.0f}Cr",
                    "PE": lambda x: f"{x:.1f}x" if x > 0 else "N/A (Loss)",
                    "ROE %": "{:.1f}%",
                    "ROCE %": "{:.1f}%", 
                    "D/E": "{:.2f}", 
                    "Interest Coverage": lambda x: f"{x:.1f}x" if isinstance(x, (int, float)) and x < 990 else ("Debt Free" if isinstance(x, (int, float)) else "N/A"),
                    "FCF Yield %": "{:.1f}%", 
                    "Altman Z": lambda x: f"{x:.2f}" if isinstance(x, (int, float)) else "N/A"
                }).background_gradient(subset=["Piotroski"], cmap="RdYlGn"),
                use_container_width=True
            )

        # ─────────────────────────────────────────────────────────────────────────
        # TAB 2: STRATEGIC DEEP-DIVE & KPI CARDS
        # ─────────────────────────────────────────────────────────────────────────
        with tab2:
            st.subheader("Strategic Cohort Leaders & Qualitative Deep-Dive")
            
            # KPI Cards Row
            kpi_col1, kpi_col2, kpi_col3 = st.columns(3)
            
            # 1. Highest ROE Leader
            valid_roe_df = df.dropna(subset=["ROE %"])
            if not valid_roe_df.empty:
                top_roe = valid_roe_df.loc[valid_roe_df["ROE %"].idxmax()]
                kpi_col1.metric("🏆 Cohort ROE Leader", f"{top_roe['Company']}", f"{top_roe['ROE %']:.1f}% ROE")
            
            # 2. Lowest Valuation P/E (Profitable companies only)
            profitable_df = df[df["PE"] > 0]
            if not profitable_df.empty:
                lowest_pe = profitable_df.loc[profitable_df["PE"].idxmin()]
                kpi_col2.metric("💎 Lowest Valuation (P/E)", f"{lowest_pe['Company']}", f"{lowest_pe['PE']:.1f}x P/E")
            else:
                kpi_col2.metric("💎 Lowest Valuation (P/E)", "N/A", "No Profitable Stocks")
                
            # 3. Safest Altman Z Score (Non-financials)
            industrial_df = df[df["Altman Z"].notnull()]
            if not industrial_df.empty:
                safest_z = industrial_df.loc[industrial_df["Altman Z"].idxmax()]
                kpi_col3.metric("🛡️ Safest Solvency (Altman Z)", f"{safest_z['Company']}", f"Z-Score {safest_z['Altman Z']:.2f}")
            else:
                kpi_col3.metric("🛡️ Safest Solvency (Altman Z)", "Banking Cohort", "N/A (Financials)")

            st.divider()

            selection = st.multiselect(
                "Select Companies for Comparative Analysis:", 
                df["Company"].unique(), 
                default=df["Company"].unique()[:min(4, len(df))]
            )
            
            if selection:
                subset = df[df["Company"].isin(selection)]
                for _, row in subset.iterrows():
                    with st.expander(f"Strategic Research Note: {row['Company']} ({row['Sector_Type']})", expanded=True):
                        c1, c2 = st.columns([1, 2.2])
                        
                        with c1:
                            st.metric("Piotroski Quality", f"{row['Piotroski']}/8")
                            st.metric("ROE / ROCE", f"{row['ROE %']:.1f}% / {row['ROCE %']:.1f}%")
                            st.metric("FCF Yield", f"{row['FCF Yield %']:.1f}%")
                            
                        with c2:
                            ic_text = f"{row['Interest Coverage']:.1f}x" if isinstance(row['Interest Coverage'], (int, float)) and row['Interest Coverage'] < 990 else ("Debt-Free" if isinstance(row['Interest Coverage'], (int, float)) else "N/A (Financial)")
                            pe_text = f"{row['PE']:.1f}x" if row['PE'] > 0 else "N/A (Loss-Making)"
                            z_text = f"{row['Altman Z']:.2f} ({row['Zone']})" if row['Altman Z'] is not None else "N/A (Financial Entity)"
                            
                            st.markdown(f"""
                            **Institutional Equity Thesis:**  
                            **{row['Company']}** is operating as a **{row['Sector_Type']}**. The company trades at a P/E valuation of **{pe_text}** with a Free Cash Flow (FCF) yield of **{row['FCF Yield %']:.1f}%**.  
                            
                            - **Capital Efficiency:** Delivers an ROE of **{row['ROE %']:.1f}%** and a Return on Capital Employed (ROCE) of **{row['ROCE %']:.1f}%**.  
                            - **Solvency & Coverage:** Leverage (D/E) stands at **{row['D/E']:.2f}** with an Interest Coverage ratio of **{ic_text}**. Solvency health zone is categorized as **{z_text}**.  
                            - **Growth & Quality:** 3-Year Sales CAGR of **{row['3Yr Sales CAGR %']:.1f}%** and PAT CAGR of **{row['3Yr PAT CAGR %']:.1f}%**, achieving a Piotroski F-Score of **{row['Piotroski']}/8**.
                            """)

        # ─────────────────────────────────────────────────────────────────────────
        # TAB 3: VISUAL ANALYTICS (PLOTLY)
        # ─────────────────────────────────────────────────────────────────────────
        with tab3:
            st.subheader("Visual Analytics & Cohort Benchmarking")
            
            c1, c2 = st.columns(2)
            
            with c1:
                scatter_df = df.copy()
                scatter_df["Plot_PE"] = scatter_df["PE"].apply(lambda x: min(x, max_pe_bound) if x > 0 else 0)
                scatter_df["PE_Label"] = scatter_df["PE"].apply(lambda x: f"{x:.1f}x" if x > 0 else "Negative P/E")

                fig1 = px.scatter(
                    scatter_df, 
                    x="Plot_PE", 
                    y="OPM %", 
                    size="Market Cap", 
                    color="Zone",
                    hover_name="Company",
                    hover_data={
                        "Plot_PE": False,
                        "PE_Label": True,
                        "ROE %": ":.1f%",
                        "Piotroski": True,
                        "Sector_Type": True
                    },
                    title=f"Valuation (P/E) vs. Profitability (OPM/Margin %) [Max Axis: {max_pe_bound}x]",
                    color_discrete_map={
                        "Safe": "#10b981", 
                        "Grey": "#f59e0b", 
                        "Distress": "#ef4444", 
                        "N/A (Financial)": "#3b82f6"
                    }
                )
                
                fig1.update_layout(
                    template="plotly_dark",
                    xaxis_title="P/E Ratio (Capped Bounds)",
                    yaxis_title="Margin / Profitability %",
                    xaxis=dict(range=[-5, max_pe_bound + 10])
                )
                st.plotly_chart(fig1, use_container_width=True)
                st.caption("ℹ️ Note: P/E axis is bounded between -5x and user-defined limit to prevent extreme valuation outliers from compressing the visual.")

            with c2:
                bar_companies = selection if selection else df['Company'].tolist()
                bar_df = df[df['Company'].isin(bar_companies)]
                
                fig2 = go.Figure()
                fig2.add_trace(go.Bar(
                    x=bar_df['Company'], 
                    y=bar_df['Piotroski'], 
                    name='Piotroski F-Score (0-8)',
                    marker_color='#10b981'
                ))
                fig2.add_trace(go.Bar(
                    x=bar_df['Company'], 
                    y=[z if z is not None else 0 for z in bar_df['Altman Z']], 
                    name='Altman Z-Score',
                    marker_color='#3b82f6'
                ))
                fig2.update_layout(
                    title="Fundamental Quality (Piotroski) vs. Solvency (Altman Z)",
                    barmode='group',
                    template="plotly_dark",
                    yaxis_title="Score / Z-Value"
                )
                st.plotly_chart(fig2, use_container_width=True)

        # ─────────────────────────────────────────────────────────────────────────
        # TAB 4: AUTOMATED RISK AUDITOR
        # ─────────────────────────────────────────────────────────────────────────
        with tab4:
            st.subheader("🚨 Automated Forensic & Risk Auditor")
            
            for _, row in df.iterrows():
                st.write(f"### {row['Company']} <span class='sector-badge'>{row['Sector_Type']}</span>", unsafe_allow_html=True)
                cols = st.columns(4)
                
                # 1. Cash Conversion Risk
                if row['Net Profit'] > 0 and row['FCF'] < 0:
                    cols[0].error("⚠️ Cash Conversion\nNegative FCF despite PAT.")
                else: 
                    cols[0].success("✅ Cash Flow OK")

                # 2. Solvency Risk
                if not row['Is_Financial']:
                    ic_val = row['Interest Coverage'] if isinstance(row['Interest Coverage'], (int, float)) else 999
                    if row['D/E'] > 1.5 and ic_val < 2.5:
                        cols[1].error("⚠️ Solvency Risk\nHigh Debt / Low Coverage.")
                    else: 
                        cols[1].success("✅ Solvency OK")
                else:
                    if row['D/E'] > 8.0:
                        cols[1].warning("⚠️ High Banking Leverage\nD/E > 8.0x")
                    else:
                        cols[1].success("✅ Banking Leverage OK")

                # 3. Accrual Risk
                if not row['Is_Financial'] and row['Sloan %'] is not None:
                    if row['Sloan %'] > 10.0:
                        cols[2].warning("⚠️ Accrual Risk\nSloan Ratio > 10%.")
                    else: 
                        cols[2].success("✅ Accruals OK")
                else:
                    cols[2].info("ℹ️ Accruals N/A\nFinancial Entity")

                # 4. Execution Risk
                if not row['Is_Financial']:
                    if row['CWIP to Net Block %'] > 40.0:
                        cols[3].warning("⚠️ Execution Risk\nExtreme CWIP Level (>40%).")
                    else: 
                        cols[3].success("✅ Asset Health OK")
                else:
                    cols[3].info("ℹ️ Asset Health OK\nNo Physical CWIP")
                    
                st.divider()

        # ─────────────────────────────────────────────────────────────────────────
        # TAB 5: OFFLINE REPORT EXPORT
        # ─────────────────────────────────────────────────────────────────────────
        with tab5:
            st.subheader("📄 Institutional Research Export Engine")
            
            report = f"# INSTITUTIONAL EQUITY RESEARCH REPORT\n"
            report += f"Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            report += f"Total Companies Analyzed: {len(df)}\n\n"
            report += "=" * 80 + "\n\n"
            
            report += "## 1. COHORT SUMMARY GRID\n\n"
            report += dataframe_to_markdown_table(df[["Company", "Sector_Type", "Market Cap", "PE", "ROE %", "ROCE %", "D/E", "Piotroski", "Zone"]])
            report += "\n\n" + "=" * 80 + "\n\n"
            
            report += "## 2. STRATEGIC COMPANY NARRATIVES\n\n"
            for _, row in df.iterrows():
                report += f"### {row['Company']} ({row['Sector_Type']})\n"
                report += f"- **Market Cap:** ₹{row['Market Cap']:,.0f} Cr | **Valuation (P/E):** {row['PE']:.1f}x\n"
                report += f"- **ROE:** {row['ROE %']:.1f}% | **ROCE:** {row['ROCE %']:.1f}% | **FCF Yield:** {row['FCF Yield %']:.1f}%\n"
                report += f"- **Piotroski Quality Score:** {row['Piotroski']}/8 | **Solvency Zone:** {row['Zone']}\n"
                report += f"- **3-Yr Revenue CAGR:** {row['3Yr Sales CAGR %']:.1f}% | **3-Yr PAT CAGR:** {row['3Yr PAT CAGR %']:.1f}%\n\n"
            
            col_exp1, col_exp2 = st.columns(2)
            
            col_exp1.download_button(
                "📥 Download Institutional Research Report (.md)", 
                data=report, 
                file_name=f"Institutional_Terminal_Report_{datetime.now().strftime('%Y%m%d')}.md",
                mime="text/markdown"
            )
            
            zip_io = io.BytesIO()
            with zipfile.ZipFile(zip_io, 'w') as zf:
                for fname, content in raw_files: 
                    zf.writestr(f"Processed_{fname}", content)
            
            col_exp2.download_button(
                "📥 Download Ingestion Package (.zip)", 
                data=zip_io.getvalue(), 
                file_name="Ingested_Workbooks_Package.zip",
                mime="application/zip"
            )

else:
    st.info("👋 Upload Screener.in Excel exports in the sidebar to run quantitative analysis.")
