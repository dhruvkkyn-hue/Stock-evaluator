import streamlit as st
import pandas as pd
import openpyxl
import io
import zipfile
import time
import traceback
from datetime import datetime
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Tuple, Any
from concurrent.futures import ThreadPoolExecutor

# ─────────────────────────────────────────────────────────────────────────────
# 1. DATA MODELS (STRONG TYPING & INTEGRITY)
# ─────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class RawFinancials:
    """Stores extracted raw values from Excel with absolute integrity."""
    company_name: str
    is_financial: bool
    sector_type: str
    mcap: float
    sales: List[float]
    pat: List[float]
    pbt: List[float]
    op: List[float]
    interest: List[float]
    debt: List[float]
    equity: List[float]
    reserves: List[float]
    cfo: List[float]
    cfi: List[float]
    capex_raw: float
    cwip: float
    net_block: float
    liab: float
    assets: float
    receivables: float
    inventory: float

@dataclass(frozen=True)
class CompanyMetrics:
    """Stores calculated institutional-grade metrics."""
    company: str
    is_financial: bool
    sector_type: str
    mcap: float
    sales: float
    pat: float
    pe: float
    ev_ebitda: float
    opm_pct: float
    roe_pct: float
    roce_pct: float
    debt_to_equity: float
    interest_coverage: Optional[float]
    fcf: float
    fcf_yield_pct: float
    sloan_pct: Optional[float]
    altman_z: Optional[float]
    zone: str
    piotroski: int
    cwip_to_net_block_pct: float
    sales_cagr_3yr: float
    pat_cagr_3yr: float

# ─────────────────────────────────────────────────────────────────────────────
# 2. UI/UX: INSTITUTIONAL CSS INJECTION
# ─────────────────────────────────────────────────────────────────────────────

st.set_page_config(page_title="Institutional Equity Terminal", layout="wide", page_icon="💎")

def inject_custom_css():
    st.markdown("""
    <style>
        :root {
            --bg-dark: #0e1117;
            --card-bg: #161b22;
            --border-color: #30363d;
            --accent-emerald: #10b981;
            --accent-blue: #3b82f6;
        }
        .stApp { background-color: var(--bg-dark); color: #c9d1d9; }
        
        /* Metric Card Styling */
        div[data-testid="stMetric"] {
            background-color: var(--card-bg);
            border: 1px solid var(--border-color);
            padding: 20px;
            border-radius: 12px;
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.4);
        }
        
        h1, h2, h3 { font-family: 'Inter', sans-serif; font-weight: 800; color: #ffffff !important; }
        .hero-title { font-size: 2.5rem; background: linear-gradient(90deg, #ffffff, #94a3b8); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
        
        .signal-tag-strong-buy { background-color: rgba(16, 185, 129, 0.2); color: #10b981; padding: 8px 16px; border-radius: 8px; font-weight: 800; border: 1px solid #10b981; display: inline-block; }
        .signal-tag-accumulate { background-color: rgba(59, 130, 246, 0.2); color: #3b82f6; padding: 8px 16px; border-radius: 8px; font-weight: 800; border: 1px solid #3b82f6; display: inline-block; }
        .signal-tag-hold { background-color: rgba(245, 158, 11, 0.2); color: #f59e0b; padding: 8px 16px; border-radius: 8px; font-weight: 800; border: 1px solid #f59e0b; display: inline-block; }
        .signal-tag-avoid { background-color: rgba(239, 68, 68, 0.2); color: #ef4444; padding: 8px 16px; border-radius: 8px; font-weight: 800; border: 1px solid #ef4444; display: inline-block; }
    </style>
    """, unsafe_allow_html=True)

inject_custom_css()

# ─────────────────────────────────────────────────────────────────────────────
# 3. QUANT ENGINE: FROZEN MATHEMATICAL LOGIC
# ─────────────────────────────────────────────────────────────────────────────

def safe_float(val: Any, default: float = 0.0) -> float:
    if val is None: return default
    try:
        if isinstance(val, (int, float)): return float(val)
        s = str(val).replace(',', '').replace('₹', '').replace('Rs.', '').strip()
        if s.startswith('(') and s.endswith(')'): s = "-" + s[1:-1]
        return float(s) if s != '' else default
    except: return default

