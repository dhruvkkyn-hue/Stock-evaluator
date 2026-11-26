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
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            font-weight: 700;
        }
        
        .hero-banner {
            background: linear-gradient(135deg, #1f2937 0%, #111827 100%);
            border: 1px solid #374151;
            border-radius: 12px;
            padding: 24px;
            margin-bottom: 25px;
            box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.5);
        }
        .hero-title {
            font-size: 2.3rem;
            font-weight: 800;
            background: linear-gradient(90deg, #ffffff, #94a3b8);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            margin-bottom: 6px;
        }
        .hero-subtitle {
            color: #9ca3af;
            font-size: 1.05rem;
            margin-bottom: 0px;
        }

        .exec-card {
            background: #161b22;
            border: 1px solid #30363d;
            border-radius: 12px;
            padding: 22px;
            margin-bottom: 24px;
            box-shadow: 0 6px 16px rgba(0, 0, 0, 0.4);
        }
        .verdict-banner {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 14px 20px;
            border-radius: 8px;
            margin-bottom: 20px;
            font-weight: 700;
            font-size: 1.15rem;
        }
        .verdict-strong-buy { background: rgba(16, 185, 129, 0.15); border: 1px solid #10b981; color: #10b981; }
        .verdict-moderate-buy { background: rgba(59, 130, 246, 0.15); border: 1px solid #3b82f6; color: #3b82f6; }
        .verdict-hold { background: rgba(245, 158, 11, 0.15); border: 1px solid #f59e0b; color: #f59e0b; }
        .verdict-avoid { background: rgba(239, 68, 68, 0.15); border: 1px solid #ef4444; color: #ef4444; }

        .stat-badge {
            background: #21262d;
            border: 1px solid #30363d;
            border-radius: 6px;
            padding: 10px 14px;
            text-align: center;
        }
        .stat-label { font-size: 0.8rem; color: #8b949e; text-transform: uppercase; margin-bottom: 4px; }
        .stat-value { font-size: 1.15rem; font-weight: 700; color: #ffffff; }

        .explainer-box {
            background: #1c2128;
            border-left: 4px solid #3b82f6;
            padding: 14px 18px;
            border-radius: 0 8px 8px 0;
            margin: 12px 0 20px 0;
            font-size: 0.95rem;
            color: #adbac7;
        }

        .pillar-header {
            font-size: 1.1rem;
            font-weight: 700;
            color: #f0f6fc;
            margin-bottom: 8px;
            display: flex;
            align-items: center;
            gap: 8px;
        }
        
        .tag-pill {
            display: inline-block;
            padding: 2px 8px;
            border-radius: 12px;
            font-size: 0.75rem;
            font-weight: 600;
            margin-right: 6px;
        }
        .tag-safe { background: #064e3b; color: #6ee7b7; border: 1px solid #059669; }
        .tag-warning { background: #78350f; color: #fde68a; border: 1px solid #d97706; }
        .tag-danger { background: #7f1d1d; color: #fca5a5; border: 1px solid #dc2626; }
        .tag-neutral { background: #1f2937; color: #9ca3af; border: 1px solid #4b5563; }
    </style>
    """, unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────────────
# 2. QUANT ENGINE: SAFE MATH & FINANCIAL SECTOR PARSING
# ─────────────────────────────────────────────────────────────────────────────
def safe_float(val, default=0.0):
    if val is None or pd.isna(val):
        return default
    try:
        if isinstance(val, (int, float)):
            return float(val)
        clean = re.sub(r'[^\d.-]', '', str(val).strip())
        return float(clean) if clean and clean != '-' else default
    except (ValueError, TypeError):
        return default

def safe_div(numerator, denominator, default=0.0):
    try:
        num = safe_float(numerator)
        den = safe_float(denominator)
        return num / den if den != 0.0 else default
    except (ZeroDivisionError, TypeError, ValueError):
        return default

def calculate_cagr(start_val, end_val, periods):
    try:
        s = safe_float(start_val)
        e = safe_float(end_val)
        p = safe_float(periods)
        if s > 0 and e > 0 and p > 0:
            return ((e / s) ** (1.0 / p) - 1.0) * 100.0
        return None
    except Exception:
        return None

def detect_financial_entity(company_name, sheet_names, all_text_blobs):
    name_lower = str(company_name).lower()
    fin_name_kws = ['bank', 'nbfc', 'finance', 'financial', 'housing finance', 'capital services', 'investments']
    if any(kw in name_lower for kw in fin_name_kws):
        return True
    
    blob_str = " ".join([str(s).lower() for s in sheet_names] + [str(b).lower() for b in all_text_blobs])
    fin_terms = ['advances', 'deposits', 'nii', 'net interest income', 'interest earned', 'provisions', 'npa']
    term_hits = sum(1 for term in fin_terms if term in blob_str)
    return term_hits >= 2

def get_row_by_keywords(df, keywords):
    if df is None or df.empty:
        return None
    col0 = df.iloc[:, 0].astype(str).str.strip().str.lower()
    for kw in keywords:
        kw_lower = kw.lower()
        matched = df[col0.str.contains(kw_lower, regex=False, na=False)]
        if not matched.empty:
            return matched.iloc[0]
    return None

def parse_time_series_row(row_series):
    if row_series is None or len(row_series) < 2:
        return []
    values = []
    for val in row_series.iloc[1:]:
        clean = str(val).strip() if pd.notna(val) else ""
        if clean != "":
            values.append(safe_float(clean))
    return values

def extract_financial_data(wb, filename):
    sheet_names = wb.sheetnames
    all_text_blobs = []
    
    extracted_sheets = {}
    for sname in sheet_names:
        sheet = wb[sname]
        data = list(sheet.iter_rows(values_only=True))
        if data:
            df = pd.DataFrame(data)
            df = df.dropna(how='all').reset_index(drop=True)
            extracted_sheets[sname] = df
            text_sample = " ".join(df.astype(str).values.flatten()[:100])
            all_text_blobs.append(text_sample)

    company_name = filename.replace(".xlsx", "").replace(".xls", "").strip()
    cmp = 0.0
    shares = 0.0

    for sname, df in extracted_sheets.items():
        if df.shape[1] >= 2:
            col0 = df.iloc[:, 0].astype(str).str.lower()
            if "company" in col0.values:
                idx = col0[col0 == "company"].index[0]
                val = str(df.iloc[idx, 1]).strip()
                if val: company_name = val
            for idx, cell in enumerate(col0):
                if "current price" in str(cell) or "cmp" in str(cell):
                    cmp = safe_float(df.iloc[idx, 1])
                if "shares" in str(cell) or "no. of shares" in str(cell):
                    shares = safe_float(df.iloc[idx, 1])

    is_fin = detect_financial_entity(company_name, sheet_names, all_text_blobs)

    pl_df = None
    bs_df = None
    cf_df = None

    for sname in sheet_names:
        s_low = sname.lower()
        if 'profit' in s_low or 'p&l' in s_low or 'income' in s_low:
            pl_df = extracted_sheets[sname]
        elif 'balance' in s_low or 'b&s' in s_low:
            bs_df = extracted_sheets[sname]
        elif 'cash' in s_low or 'cfo' in s_low:
            cf_df = extracted_sheets[sname]

    if pl_df is None and "Data Sheet" in extracted_sheets:
        pl_df = extracted_sheets["Data Sheet"]
    if bs_df is None and "Data Sheet" in extracted_sheets:
        bs_df = extracted_sheets["Data Sheet"]
    if cf_df is None and "Data Sheet" in extracted_sheets:
        cf_df = extracted_sheets["Data Sheet"]

    sales_ts = parse_time_series_row(get_row_by_keywords(pl_df, ['sales', 'revenue', 'interest earned']))
    ebitda_ts = parse_time_series_row(get_row_by_keywords(pl_df, ['operating profit', 'ebitda', 'financing profit']))
    pbt_ts = parse_time_series_row(get_row_by_keywords(pl_df, ['profit before tax', 'pbt']))
    pat_ts = parse_time_series_row(get_row_by_keywords(pl_df, ['net profit', 'pat']))
    interest_ts = parse_time_series_row(get_row_by_keywords(pl_df, ['interest', 'finance cost']))
    depr_ts = parse_time_series_row(get_row_by_keywords(pl_df, ['depreciation', 'amortization']))

    eq_ts = parse_time_series_row(get_row_by_keywords(bs_df, ['equity share capital', 'equity capital', 'share capital']))
    reserves_ts = parse_time_series_row(get_row_by_keywords(bs_df, ['reserves', 'retained earnings']))
    debt_ts = parse_time_series_row(get_row_by_keywords(bs_df, ['borrowings', 'total debt', 'debt']))
    assets_ts = parse_time_series_row(get_row_by_keywords(bs_df, ['total assets', 'balance sheet total']))
    cwip_ts = parse_time_series_row(get_row_by_keywords(bs_df, ['cwip', 'work in progress']))
    net_block_ts = parse_time_series_row(get_row_by_keywords(bs_df, ['net block', 'fixed assets', 'property plant']))
    rec_ts = parse_time_series_row(get_row_by_keywords(bs_df, ['trade receivables', 'receivables']))

    cfo_ts = parse_time_series_row(get_row_by_keywords(cf_df, ['cash from operating activity', 'operating activity', 'cfo']))
    cfi_ts = parse_time_series_row(get_row_by_keywords(cf_df, ['cash from investing activity', 'investing activity', 'cfi']))
    capex_row = get_row_by_keywords(cf_df, ['fixed assets purchased', 'capital expenditure', 'capex'])
    capex_ts = [abs(x) for x in parse_time_series_row(capex_row)] if capex_row is not None else []

    curr_sales = sales_ts[-1] if sales_ts else 0.0
    prev_sales = sales_ts[-2] if len(sales_ts) >= 2 else curr_sales
    s3_sales = sales_ts[-4] if len(sales_ts) >= 4 else (sales_ts[0] if sales_ts else 0.0)

    curr_pat = pat_ts[-1] if pat_ts else 0.0
    prev_pat = pat_ts[-2] if len(pat_ts) >= 2 else curr_pat
    s3_pat = pat_ts[-4] if len(pat_ts) >= 4 else (pat_ts[0] if pat_ts else 0.0)

    curr_pbt = pbt_ts[-1] if pbt_ts else 0.0
    curr_int = interest_ts[-1] if interest_ts else 0.0
    curr_depr = depr_ts[-1] if depr_ts else 0.0
    curr_ebitda = ebitda_ts[-1] if ebitda_ts else (curr_pbt + curr_int + curr_depr)
    
    if is_fin:
        curr_ebit = curr_pbt if curr_pbt != 0.0 else curr_pat
    else:
        curr_ebit = curr_pbt + curr_int

    curr_eq = eq_ts[-1] if eq_ts else 0.0
    curr_res = reserves_ts[-1] if reserves_ts else 0.0
    net_worth = curr_eq + curr_res
    prev_nw = (eq_ts[-2] + reserves_ts[-2]) if len(eq_ts) >= 2 and len(reserves_ts) >= 2 else net_worth
    
    curr_debt = debt_ts[-1] if debt_ts else 0.0
    prev_debt = debt_ts[-2] if len(debt_ts) >= 2 else curr_debt
    
    curr_assets = assets_ts[-1] if assets_ts else (net_worth + curr_debt)
    prev_assets = assets_ts[-2] if len(assets_ts) >= 2 else curr_assets
    if curr_assets == 0.0:
        curr_assets = 1.0

    curr_cwip = cwip_ts[-1] if cwip_ts else 0.0
    curr_nb = net_block_ts[-1] if net_block_ts else 0.0
    curr_rec = rec_ts[-1] if rec_ts else 0.0
    prev_rec = rec_ts[-2] if len(rec_ts) >= 2 else curr_rec

    curr_cfo = cfo_ts[-1] if cfo_ts else 0.0
    curr_cfi = cfi_ts[-1] if cfi_ts else 0.0
    curr_capex = capex_ts[-1] if capex_ts else abs(curr_cfi)
    curr_fcf = curr_cfo - curr_capex

    mcap = (cmp * shares) if (cmp > 0 and shares > 0) else (net_worth * 1.5 if net_worth > 0 else 1000.0)
    pe = safe_div(mcap, curr_pat) if curr_pat > 0 else None
    
    opm = safe_div(curr_ebitda, curr_sales) * 100.0 if not is_fin else safe_div(curr_pat, curr_sales) * 100.0
    net_margin = safe_div(curr_pat, curr_sales) * 100.0
    
    roe = safe_div(curr_pat, net_worth) * 100.0
    cap_employed = net_worth + curr_debt
    roce = safe_div(curr_ebit, cap_employed) * 100.0
    
    if curr_int > 0:
        int_coverage = safe_div(curr_ebit, curr_int)
    else:
        int_coverage = 999.0 if curr_debt == 0 else safe_div(curr_ebit, 1.0)
        
    de_ratio = safe_div(curr_debt, net_worth)
    fcf_yield = safe_div(curr_fcf, mcap) * 100.0

    p_score = 0
    if curr_pat > 0: p_score += 1
    if curr_cfo > 0: p_score += 1
    roa_curr = safe_div(curr_pat, curr_assets)
    roa_prev = safe_div(prev_pat, prev_assets)
    if roa_curr > roa_prev: p_score += 1
    if curr_cfo > curr_pat: p_score += 1
    if curr_debt <= prev_debt: p_score += 1
    if safe_div(curr_pat, curr_sales) > safe_div(prev_pat, prev_sales): p_score += 1
    if safe_div(curr_sales, curr_assets) >= safe_div(prev_sales, prev_assets): p_score += 1
    if safe_div(curr_cfo, curr_assets) > 0.05: p_score += 1

    if not is_fin:
        x1 = 0.2
        x2 = safe_div(curr_res, curr_assets)
        x3 = safe_div(curr_ebit, curr_assets)
        x4 = safe_div(net_worth, curr_debt) if curr_debt > 0 else 5.0
        x5 = safe_div(curr_sales, curr_assets)
        altman_z = (1.2 * x1) + (1.4 * x2) + (3.3 * x3) + (0.6 * x4) + (1.0 * x5)
        if altman_z >= 2.99:
            z_zone = "Safe"
        elif altman_z >= 1.81:
            z_zone = "Grey"
        else:
            z_zone = "Distress"
    else:
        altman_z = None
        z_zone = "Financial Entity (Exempt)"

    if not is_fin and curr_assets > 0:
        sloan_ratio = (curr_pat - curr_cfo) / curr_assets
    else:
        sloan_ratio = 0.0

    sales_cagr_3yr = calculate_cagr(s3_sales, curr_sales, 3)
    pat_cagr_3yr = calculate_cagr(s3_pat, curr_pat, 3)

    return {
        "Company": company_name,
        "Filename": filename,
        "Sector": "Banking & Financial Services" if is_fin else "Industrial & Commercial",
        "Is_Financial": is_fin,
        "CMP": cmp,
        "Market_Cap": mcap,
        "Sales": curr_sales,
        "EBITDA": curr_ebitda,
        "EBIT": curr_ebit,
        "PAT": curr_pat,
        "Interest": curr_int,
        "Net_Worth": net_worth,
        "Debt": curr_debt,
        "Total_Assets": curr_assets,
        "CFO": curr_cfo,
        "CapEx": curr_capex,
        "FCF": curr_fcf,
        "CWIP": curr_cwip,
        "Net_Block": curr_nb,
        "PE": pe,
        "OPM": opm,
        "Net_Margin": net_margin,
        "ROE": roe,
        "ROCE": roce,
        "Interest_Coverage": int_coverage,
        "DE_Ratio": de_ratio,
        "FCF_Yield": fcf_yield,
        "Piotroski_Score": p_score,
        "Altman_Z": altman_z,
        "Z_Zone": z_zone,
        "Sloan_Ratio": sloan_ratio,
        "Sales_CAGR_3Yr": sales_cagr_3yr,
        "PAT_CAGR_3Yr": pat_cagr_3yr,
        "Raw_Sales_TS": sales_ts,
        "Raw_PAT_TS": pat_ts
    }

# ─────────────────────────────────────────────────────────────────────────────
# 3. 3-TIER INVESTOR EXPERIENCE NARRATIVE ENGINE
# ─────────────────────────────────────────────────────────────────────────────
def generate_strategic_narrative(row, expertise_level):
    c = row["Company"]
    roe = row["ROE"]
    roce = row["ROCE"]
    de = row["DE_Ratio"]
    int_cov = row["Interest_Coverage"]
    fcf = row["FCF"]
    pat = row["PAT"]
    fcf_yield = row["FCF_Yield"]
    pe = row["PE"]
    f_score = row["Piotroski_Score"]
    z_score = row["Altman_Z"]
    z_zone = row["Z_Zone"]
    sloan = row["Sloan_Ratio"]
    is_fin = row["Is_Financial"]
    cwip = row["CWIP"]
    nb = row["Net_Block"]
    sales_cagr = row["Sales_CAGR_3Yr"]
    pat_cagr = row["PAT_CAGR_3Yr"]

    buy_points = 0
    risk_points = 0
    if roe > 15: buy_points += 2
    elif roe > 10: buy_points += 1
    else: risk_points += 1

    if not is_fin:
        if de < 0.5: buy_points += 2
        elif de < 1.0: buy_points += 1
        else: risk_points += 2
        if int_cov > 4.0: buy_points += 1
        elif int_cov < 2.0: risk_points += 2
    else:
        if roe > 14: buy_points += 2

    if fcf > 0: buy_points += 2
    else: risk_points += 1

    if f_score >= 6: buy_points += 2
    elif f_score <= 3: risk_points += 2

    if not is_fin and z_score is not None:
        if z_score >= 2.99: buy_points += 1
        elif z_score < 1.81: risk_points += 2

    if buy_points >= 6 and risk_points <= 2:
        verdict = "STRONG BUY (ACCUMULATE)"
        verdict_cls = "verdict-strong-buy"
        verdict_icon = "🟢"
        verdict_summary = "High-quality compounding candidate exhibiting strong capital efficiency and pristine balance sheet health."
    elif buy_points >= 4 and risk_points <= 3:
        verdict = "MODERATE BUY (SELECTIVE ALLOCATION)"
        verdict_cls = "verdict-moderate-buy"
        verdict_icon = "🔵"
        verdict_summary = "Healthy business fundamentals with reasonable safeguards, suitable for core portfolio allocation."
    elif risk_points >= 4:
        verdict = "HIGH RISK (AVOID / RE-EVALUATE)"
        verdict_cls = "verdict-avoid"
        verdict_icon = "🔴"
        verdict_summary = "Significant red flags identified across cash flow reality, high leverage, or solvency metrics."
    else:
        verdict = "NEUTRAL / HOLD (WATCHLIST)"
        verdict_cls = "verdict-hold"
        verdict_icon = "🟡"
        verdict_summary = "Fair business metrics but lacks decisive margin of safety or standout competitive advantage."

    pe_str = f"{pe:.1f}x" if pe else "Loss-making"
    fcf_str = f"₹{fcf:,.1f} Cr"
    sales_cagr_str = f"{sales_cagr:.1f}%" if sales_cagr is not None else "N/A"
    pat_cagr_str = f"{pat_cagr:.1f}%" if pat_cagr is not None else "N/A"

    st.markdown(f"""
    <div class="exec-card">
        <div class="verdict-banner {verdict_cls}">
            <div>{verdict_icon} VERDICT: {verdict}</div>
            <div style="font-size: 0.85rem; font-weight: normal; opacity: 0.9;">Mode: {expertise_level}</div>
        </div>
        <p style="font-size: 1.05rem; color: #f0f6fc; margin-bottom: 18px; line-height: 1.5;">{verdict_summary}</p>
        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap: 12px; margin-bottom: 16px;">
            <div class="stat-badge">
                <div class="stat-label">ROE (Return)</div>
                <div class="stat-value">{roe:.1f}%</div>
            </div>
            <div class="stat-badge">
                <div class="stat-label">ROCE</div>
                <div class="stat-value">{roce:.1f}%</div>
            </div>
            <div class="stat-badge">
                <div class="stat-label">P/E Valuation</div>
                <div class="stat-value">{pe_str}</div>
            </div>
            <div class="stat-badge">
                <div class="stat-label">Piotroski Health</div>
                <div class="stat-value">{f_score}/8</div>
            </div>
            <div class="stat-badge">
                <div class="stat-label">Free Cash Flow</div>
                <div class="stat-value">{fcf_str}</div>
            </div>
            <div class="stat-badge">
                <div class="stat-label">Debt-to-Equity</div>
                <div class="stat-value">{'N/A (Bank)' if is_fin else f'{de:.2f}x'}</div>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    if "Beginner" in expertise_level:
        st.markdown(f"### 📖 Plain-English Guide to {c}")
        
        with st.expander("🏢 1. How Profitable is this Business? (Profitability Pillar)", expanded=True):
            st.markdown(f"""
            <div class="pillar-header">🎯 Return on Equity: <b>{roe:.1f}%</b></div>
            <p>Imagine giving this business ₹100 of shareholders' money. Last year, they generated <b>₹{roe:.1f}</b> in pure profit on that money.</p>
            <div class="explainer-box">
                <b>💡 Rule of Thumb:</b> Great businesses consistently achieve an ROE above <b>15%</b>. 
                {f"✅ <b>{c} passes this test!</b> It has outstanding compounding power." if roe >= 15 else f"⚠️ <b>{c} is below 15%.</b> It is earning modest returns on shareholder capital."}
            </div>
            """, unsafe_allow_html=True)

        with st.expander("🛡️ 2. Is this Company Safe from Debt? (Debt & Safety Pillar)", expanded=True):
            if is_fin:
                st.markdown(f"""
                <div class="pillar-header">🏦 Financial Institution Safety</div>
                <p>Because <b>{c}</b> is a bank/NBFC, it naturally takes customer deposits and lends them out. Traditional debt-to-equity ratios don't apply.</p>
                <div class="explainer-box">
                    Key indicator: Piotroski Score is <b>{f_score}/8</b>. { "The bank displays robust health across profitability and operational safeguards." if f_score >= 5 else "Caution is warranted regarding loan book stress or slowing returns." }
                </div>
                """, unsafe_allow_html=True)
            else:
                st.markdown(f"""
                <div class="pillar-header">⚖️ Debt-to-Equity: <b>{de:.2f}x</b> | Interest Coverage: <b>{int_cov:.1f}x</b></div>
                <p>For every ₹1 of its own money, {c} owes <b>₹{de:.2f}</b> to lenders. Furthermore, their operating profit can pay annual interest payments <b>{int_cov:.1f} times over</b>.</p>
                <div class="explainer-box">
                    <b>💡 Rule of Thumb:</b> A debt ratio below <b>0.5x</b> is very safe. An interest coverage above <b>3.0x</b> means the company has plenty of breathing room.
                    <br>{ "✅ <b>Low financial risk:</b> This company is not at risk of debt distress." if de < 0.8 and int_cov > 3.0 else "⚠️ <b>Heavier debt load:</b> Significant cash goes toward servicing debt." }
                </div>
                """, unsafe_allow_html=True)

        with st.expander("💵 3. Is the Cash Real? (Cash Flow Pillar)", expanded=True):
            st.markdown(f"""
            <div class="pillar-header">💰 Reported Profit: <b>₹{pat:,.1f} Cr</b> | Real Free Cash: <b>₹{fcf:,.1f} Cr</b></div>
            <p>Accounting profit on paper can be distorted. <b>Free Cash Flow (FCF)</b> is the real money left in the bank after building factories and maintaining equipment.</p>
            <div class="explainer-box">
                <b>💡 Rule of Thumb:</b> A healthy business should turn accounting profit into actual cash.
                <br>{ f"✅ <b>Cash Cow:</b> {c} converted its accounting profit into ₹{fcf:,.1f} Cr of real liquid cash." if fcf > 0 else f"⚠️ <b>Cash Drain:</b> {c} reported paper profits, but actual cash was consumed by heavy capital spending or unpaid customer bills." }
            </div>
            """, unsafe_allow_html=True)

        with st.expander("🏷️ 4. Is the Price Right? (Valuation Pillar)", expanded=True):
            st.markdown(f"""
            <div class="pillar-header">🏷️ Price-to-Earnings (P/E): <b>{pe_str}</b></div>
            <p>The P/E ratio tells you how many rupees investors are paying for every ₹1 of annual profit.</p>
            <div class="explainer-box">
                <b>💡 Rule of Thumb:</b> In Indian markets, a P/E between 15x–25x is common for mature companies. Above 40x means investors expect massive future growth.
                <br>{ f"Investigate if growth justified: 3-Year Profit Growth is <b>{pat_cagr_str}</b>." if pat_cagr is not None else "" }
            </div>
            """, unsafe_allow_html=True)

    elif "Intermediate" in expertise_level:
        st.markdown(f"### 📈 Comprehensive Financial Analysis for {c}")
        col_a, col_b = st.columns(2)
        
        with col_a:
            st.markdown("#### 🎯 Capital Productivity & Growth")
            st.write(f"- **Return on Capital Employed (ROCE):** `{roce:.1f}%` (Overall business efficiency on debt + equity)")
            st.write(f"- **Return on Equity (ROE):** `{roe:.1f}%` (Equity compounding speed)")
            st.write(f"- **Operating Profit Margin (OPM):** `{row['OPM']:.1f}%`")
            st.write(f"- **3-Yr Sales Growth (CAGR):** `{sales_cagr_str}`")
            st.write(f"- **3-Yr PAT Growth (CAGR):** `{pat_cagr_str}`")

            st.markdown("#### 💵 Cash Conversion Quality")
            st.write(f"- **Operating Cash Flow (CFO):** `₹{row['CFO']:,.1f} Cr`")
            st.write(f"- **Capital Expenditures (CapEx):** `₹{row['CapEx']:,.1f} Cr`")
            st.write(f"- **Free Cash Flow (FCF):** `₹{fcf:,.1f} Cr`")
            st.write(f"- **FCF Yield on Market Cap:** `{fcf_yield:.2f}%`")

        with col_b:
            st.markdown("#### ⚖️ Solvency & Balance Sheet Structure")
            if not is_fin:
                st.write(f"- **Debt-to-Equity:** `{de:.2f}x`")
                st.write(f"- **Interest Coverage:** `{int_cov:.1f}x`")
                st.write(f"- **Altman Z-Score:** `{z_score:.2f if z_score else 'N/A'}` (Zone: **{z_zone}**)")
            else:
                st.write("*- Financial Entity: Standard Debt/Altman metrics bypassed.*")
                st.write(f"- **Net Worth:** `₹{row['Net_Worth']:,.1f} Cr`")
            st.write(f"- **Piotroski F-Score:** `{f_score}/8` ({ 'Pristine operational health' if f_score >= 6 else 'Average operational safeguards' if f_score >= 4 else 'Weak trend' })")
            
            st.markdown("#### 🏷️ Relative Valuation Multiples")
            st.write(f"- **Current P/E:** `{pe_str}`")
            st.write(f"- **Market Capitalization:** `₹{row['Market_Cap']:,.1f} Cr`")
            st.write(f"- **CWIP to Net Block:** `{safe_div(cwip, nb)*100.0:.1f}%`")

    else:
        st.markdown(f"### 🏛️ Institutional Quantitative Profile: {c}")
        c1, c2, c3 = st.columns(3)
        
        with c1:
            st.markdown("##### 📌 Earnings Quality & Accruals")
            st.write(f"• **Sloan Accrual Ratio:** `{sloan:.2%}`")
            if abs(sloan) > 0.10:
                st.caption("⚠️ High accruals detected. Disconnect between Net Income and CFO.")
            else:
                st.caption("✅ Low accruals. Earnings are supported by cash.")
            st.write(f"• **CFO / PAT Ratio:** `{safe_div(row['CFO'], pat):.2f}x`")
            st.write(f"• **Piotroski F-Score:** `{f_score}/8`")

        with c2:
            st.markdown("##### 📌 Capital Allocation & Moat")
            st.write(f"• **ROCE (Capital Employed):** `{roce:.2f}%`")
            st.write(f"• **ROE (Equity Capital):** `{roe:.2f}%`")
            st.write(f"• **FCF Yield %:** `{fcf_yield:.2f}%`")
            st.write(f"• **Asset Turnover:** `{safe_div(row['Sales'], row['Total_Assets']):.2f}x`")

        with c3:
            st.markdown("##### 📌 Risk & Tail Risk Metrics")
            if not is_fin:
                st.write(f"• **Altman Z-Score:** `{z_score:.2f if z_score else 'N/A'}` ({z_zone})")
                st.write(f"• **D/E Leverage:** `{de:.2f}x`")
                st.write(f"• **Interest Coverage:** `{int_cov:.1f}x`")
            else:
                st.write("• **Sector Regime:** Banking / Financial Services")
                st.write(f"• **Total Assets:** `₹{row['Total_Assets']:,.1f} Cr`")
            st.write(f"• **CWIP / Net Block:** `{safe_div(cwip, nb)*100.0:.1f}%`")

# ─────────────────────────────────────────────────────────────────────────────
# 4. UI & CONTROL FLOW
# ─────────────────────────────────────────────────────────────────────────────
inject_custom_css()

st.markdown("""
<div class="hero-banner">
    <div class="hero-title">🏛️ Institutional Equity Research Terminal</div>
    <div class="hero-subtitle">High-throughput fundamental analytics, forensic risk auditing & beginner-to-institutional research synthesis.</div>
</div>
""", unsafe_allow_html=True)

with st.sidebar:
    st.header("🎛️ Terminal Settings")
    
    expertise_level = st.radio(
        "Select Investor Experience Level:",
        [
            "🌱 Beginner Investor (Plain English)",
            "📈 Intermediate Investor (Ratios & Financials)",
            "🏛️ Pro / Institutional Analyst (Deep Forensic Quant)"
        ],
        index=0
    )
    
    st.divider()
    st.header("📁 Financial Data Ingestion")
    st.caption("Upload Screener.in standard Excel workbooks (.xlsx / .xls).")
    uploaded_files = st.file_uploader(
        "Upload Cohort Excel Files",
        type=["xlsx", "xls"],
        accept_multiple_files=True
    )
    
    st.divider()
    max_pe_bound = st.slider("Plotly Scatter: Max P/E Bound", min_value=30, max_value=250, value=80, step=10)

if uploaded_files:
    parsed_companies = []
    raw_files = []
    
    for up_file in uploaded_files:
        try:
            content = up_file.read()
            raw_files.append((up_file.name, content))
            wb = openpyxl.load_workbook(io.BytesIO(content), data_only=True)
            res = extract_financial_data(wb, up_file.name)
            parsed_companies.append(res)
        except Exception as e:
            st.error(f"Error parsing workbook `{up_file.name}`: {str(e)}")

    if parsed_companies:
        df_cohort = pd.DataFrame(parsed_companies)
        
        tab_deep, tab_matrix, tab_visual, tab_risk, tab_export = st.tabs([
            "🔍 Strategic Deep-Dive", 
            "📊 Cohort Master Matrix", 
            "📈 Visual Analytics", 
            "🛡️ Forensic Risk Auditor", 
            "📥 Export Reports"
        ])

        with tab_deep:
            valid_roe = df_cohort[df_cohort["ROE"] > 0]
            top_roe_comp = valid_roe.loc[valid_roe["ROE"].idxmax()]["Company"] if not valid_roe.empty else "N/A"
            top_roe_val = valid_roe["ROE"].max() if not valid_roe.empty else 0.0

            valid_pe = df_cohort[df_cohort["PE"].notna() & (df_cohort["PE"] > 0)]
            low_pe_comp = valid_pe.loc[valid_pe["PE"].idxmin()]["Company"] if not valid_pe.empty else "N/A"
            low_pe_val = valid_pe["PE"].min() if not valid_pe.empty else 0.0

            valid_z = df_cohort[df_cohort["Altman_Z"].notna()]
            safe_z_comp = valid_z.loc[valid_z["Altman_Z"].idxmax()]["Company"] if not valid_z.empty else "N/A"
            safe_z_val = valid_z["Altman_Z"].max() if not valid_z.empty else 0.0

            kpi1, kpi2, kpi3 = st.columns(3)
            kpi1.metric("🏆 Cohort ROE Leader", top_roe_comp, f"{top_roe_val:.1f}%")
            kpi2.metric("🏷️ Lowest Valuation (P/E)", low_pe_comp, f"{low_pe_val:.1f}x" if low_pe_val else "N/A")
            kpi3.metric("🛡️ Safest Solvency (Altman Z)", safe_z_comp, f"{safe_z_val:.2f}" if safe_z_val else "N/A")

            st.divider()

            selected_company_name = st.selectbox(
                "Select Company to Inspect:", 
                options=df_cohort["Company"].tolist(),
                index=0
            )
            selected_row = df_cohort[df_cohort["Company"] == selected_company_name].iloc[0]
            generate_strategic_narrative(selected_row, expertise_level)

        with tab_matrix:
            st.markdown("### 📊 Multi-Company Fundamental Matrix")
            display_cols = [
                "Company", "Sector", "CMP", "Market_Cap", "PE", "OPM", "ROE", 
                "ROCE", "Interest_Coverage", "DE_Ratio", "FCF_Yield", 
                "Piotroski_Score", "Altman_Z", "Z_Zone"
            ]
            
            format_dict = {
                "CMP": "₹{:,.1f}",
                "Market_Cap": "₹{:,.0f} Cr",
                "PE": "{:.1f}x",
                "OPM": "{:.1f}%",
                "ROE": "{:.1f}%",
                "ROCE": "{:.1f}%",
                "Interest_Coverage": "{:.1f}x",
                "DE_Ratio": "{:.2f}x",
                "FCF_Yield": "{:.2f}%",
                "Piotroski_Score": "{:d}/8",
                "Altman_Z": lambda x: f"{x:.2f}" if pd.notna(x) else "N/A"
            }
            
            clean_display_df = df_cohort[display_cols].copy()
            st.dataframe(
                clean_display_df.style.format(format_dict, na_rep="N/A"),
                use_container_width=True,
                height=450
            )

        with tab_visual:
            st.markdown("### 📈 Visual Analytics Suite")
            col_v1, col_v2 = st.columns(2)
            
            with col_v1:
                scatter_df = df_cohort.copy()
                scatter_df["Scatter_PE"] = scatter_df["PE"].fillna(max_pe_bound + 5).clip(upper=max_pe_bound)
                scatter_df["Bubble_Size"] = scatter_df["Market_Cap"].clip(lower=100)
                
                fig_scatter = px.scatter(
                    scatter_df,
                    x="Scatter_PE",
                    y="ROE",
                    size="Bubble_Size",
                    color="Z_Zone",
                    hover_name="Company",
                    hover_data={"Scatter_PE": False, "PE": ":.1f", "ROE": ":.1f%", "Market_Cap": ":,.0f"},
                    title=f"Valuation (P/E) vs. Capital Return (ROE %) [Clamped at {max_pe_bound}x]",
                    labels={"Scatter_PE": "P/E Multiple", "ROE": "Return on Equity (ROE %)"},
                    template="plotly_dark",
                    color_discrete_map={
                        "Safe": "#10b981", 
                        "Grey": "#f59e0b", 
                        "Distress": "#ef4444", 
                        "Financial Entity (Exempt)": "#3b82f6"
                    }
                )
                fig_scatter.update_layout(height=480, range_x=[-5, max_pe_bound + 10])
                st.plotly_chart(fig_scatter, use_container_width=True)

            with col_v2:
                fig_bar = go.Figure()
                fig_bar.add_trace(go.Bar(
                    x=df_cohort["Company"],
                    y=df_cohort["Piotroski_Score"],
                    name="Piotroski F-Score (Max 8)",
                    marker_color="#3b82f6"
                ))
                clean_z = df_cohort["Altman_Z"].fillna(0)
                fig_bar.add_trace(go.Bar(
                    x=df_cohort["Company"],
                    y=clean_z,
                    name="Altman Z-Score",
                    marker_color="#10b981"
                ))
                fig_bar.update_layout(
                    barmode="group",
                    title="Piotroski Operational Health vs. Altman Solvency",
                    template="plotly_dark",
                    height=480,
                    yaxis_title="Score"
                )
                st.plotly_chart(fig_bar, use_container_width=True)

        with tab_risk:
            st.markdown("### 🛡️ Automated Forensic Risk Auditor")
            st.caption("Heuristic screening across cash flow divergence, balance sheet stress, accruals & execution risk.")
            
            c_r1, c_r2, c_r3, c_r4 = st.columns(4)
            
            with c_r1:
                st.markdown("#### 1. Cash Conversion")
                for _, r in df_cohort.iterrows():
                    if r["FCF"] < 0 and r["PAT"] > 0:
                        st.markdown(f"**{r['Company']}**: <span class='tag-pill tag-danger'>Drain</span>", unsafe_allow_html=True)
                        st.caption(f"PAT: ₹{r['PAT']:,.0f} Cr vs FCF: ₹{r['FCF']:,.0f} Cr")
                    elif r["FCF"] > r["PAT"]:
                        st.markdown(f"**{r['Company']}**: <span class='tag-pill tag-safe'>Cash Cow</span>", unsafe_allow_html=True)
                    else:
                        st.markdown(f"**{r['Company']}**: <span class='tag-pill tag-neutral'>Normal</span>", unsafe_allow_html=True)

            with c_r2:
                st.markdown("#### 2. Solvency & Debt")
                for _, r in df_cohort.iterrows():
                    if r["Is_Financial"]:
                        st.markdown(f"**{r['Company']}**: <span class='tag-pill tag-neutral'>Bank</span>", unsafe_allow_html=True)
                    elif r["DE_Ratio"] > 1.2 or (r["Interest_Coverage"] < 2.0 and r["Debt"] > 0):
                        st.markdown(f"**{r['Company']}**: <span class='tag-pill tag-danger'>Leverage Alert</span>", unsafe_allow_html=True)
                        st.caption(f"D/E: {r['DE_Ratio']:.1f}x | IntCov: {r['Interest_Coverage']:.1f}x")
                    elif r["DE_Ratio"] < 0.3:
                        st.markdown(f"**{r['Company']}**: <span class='tag-pill tag-safe'>Pristine</span>", unsafe_allow_html=True)
                    else:
                        st.markdown(f"**{r['Company']}**: <span class='tag-pill tag-neutral'>Moderate</span>", unsafe_allow_html=True)

            with c_r3:
                st.markdown("#### 3. Accrual Quality")
                for _, r in df_cohort.iterrows():
                    if not r["Is_Financial"] and abs(r["Sloan_Ratio"]) > 0.10:
                        st.markdown(f"**{r['Company']}**: <span class='tag-pill tag-warning'>High Accruals</span>", unsafe_allow_html=True)
                        st.caption(f"Sloan Ratio: {r['Sloan_Ratio']:.1%}")
                    elif r["Is_Financial"]:
                        st.markdown(f"**{r['Company']}**: <span class='tag-pill tag-neutral'>Exempt</span>", unsafe_allow_html=True)
                    else:
                        st.markdown(f"**{r['Company']}**: <span class='tag-pill tag-safe'>High Quality</span>", unsafe_allow_html=True)

            with c_r4:
                st.markdown("#### 4. Asset Execution")
                for _, r in df_cohort.iterrows():
                    cwip_ratio = safe_div(r["CWIP"], r["Net_Block"]) * 100.0
                    if cwip_ratio > 40.0:
                        st.markdown(f"**{r['Company']}**: <span class='tag-pill tag-warning'>High CWIP</span>", unsafe_allow_html=True)
                        st.caption(f"CWIP / Net Block: {cwip_ratio:.1f}%")
                    else:
                        st.markdown(f"**{r['Company']}**: <span class='tag-pill tag-safe'>Executed</span>", unsafe_allow_html=True)

        with tab_export:
            st.markdown("### 📥 Export Offline Research Reports")
            st.caption("Generate downloadable research synthesis or backup the ingested Excel workbooks.")
            
            report = f"""# Institutional Equity Research Synthesis
Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
Cohort Size: {len(df_cohort)} Companies

## 1. Executive Summary & Cohort Matrix
| Company | Sector | PE | ROE % | ROCE % | D/E | FCF (₹ Cr) | Piotroski | Altman Z |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
"""
            for _, r in df_cohort.iterrows():
                pe_fmt = f"{r['PE']:.1f}x" if r['PE'] else "N/A"
                z_fmt = f"{r['Altman_Z']:.2f}" if pd.notna(r['Altman_Z']) else "N/A"
                report += f"| {r['Company']} | {r['Sector']} | {pe_fmt} | {r['ROE']:.1f}% | {r['ROCE']:.1f}% | {r['DE_Ratio']:.2f}x | {r['FCF']:,.1f} | {r['Piotroski_Score']}/8 | {z_fmt} |\n"

            report += "\n## 2. Company Research Profiles\n"
            for _, r in df_cohort.iterrows():
                report += f"\n### {r['Company']}\n"
                report += f"- **Sector:** {r['Sector']}\n"
                report += f"- **Compounding:** ROE: {r['ROE']:.1f}%, ROCE: {r['ROCE']:.1f}%\n"
                report += f"- **Cash Reality:** PAT: ₹{r['PAT']:,.1f} Cr vs FCF: ₹{r['FCF']:,.1f} Cr (Yield: {r['FCF_Yield']:.2f}%)\n"
                report += f"- **Health:** Piotroski: {r['Piotroski_Score']}/8, Altman Z: {r['Z_Zone']}\n"

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