def safe_div(n: Optional[float], d: Optional[float], default: float = 0.0) -> float:
    try:
        n_val = float(n) if n is not None else 0.0
        d_val = float(d) if d is not None else 0.0
        return n_val / d_val if d_val != 0 else default
    except: return default

def calculate_cagr(series: List[float], years: int) -> float:
    if not series or len(series) < years + 1: return 0.0
    try:
        start_val, end_val = series[-(years + 1)], series[-1]
        if start_val <= 0 or end_val <= 0: return 0.0
        return ((end_val / start_val) ** (1 / years) - 1) * 100
    except: return 0.0

def find_row_series(ws, keywords: List[str]) -> List[float]:
    kw_lower = [k.lower() for k in keywords]
    for row in ws.iter_rows(min_row=1, max_row=ws.max_row, min_col=1, max_col=3):
        label = f"{str(row[0].value or '')} {str(row[1].value or '')} {str(row[2].value or '')}".lower()
        if any(k in label for k in kw_lower):
            row_idx = row[0].row
            series = []
            for c in range(2, ws.max_column + 1):
                val = ws.cell(row=row_idx, column=c).value
                if val is not None: series.append(safe_float(val))
            return series
    return []

# ─────────────────────────────────────────────────────────────────────────────
# 4. PERFORMANCE-OPTIMIZED INGESTION (CACHING & CONCURRENCY)
# ─────────────────────────────────────────────────────────────────────────────

@st.cache_data(show_spinner=False)
def process_workbook_core(file_bytes: bytes, filename: str) -> Optional[RawFinancials]:
    """Parses Excel into RawFinancials dataclass with frozen math rules."""
    wb = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True)
    ds_name = next((s for s in wb.sheetnames if "data sheet" in s.lower()), wb.sheetnames[0])
    ws = wb[ds_name]

    extracted_name = str(ws.cell(row=1, column=2).value or "").strip()
    company_name = extracted_name if extracted_name else filename.replace(".xlsx", "")

    data_map = {
        "mcap": ["Market Capitalization", "Market Cap"],
        "sales": ["Sales", "Revenue", "Interest Earned", "Total Revenue"],
        "op": ["Operating Profit", "EBITDA", "EBIT"],
        "pat": ["Net Profit", "PAT"],
        "pbt": ["Profit before tax", "PBT"],
        "interest": ["Interest", "Finance Costs"],
        "debt": ["Borrowings", "Total Debt"],
        "equity": ["Equity Share Capital"],
        "reserves": ["Reserves", "Other Equity"],
        "cfo": ["Cash from Operating", "CFO"],
        "cfi": ["Cash from Investing", "CFI"],
        "capex": ["Capital Expenditure", "Purchase of fixed assets"],
        "cwip": ["Capital Work in Progress", "CWIP"],
        "net_block": ["Net Block", "Fixed Assets"],
        "liab": ["Other Liabilities", "Total Liabilities"],
        "assets": ["Total Assets"],
        "receivables": ["Receivables", "Trade Receivables"],
        "inventory": ["Inventory", "Inventories"]
    }

    raw = {k: find_row_series(ws, v) for k, v in data_map.items()}
    
    # Financial Sector Logic
    ws_text_sample = "".join([str(ws.cell(row=r, column=c).value or "").lower() for r in range(1, 40) for c in range(1, 4)])
    is_fin = any(kw in ws_text_sample for kw in ["bank", "nbfc", "advances", "deposits", "nii"]) or \
             any(term in company_name.lower() for term in ["bank", "finance", "fin", "nbfc", "capital"])

    return RawFinancials(
        company_name=company_name, is_financial=is_fin, sector_type="Financial" if is_fin else "Industrial",
        mcap=raw["mcap"][-1] if raw["mcap"] else 0.0,
        sales=raw["sales"], pat=raw["pat"], pbt=raw["pbt"], op=raw["op"], interest=raw["interest"],
        debt=raw["debt"], equity=raw["equity"], reserves=raw["reserves"],
        cfo=raw["cfo"], cfi=raw["cfi"], 
        capex_raw=raw["capex"][-1] if raw["capex"] else 0.0,
        cwip=raw["cwip"][-1] if raw["cwip"] else 0.0,
        net_block=raw["net_block"][-1] if raw["net_block"] else 0.0,
        liab=raw["liab"][-1] if raw["liab"] else 0.0,
        assets=raw["assets"][-1] if raw["assets"] else 0.0,
        receivables=raw["receivables"][-1] if raw["receivables"] else 0.0,
        inventory=raw["inventory"][-1] if raw["inventory"] else 0.0
    )

def compute_metrics(raw: RawFinancials) -> CompanyMetrics:
    """Transmutes RawFinancials into CompanyMetrics with validated formulas."""
    curr_sales = raw.sales[-1] if raw.sales else 0.0
    curr_pat = raw.pat[-1] if raw.pat else 0.0
    curr_equity = (raw.equity[-1] if raw.equity else 0.0) + (raw.reserves[-1] if raw.reserves else 0.0)
    curr_debt = raw.debt[-1] if raw.debt else 0.0
    curr_cfo = raw.cfo[-1] if raw.cfo else 0.0
    
    # Valuation & FCF
    pe = safe_div(raw.mcap, curr_pat) if curr_pat > 0 else -1.0
    capex_val = raw.capex_raw if raw.capex_raw > 0 else (abs(raw.cfi[-1]) if raw.cfi else 0.0)
    fcf = curr_cfo - capex_val
    
    # Margins & Returns
    if raw.is_financial:
        local_ebit = raw.pbt[-1] if raw.pbt else curr_pat
        opm = safe_div(curr_pat, curr_sales) * 100
    else:
        local_ebit = (raw.pbt[-1] + raw.interest[-1]) if (raw.pbt and raw.interest) else (raw.op[-1] if raw.op else 0.0)
        opm = safe_div(raw.op[-1] if raw.op else 0.0, curr_sales) * 100

    roe = safe_div(curr_pat, curr_equity) * 100
    roce = safe_div(local_ebit, curr_equity + curr_debt) * 100

    # Altman Z (Frozen Formula)
    alt_z = None
    zone = "N/A (Financial)"
    if not raw.is_financial and raw.assets > 0:
        wc = (raw.receivables + raw.inventory + (raw.assets * 0.05)) - raw.liab
        alt_z = (1.2 * safe_div(wc, raw.assets)) + (1.4 * safe_div(raw.reserves[-1] if raw.reserves else 0.0, raw.assets)) + \
                (3.3 * safe_div(raw.op[-1] if raw.op else 0.0, raw.assets)) + (0.6 * safe_div(raw.mcap, curr_debt + raw.liab)) + \
                (0.99 * safe_div(curr_sales, raw.assets))
        zone = "Safe" if alt_z > 2.99 else "Grey" if alt_z >= 1.81 else "Distress"

    # Piotroski (Frozen Logic)
    p = 0
    if curr_pat > 0: p += 1
    if curr_cfo > 0: p += 1
    if curr_cfo > curr_pat: p += 1
    if calculate_cagr(raw.pat, 1) > 0: p += 1
    if raw.debt and len(raw.debt) > 1:
        prev_eq = (raw.equity[-2] if len(raw.equity) > 1 else 0.0) + (raw.reserves[-2] if len(raw.reserves) > 1 else 0.0)
        if safe_div(curr_debt, curr_equity) <= safe_div(raw.debt[-2], prev_eq): p += 1
    if roce > 12: p += 1
    if calculate_cagr(raw.sales, 1) > 0: p += 1
    if raw.assets > 0: p += 1

    return CompanyMetrics(
        company=raw.company_name, is_financial=raw.is_financial, sector_type=raw.sector_type,
        mcap=raw.mcap, sales=curr_sales, pat=curr_pat, pe=pe, 
        ev_ebitda=safe_div(raw.mcap + curr_debt, raw.op[-1] if raw.op else local_ebit),
        opm_pct=opm, roe_pct=roe, roce_pct=roce, debt_to_equity=safe_div(curr_debt, curr_equity),
        interest_coverage=safe_div(local_ebit, raw.interest[-1]) if not raw.is_financial and raw.interest else None,
        fcf=fcf, fcf_yield_pct=safe_div(fcf, raw.mcap) * 100,
        sloan_pct=safe_div(curr_pat - curr_cfo, raw.assets) * 100 if not raw.is_financial else None,
        altman_z=alt_z, zone=zone, piotroski=p,
        cwip_to_net_block_pct=safe_div(raw.cwip, raw.net_block) * 100,
        sales_cagr_3yr=calculate_cagr(raw.sales, 3), pat_cagr_3yr=calculate_cagr(raw.pat, 3)
    )

# ─────────────────────────────────────────────────────────────────────────────
# 5. UI COMPONENTS & TIERED INTERPRETATION
# ─────────────────────────────────────────────────────────────────────────────

def get_tier_content(m: CompanyMetrics, tier: str) -> Dict[str, str]:
    is_f = m.is_financial
    pe_tag = "[🟢 STRONG]" if (0 < m.pe < 22) else "[🟡 AVERAGE]" if m.pe < 45 else "[🔴 WEAK]"
    roe_tag = "[🟢 STRONG]" if m.roe_pct > 18 else "[🟡 AVERAGE]" if m.roe_pct > 12 else "[🔴 WEAK]"
    debt_tag = "[🟢 STRONG]" if (m.debt_to_equity < 0.6 or (is_f and m.debt_to_equity < 7)) else "[🔴 WEAK]"

    if tier == "🌱 Beginner Investor":
        return {
            "PE": f"**Status: {pe_tag}**\n- 💡 **What is this?** Like a price tag. A score of {m.pe:.1f} means for every ₹1 profit, you pay ₹{m.pe:.1f}.\n- ⚠️ **Warning:** A low number might mean the company is in trouble, not just 'cheap'.",
            "ROE": f"**Status: {roe_tag}**\n- 💡 **What is this?** This is like the interest rate the business earns on its own money. {m.roe_pct:.1f}% is solid.\n- ⚠️ **Warning:** If a company borrows too much, this number looks fake-high.",
            "DE": f"**Status: {debt_tag}**\n- 💡 **What is this?** Comparing bank loans to the company's own cash. {m.debt_to_equity:.2f} measures 'heaviness'.",
            "PIO": f"**Status: {m.piotroski}/8**\n- 💡 **What is this?** A 9-point report card. High scores mean the business is getting healthier every year."
        }
    elif tier == "📈 Intermediate Investor":
        return {
            "PE": f"- **Practical View:** Trading at {m.pe:.1f}x earnings. Check if this is below the 5-year sector average.\n- **Significance:** Measures valuation premium vs growth expectations.",
            "ROE": f"- **Practical View:** Generating {m.roe_pct:.1f}% return on shareholder equity.\n- **Significance:** Core measure of internal capital efficiency and compounding power.",
            "DE": f"- **Practical View:** D/E at {m.debt_to_equity:.2f}.\n- **Significance:** Essential for understanding solvency. Industrials should ideally stay < 1.0x.",
            "PIO": f"- **Practical View:** Piotroski F-Score: {m.piotroski}/8.\n- **Significance:** Validates fundamental momentum across liquidity and operating efficiency."
        }
    else: # Institutional
        return {
            "PE": f"- **Quant Logic:** P/E of {m.pe:.1f}x. Earnings Yield: {safe_div(1, m.pe)*100:.2f}%.\n- **Note:** Standard TTM multiple for exit-multiple modeling.",
            "ROE": f"- **Quant Logic:** ROE at {m.roe_pct:.1f}%. Decomposition: Margin x Turnover x Leverage.\n- **Note:** Key driver of sustainable growth rate (g = ROE * b).",
            "DE": f"- **Quant Logic:** Gearing at {m.debt_to_equity:.2f}. Capital structure check.\n- **Note:** Critical risk input for WACC and cost-of-equity calculations.",
            "PIO": f"- **Quant Logic:** F-Score of {m.piotroski}. Binary assessment of fundamental momentum.\n- **Note:** High correlation with lower probability of financial misstatement."
        }

def get_action_verdict(m: CompanyMetrics) -> Tuple[str, str]:
    score = 0
    if m.roe_pct >= 15: score += 1
    if 0 < m.pe <= 25: score += 1
    if (m.debt_to_equity <= 0.8 or (m.is_financial and m.debt_to_equity <= 7)): score += 1
    if m.piotroski >= 6: score += 1
    if m.fcf_yield_pct >= 3: score += 1
    if m.zone == "Safe": score += 1

    if score >= 5: return "STRONG BUY", "signal-tag-strong-buy"
    if score >= 3: return "ACCUMULATE ON DIPS", "signal-tag-accumulate"
    if score >= 2: return "HOLD / WATCHLIST", "signal-tag-hold"
    return "AVOID / EXIT", "signal-tag-avoid"

# ─────────────────────────────────────────────────────────────────────────────
# 6. MAIN APPLICATION EXECUTION
# ─────────────────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("## 📂 Batch Ingestion")
    uploads = st.file_uploader("Upload Screener Excels", type=["xlsx"], accept_multiple_files=True)
    st.divider()
    st.markdown("## 🏛️ Strategy Tier")
    complexity = st.radio("Analysis Complexity:", ["🌱 Beginner Investor", "📈 Intermediate Investor", "🏛️ Pro / Institutional Analyst"])
    st.divider()
    max_pe_bound = st.slider("Plot Max P/E Axis", 50, 300, 150)
    st.caption(f"Terminal v7.0 Unification | {datetime.now().year}")

st.markdown("<h1 class='hero-title'>🏛️ Institutional Research Terminal</h1>", unsafe_allow_html=True)

if uploads:
    start_time = time.time()
    results: List[CompanyMetrics] = []
    raw_package: List[Tuple[str, bytes]] = []

    def batch_worker(up) -> Optional[CompanyMetrics]:
        try:
            raw = process_workbook_core(up.getvalue(), up.name)
            return compute_metrics(raw) if raw else None
        except: return None

    with ThreadPoolExecutor() as executor:
        metrics_list = list(executor.map(batch_worker, uploads))
        
    for m in metrics_list:
        if m: results.append(m)

    processing_time = time.time() - start_time
    st.toast(f"⚡ Analyzed {len(results)} companies in {processing_time:.2f}s", icon="🚀")

    if results:
        df = pd.DataFrame([m.__dict__ for m in results])
        
        # --- 1. TOP KPI DASHBOARD ---
        st.subheader("🏆 Cohort Performance Leaders")
        k1, k2, k3 = st.columns(3)
        k1.metric("ROE Leader", df.loc[df["roe_pct"].idxmax(), "company"], f"{df['roe_pct'].max():.1f}%")
        k2.metric("Valuation Leader (P/E)", df.loc[df[df["pe"]>0]["pe"].idxmin(), "company"], f"{df[df['pe']>0]['pe'].min():.1f}x")
        valid_z = df[df["altman_z"].notnull()]
        if not valid_z.empty:
            k3.metric("Solvency Leader", valid_z.loc[valid_z["altman_z"].idxmax(), "company"], f"Z-Score {valid_z['altman_z'].max():.2f}")

        # --- 2. MULTI-TAB ARCHITECTURE ---
        t1, t2, t3, t4, t5 = st.tabs([
            "📊 Metric Deep-Dive", "🏛️ Bull & Bear Thesis", "🚦 Action Triggers", "🛡️ Risk Auditor", "📈 Visual Matrix"
        ])

        with t1:
            target = st.selectbox("Select Analysis Target:", df["company"].unique())
            row = next(r for r in results if r.company == target)
            c = get_tier_content(row, complexity)
            
            col_a, col_b = st.columns(2)
            with col_a:
                with st.expander("▸ Group 1: Valuation & Margins", expanded=True):
                    st.markdown(f"**P/E Ratio**\n{c['PE']}")
                    st.markdown(f"**Operating Margin (OPM %)**\nValue: {row.opm_pct:.1f}%")
            with col_b:
                with st.expander("▸ Group 2: Efficiency & Safety", expanded=True):
                    st.markdown(f"**Return on Equity (ROE %)**\n{c['ROE']}")
                    st.markdown(f"**Debt-to-Equity**\n{c['DE']}")
                    st.markdown(f"**Fundamental Quality**\n{c['PIO']}")

        with t2:
            sel_comp = st.multiselect("Compare Thesis:", df["company"].unique(), default=df["company"].unique()[:2])
            if sel_comp:
                cols = st.columns(len(sel_comp))
                for i, name in enumerate(sel_comp):
                    r = next(item for item in results if item.company == name)
                    v_text, v_css = get_action_verdict(r)
                    with cols[i]:
                        st.markdown(f"<div class='{v_css}'>{v_text}</div>", unsafe_allow_html=True)
                        st.markdown(f"### {r.company}")
                        st.success(f"**🟢 Bull Case:**\n- ROE: {r.roe_pct:.1f}%\n- Piotroski: {r.piotroski}/8\n- Status: {r.zone}")
                        st.error(f"**🔴 Bear Case:**\n- P/E: {r.pe:.1f}x\n- Gearing: {r.debt_to_equity:.2f}\n- FCF Yield: {r.fcf_yield_pct:.1f}%")

        with t3:
            if sel_comp:
                cols = st.columns(len(sel_comp))
                for i, name in enumerate(sel_comp):
                    r = next(item for item in results if item.company == name)
                    with cols[i]:
                        st.info(f"**🎯 BUY Trigger:**\nP/E falls below {r.pe*0.85:.1f}x while ROCE holds >15%.")
                        st.warning(f"**⚠️ SELL Trigger:**\nExit if F-Score < 4 or D/E > {r.debt_to_equity*1.4:.2f}.")
                        st.write(f"**🔄 Catalyst:** Monitor Asset Turnover and CWIP ({r.cwip_to_net_block_pct:.1f}% block).")

        with t4:
            for _, r in df.iterrows():
                with st.expander(f"Forensic Audit: {r['company']}"):
                    c1, c2, c3, c4 = st.columns(4)
                    if r['pat'] > 0 and r['fcf'] < 0: c1.error("❌ Cash Burn")
                    else: c1.success("✅ Cash Flow OK")
                    if not r['is_financial']:
                        if r['debt_to_equity'] > 1.2: c2.error("❌ High Gearing")
                        else: c2.success("✅ Leverage OK")
                        if r['sloan_pct'] and r['sloan_pct'] > 10: c3.warning("⚠️ High Accruals")
                        else: c3.success("✅ Clean Accruals")
                        if r['altman_z'] and r['altman_z'] < 1.8: c4.error("❌ Solvency Risk")
                        else: c4.success("✅ Solvent")
                    else: st.info("🏦 Financial: Check Capital Adequacy Ratios.")

        with t5:
            st.subheader("Performance vs Valuation Matrix")
            df["PlotPE"] = df["pe"].apply(lambda x: min(x, max_pe_bound) if x > 0 else 0)
            fig = px.scatter(df, x="PlotPE", y="roe_pct", size="mcap", color="zone", hover_name="company", template="plotly_dark")
            st.plotly_chart(fig, use_container_width=True)

        # --- 3. EXPORT MODULE ---
        st.divider()
        report_md = f"# RESEARCH REPORT: {complexity}\nGenerated: {datetime.now()}\n\n"
        report_md += df[["company", "pe", "roe_pct", "debt_to_equity", "zone", "piotroski"]].to_markdown()
        
        st.download_button("📥 Download Report (.md)", data=report_md, file_name=f"Report_{datetime.now().strftime('%Y%m%d')}.md")
        
        zip_io = io.BytesIO()
        with zipfile.ZipFile(zip_io, 'w') as zf:
            for up in uploads: zf.writestr(f"Processed_{up.name}", up.getvalue())
        st.download_button("📥 Download ZIP Package", data=zip_io.getvalue(), file_name="Institutional_Package.zip")

else:
    st.info("👋 Upload Screener.in Excel exports to begin quantitative research.")
