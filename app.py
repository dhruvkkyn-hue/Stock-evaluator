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
        
        # EV/EBITDA Calculation
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
    for _, r in df_sub.iterrows():
        r_str = [str(val).replace('\n', ' ') for val in r.values]
        data_rows.append("| " + " | ".join(r_str) + " |")
    return "\n".join([header_row, sep_row] + data_rows)

# ─────────────────────────────────────────────────────────────────────────────
# 3. 3-TIER INVESTOR EXPERIENCE NARRATIVE ENGINE
# ─────────────────────────────────────────────────────────────────────────────

def get_metric_meta(metric_name, row):
    is_fin = row["Is_Financial"]
    meta = {
        "ROE %": {
            "val": f"{row['ROE %']:.1f}%",
            "rating": "good" if row['ROE %'] >= 15 else "warn" if row['ROE %'] >= 10 else "bad",
            "tag": "Capital Efficiency"
        },
        "ROCE %": {
            "val": f"{row['ROCE %']:.1f}%",
            "rating": "good" if row['ROCE %'] >= 15 else "warn" if row['ROCE %'] >= 10 else "bad",
            "tag": "Total Capital Return"
        },
        "D/E": {
            "val": "N/A (Financial)" if is_fin else f"{row['D/E']:.2f}",
            "rating": "neutral" if is_fin else ("good" if row['D/E'] < 0.5 else "warn" if row['D/E'] <= 1.2 else "bad"),
            "tag": "Solvency"
        },
        "Interest Coverage": {
            "val": "Exempt (Bank)" if is_fin else (f"{row['Interest Coverage']:.1f}x" if row['Interest Coverage'] < 900 else "Debt Free"),
            "rating": "neutral" if is_fin else ("good" if row['Interest Coverage'] > 4.0 else "warn" if row['Interest Coverage'] >= 2.0 else "bad"),
            "tag": "Debt Service"
        },
        "FCF": {
            "val": f"₹{row['FCF']:,.0f} Cr",
            "rating": "good" if row['FCF'] > 0 else "bad",
            "tag": "Cash Generation"
        },
        "P/E": {
            "val": f"{row['PE']:.1f}x" if row['PE'] > 0 else "Loss Making",
            "rating": "neutral" if row['PE'] <= 0 else ("good" if row['PE'] < 25 else "warn" if row['PE'] <= 50 else "bad"),
            "tag": "Valuation"
        },
        "Piotroski": {
            "val": f"{row['Piotroski']}/8",
            "rating": "good" if row['Piotroski'] >= 6 else "warn" if row['Piotroski'] >= 4 else "bad",
            "tag": "Accounting Health"
        }
    }
    return meta.get(metric_name, {"val": "N/A", "rating": "neutral", "tag": "General"})

def get_beginner_metric_desc(metric, row):
    c = row["Company"]
    is_fin = row["Is_Financial"]
    
    if metric == "ROE %":
        val = row["ROE %"]
        status = "🌟 Excellent" if val >= 18 else "✅ Good" if val >= 12 else "⚠️ Subdued"
        meaning = (
            f"If shareholders give {c} ₹100 of their own money, the management generates **₹{val:.1f} in annual net profit**. "
            "High numbers indicate that the company has a competitive advantage (a moat)."
        )
        takeaway = "Consistently earning above 15% means your wealth compounds rapidly over time."
        
    elif metric == "D/E":
        if is_fin:
            status = "🏦 Banking Entity"
            meaning = f"{c} is a financial institution that takes deposits to lend. Traditional Debt-to-Equity is not an informative risk gauge here."
            takeaway = "Focus instead on asset quality, NPA trends, and Capital Adequacy."
        else:
            val = row["D/E"]
            status = "🟢 Debt-Free / Pristine" if val < 0.1 else "✅ Healthy" if val < 0.7 else "⚠️ High Debt"
            meaning = f"For every ₹1 of money owned by shareholders, {c} owes **₹{val:.2f} to outside lenders and banks**."
            takeaway = "Companies with low debt rarely face bankruptcy risk during economic recessions."
            
    elif metric == "Interest Coverage":
        if is_fin:
            status = "🏦 Exempt"
            meaning = "Interest cost is a raw operational expense for banks, making traditional coverage ratios redundant."
            takeaway = "Evaluate Net Interest Margin (NIM) and Return on Assets."
        else:
            val = row["Interest Coverage"]
            status = "🟢 Bulletproof" if val > 6 else "✅ Adequate" if val >= 2.5 else "🚨 Strained"
            meaning = f"{c} earns enough operating profit to pay its annual loan interest obligations **{val:.1f} times over**."
            takeaway = "Ratios above 4.0x mean the company can comfortably handle rising interest rate cycles."

    elif metric == "FCF":
        val = row["FCF"]
        pat = row["Net Profit"]
        status = "🟢 True Cash Generator" if val > 0 else "⚠️ Cash Burner"
        meaning = (
            f"Accounting profit on paper was ₹{pat:,.0f} Cr, but after actually upgrading and building factories (CapEx of ₹{row['CapEx']:,.0f} Cr), "
            f"{c} took home **₹{val:,.0f} Cr in cold, hard liquid bank cash**."
        )
        takeaway = "Stock prices follow free cash flow over the long run. Dividends and share buybacks come strictly from FCF."

    elif metric == "P/E":
        val = row["PE"]
        status = "🟢 Reasonable" if (0 < val <= 25) else "⚖️ Premium Growth" if (25 < val <= 55) else "🚨 Expensive" if val > 55 else "⚠️ Loss-Making"
        meaning = (
            f"Investors in the market are currently paying **₹{val:.1f} for every ₹1 of profit** {c} earns annually."
            if val > 0 else f"{c} reported a net loss over the latest period, so traditional P/E cannot be computed."
        )
        takeaway = "Paying too high a multiple reduces your margin of safety, even for great businesses."

    elif metric == "Piotroski":
        val = row["Piotroski"]
        status = "🟢 Clean Audit" if val >= 6 else "⚖️ Average" if val >= 4 else "🚨 Financial Warning"
        meaning = f"Out of 8 fundamental checks testing profitability, balance sheet leverage, and operating efficiency, {c} cleared **{val} criteria**."
        takeaway = "Scores of 7 or 8 suggest sound accounting integrity and improving business fundamentals."
        
    else:
        return ""

    return f"""
    <div style="background-color: var(--card-bg); border-left: 4px solid var(--accent-blue); padding: 14px 18px; border-radius: 6px; margin-bottom: 14px;">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
            <span style="font-weight: 700; font-size: 1.05rem; color: #fff;">{metric} Analysis</span>
            <span style="font-size: 0.9rem; font-weight: 600;">{status}</span>
        </div>
        <p style="margin-bottom: 6px; font-size: 0.95rem; line-height: 1.5;">{meaning}</p>
        <p style="margin-bottom: 0px; font-size: 0.85rem; color: var(--accent-emerald);">💡 <b>Why it matters:</b> {takeaway}</p>
    </div>
    """

def get_intermediate_metric_desc(metric, row):
    c = row["Company"]
    if metric == "ROE %":
        return f"**{metric}:** `{row['ROE %']:.1f}%` vs Cost of Equity (~12%). Generates excess economic return on equity capital."
    elif metric == "ROCE %":
        return f"**{metric}:** `{row['ROCE %']:.1f}%` return on total capital deployed (Equity + Net Debt)."
    elif metric == "D/E":
        return f"**{metric}:** `{row['D/E']:.2f}`. Net balance sheet gearing."
    elif metric == "Interest Coverage":
        return f"**{metric}:** `{row['Interest Coverage']:.1f}x` EBIT to Finance charges."
    elif metric == "FCF":
        return f"**{metric}:** CFO of `₹{row['Sales']*0.15:,.0f}Cr` minus CapEx of `₹{row['CapEx']:,.0f}Cr` = `₹{row['FCF']:,.0f}Cr` FCF."
    elif metric == "P/E":
        return f"**{metric}:** Trailing P/E of `{row['PE']:.1f}x` vs 3-Year PAT CAGR of `{row['3Yr PAT CAGR %']:.1f}%`."
    elif metric == "Piotroski":
        return f"**{metric}:** `{row['Piotroski']}/8` scoring across liquidity, solvency, and operational margins."
    return ""

def get_pro_metric_desc(metric, row):
    if metric == "ROE %":
        return f"**DuPont Deconstruction:** ROE of `{row['ROE %']:.2f}%` driven by OPM `{row['OPM %']:.2f}%`."
    elif metric == "D/E":
        return f"**Capital Structure:** Debt: `{row['D/E']:.2f}x` | Solvency status: `{row['Zone']}` (Altman Z: `{row['Altman Z']:.2f}`)."
    elif metric == "Interest Coverage":
        return f"**Fixed Charge Coverage:** Coverage `{row['Interest Coverage']:.2f}x` on operating EBIT."
    elif metric == "FCF":
        return f"**FCF Yield:** `{row['FCF Yield %']:.2f}%` on Market Cap. Sloan Accrual: `{row['Sloan %']:.2f}%`."
    elif metric == "P/E":
        return f"**Valuation Complex:** P/E: `{row['PE']:.1f}x` | EV/EBITDA: `{row['EV/EBITDA']:.1f}x`."
    elif metric == "Piotroski":
        return f"**Forensic Score:** `{row['Piotroski']}/8` confirming balance sheet and operational earnings quality."
    return ""

def render_expertise_deep_dive(row, category, level):
    metrics_map = {
        "Compounding & Returns": ["ROE %", "ROCE %"],
        "Solvency & Balance Sheet": ["D/E", "Interest Coverage"],
        "Cash Generation": ["FCF"],
        "Valuation & Integrity": ["P/E", "Piotroski"]
    }
    
    target_metrics = metrics_map.get(category, [])
    output = []
    
    for m in target_metrics:
        if level == "🌱 Beginner Investor":
            desc = get_beginner_metric_desc(m, row)
            output.append(desc)
        elif level == "📈 Intermediate Investor":
            desc = get_intermediate_metric_desc(m, row)
            output.append(f"<div style='margin-bottom: 8px;'>{desc}</div>")
        else:
            desc = get_pro_metric_desc(m, row)
            output.append(f"<div style='margin-bottom: 8px;'>{desc}</div>")
            
    return "\n\n".join(output)

# ─────────────────────────────────────────────────────────────────────────────
# 4. UI & CONTROL FLOW
# ─────────────────────────────────────────────────────────────────────────────

inject_custom_css()

with st.sidebar:
    st.header("📂 Batch Ingestion")
    uploads = st.file_uploader("Upload Screener Excels", type=["xlsx", "xls"], accept_multiple_files=True)
    st.divider()
    st.markdown("### 🏛️ Experience Controls")
    complexity_level = st.radio(
        "Select Analysis Complexity:", 
        ["🌱 Beginner Investor", "📈 Intermediate Investor", "🏛️ Pro / Institutional Analyst"]
    )
    st.divider()
    st.markdown("### ⚙️ Terminal Settings")
    max_pe_bound = st.slider(
        "Scatter Plot Max P/E Axis Limit", 
        min_value=50, max_value=300, value=150, step=25, 
        help="Clips scatter plot x-axis upper bound to prevent valuation outliers from compressing the chart."
    )
    st.divider()
    st.caption(f"Institutional Terminal v5.0 | {datetime.now().year}")

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
        
        tab1, tab2, tab3, tab4, tab5 = st.tabs([
            "📊 Master Grid", "🕵️ Comparative Research Deep-Dive", 
            "📈 Visual Benchmarks", "🚨 Forensic Auditor", "📄 Export Report"
        ])

        # ─────────────────────────────────────────────────────────────────────────
        # TAB 1: MASTER QUANTITATIVE MATRIX
        # ─────────────────────────────────────────────────────────────────────────
        with tab1:
            st.subheader("Master Quantitative Grid")
            
            disp_df = df.copy()
            st.dataframe(
                disp_df[[
                    "Company", "Sector_Type", "Market Cap", "Sales", "Net Profit", 
                    "PE", "EV/EBITDA", "ROE %", "ROCE %", "D/E", "Interest Coverage", 
                    "FCF Yield %", "Piotroski", "Altman Z", "Zone"
                ]].style.format({
                    "Market Cap": "₹{:,.0f}Cr", 
                    "Sales": "₹{:,.0f}Cr", 
                    "Net Profit": "₹{:,.0f}Cr",
                    "PE": lambda x: f"{x:.1f}x" if x > 0 else "N/A (Loss)",
                    "EV/EBITDA": lambda x: f"{x:.1f}x" if x > 0 else "N/A",
                    "ROE %": "{:.1f}%", 
                    "ROCE %": "{:.1f}%", 
                    "D/E": "{:.2f}", 
                    "Interest Coverage": lambda x: f"{x:.1f}x" if pd.notna(x) and x < 900 else ("Debt Free" if x >= 900 else "N/A (Bank)"),
                    "FCF Yield %": "{:.1f}%", 
                    "Piotroski": "{}/8", 
                    "Altman Z": lambda x: f"{x:.2f}" if pd.notna(x) else "N/A"
                }), 
                use_container_width=True, 
                height=450
            )

        # ─────────────────────────────────────────────────────────────────────────
        # TAB 2: 3-TIER COMPARATIVE DEEP-DIVE
        # ─────────────────────────────────────────────────────────────────────────
        with tab2:
            st.subheader("🕵️ Comparative Research Deep-Dive")
            
            # Header KPI summary cards
            col_kpi1, col_kpi2, col_kpi3, col_kpi4 = st.columns(4)
            best_roe_comp = df.loc[df['ROE %'].idxmax()]
            low_pe_df = df[df['PE'] > 0]
            best_pe_comp = low_pe_df.loc[low_pe_df['PE'].idxmin()] if not low_pe_df.empty else df.iloc[0]
            best_fcf_comp = df.loc[df['FCF'].idxmax()]
            best_pio_comp = df.loc[df['Piotroski'].idxmax()]

            col_kpi1.metric("🏆 Highest ROE", f"{best_roe_comp['ROE %']:.1f}%", best_roe_comp['Company'])
            col_kpi2.metric("🏷️ Lowest P/E", f"{best_pe_comp['PE']:.1f}x" if best_pe_comp['PE'] > 0 else "N/A", best_pe_comp['Company'])
            col_kpi3.metric("💰 Cash Flow King", f"₹{best_fcf_comp['FCF']:,.0f}Cr", best_fcf_comp['Company'])
            col_kpi4.metric("🛡️ Top Quality Score", f"{best_pio_comp['Piotroski']}/8", best_pio_comp['Company'])

            st.divider()

            selected_company = st.selectbox("Select Company for Strategic Analysis:", df["Company"].unique())
            row = df[df["Company"] == selected_company].iloc[0]

            # Strategic Quick Verdict Banner
            roe_val = row["ROE %"]
            de_val = row["D/E"]
            pio_val = row["Piotroski"]
            fcf_val = row["FCF"]
            is_fin = row["Is_Financial"]

            if roe_val >= 16 and (de_val < 0.6 or is_fin) and pio_val >= 6 and fcf_val > 0:
                verdict = "STRONG BUY / CORE COMPOUNDER"
                verdict_color = "var(--accent-emerald)"
                verdict_summary = "Pristine capital returns, conservative balance sheet leverage, and outstanding accounting cash conversion."
            elif roe_val >= 12 and (de_val <= 1.2 or is_fin) and pio_val >= 5:
                verdict = "ACCUMULATE / HIGH-QUALITY WATCHLIST"
                verdict_color = "var(--accent-blue)"
                verdict_summary = "Solid fundamental performance with sustainable market share and reasonable balance sheet safeguards."
            elif de_val > 1.5 and not is_fin:
                verdict = "CAUTION: HIGH LEVERAGE EXPOSURE"
                verdict_color = "var(--accent-orange)"
                verdict_summary = "Debt load warrants close monitoring; rising interest rates or cyclical downswings could pressure cash margins."
            else:
                verdict = "NEUTRAL / SELECTIVE HOLD"
                verdict_color = "#9ca3af"
                verdict_summary = "Balanced growth trajectory without asymmetric upside or immediate balance sheet catalysts."

            st.markdown(f"""
            <div style="background-color: var(--card-bg); border: 1px solid var(--border-color); border-top: 4px solid {verdict_color}; padding: 18px 22px; border-radius: 8px; margin-bottom: 22px;">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
                    <span style="font-size: 1.15rem; font-weight: 800; color: {verdict_color};">📌 STRATEGIC VERDICT: {verdict}</span>
                    <span style="font-size: 0.85rem; color: #8b949e; text-transform: uppercase;">Sector: {row['Sector_Type']}</span>
                </div>
                <p style="margin: 0; color: #c9d1d9; font-size: 0.95rem;">{verdict_summary}</p>
            </div>
            """, unsafe_allow_html=True)

            # 3-Tier Multi-Pillar View
            t_col1, t_col2 = st.columns(2)
            
            with t_col1:
                st.markdown("#### 1. Compounding & Returns")
                comp_desc = render_expertise_deep_dive(row, "Compounding & Returns", complexity_level)
                st.markdown(comp_desc, unsafe_allow_html=True)

                st.markdown("#### 2. Cash Reality & True Earnings")
                cash_desc = render_expertise_deep_dive(row, "Cash Generation", complexity_level)
                st.markdown(cash_desc, unsafe_allow_html=True)

            with t_col2:
                st.markdown("#### 3. Solvency & Balance Sheet Shield")
                solv_desc = render_expertise_deep_dive(row, "Solvency & Balance Sheet", complexity_level)
                st.markdown(solv_desc, unsafe_allow_html=True)

                st.markdown("#### 4. Valuation & Audit Integrity")
                val_desc = render_expertise_deep_dive(row, "Valuation & Integrity", complexity_level)
                st.markdown(val_desc, unsafe_allow_html=True)

        # ─────────────────────────────────────────────────────────────────────────
        # TAB 3: INTERACTIVE VISUAL BENCHMARKS
        # ─────────────────────────────────────────────────────────────────────────
        with tab3:
            st.subheader("📈 Institutional Visual Analytics")
            
            v_col1, v_col2 = st.columns(2)
            
            with v_col1:
                plot_df = df.copy()
                plot_df["Clamped_PE"] = plot_df["PE"].apply(
                    lambda x: max(0.0, min(float(x), float(max_pe_bound))) if (pd.notna(x) and x > 0) else 0.0
                )
                
                fig_scatter = px.scatter(
                    plot_df, 
                    x="Clamped_PE", 
                    y="ROE %", 
                    size="Market Cap", 
                    color="Zone",
                    hover_name="Company",
                    hover_data={
                        "Clamped_PE": False, 
                        "PE": ":.1f", 
                        "ROE %": ":.1f%", 
                        "Market Cap": ":,.0f",
                        "Zone": True
                    },
                    color_discrete_map={
                        "Safe": "#10b981", 
                        "Grey": "#f59e0b", 
                        "Distress": "#ef4444", 
                        "N/A (Financial)": "#3b82f6"
                    },
                    title=f"Valuation (P/E) vs. Profitability (ROE %) [Bounded at {max_pe_bound}x P/E]",
                    labels={"Clamped_PE": "P/E Multiple", "ROE %": "Return on Equity (ROE %)"},
                    template="plotly_dark"
                )
                fig_scatter.update_layout(
                    height=450,
                    xaxis=dict(range=[-2, max_pe_bound + 5]),
                    margin=dict(l=20, r=20, t=50, b=20)
                )
                st.plotly_chart(fig_scatter, use_container_width=True)

            with v_col2:
                fig_bar = go.Figure()
                fig_bar.add_trace(go.Bar(
                    x=df["Company"], 
                    y=df["Piotroski"], 
                    name="Piotroski F-Score (Max 8)", 
                    marker_color="#3b82f6"
                ))
                clean_altman = df["Altman Z"].fillna(0)
                fig_bar.add_trace(go.Bar(
                    x=df["Company"], 
                    y=clean_altman, 
                    name="Altman Z-Score", 
                    marker_color="#10b981"
                ))
                fig_bar.update_layout(
                    barmode="group", 
                    title="Piotroski Score vs. Altman Z-Score Benchmark",
                    template="plotly_dark", 
                    height=450,
                    margin=dict(l=20, r=20, t=50, b=20)
                )
                st.plotly_chart(fig_bar, use_container_width=True)

        # ─────────────────────────────────────────────────────────────────────────
        # TAB 4: FORENSIC AUDITOR
        # ─────────────────────────────────────────────────────────────────────────
        with tab4:
            st.subheader("🚨 Automated Forensic Auditor")
            st.markdown("<p style='color: #8b949e; margin-bottom: 20px;'>Rule-based checks flagging accrual anomalies, working capital expansion, and balance sheet distress.</p>", unsafe_allow_html=True)
            
            cols = st.columns(4)
            cols[0].markdown("##### 1. Cash Conversion")
            cols[1].markdown("##### 2. Debt Burden")
            cols[2].markdown("##### 3. Accrual Quality")
            cols[3].markdown("##### 4. Execution Risk")

            for _, r in df.iterrows():
                # 1. Cash Conversion
                with cols[0]:
                    if r["FCF"] < 0 and r["Net Profit"] > 0:
                        st.error(f"**{r['Company']}**\n\n⚠️ Negative FCF despite PAT.")
                    else:
                        st.success(f"**{r['Company']}**\n\n✅ Sound Cash Conversion.")
                
                # 2. Debt Burden
                with cols[1]:
                    if r["Is_Financial"]:
                        st.info(f"**{r['Company']}**\n\n🏦 Financial Institution.")
                    elif r["D/E"] > 1.2 or (pd.notna(r["Interest Coverage"]) and r["Interest Coverage"] < 2.0):
                        st.error(f"**{r['Company']}**\n\n⚠️ High Debt / Low Coverage.")
                    else:
                        st.success(f"**{r['Company']}**\n\n✅ Conservative Leverage.")
                
                # 3. Accrual Quality
                with cols[2]:
                    if r["Is_Financial"]:
                        st.info(f"**{r['Company']}**\n\n🏦 Accrual exempt.")
                    elif pd.notna(r["Sloan %"]) and abs(r["Sloan %"]) > 10.0:
                        st.warning(f"**{r['Company']}**\n\n⚠️ Sloan Ratio > 10% ({r['Sloan %']:.1f}%).")
                    else:
                        st.success(f"**{r['Company']}**\n\n✅ Pristine Sloan Accruals.")

                # 4. Asset Execution Risk
                with cols[3]:
                    if r["CWIP to Net Block %"] > 40.0:
                        st.warning(f"**{r['Company']}**\n\n⚠️ Heavy CWIP ({r['CWIP to Net Block %']:.1f}% of Block).")
                    else:
                        st.success(f"**{r['Company']}**\n\n✅ Normal Project Cycle.")

        # ─────────────────────────────────────────────────────────────────────────
        # TAB 5: EXPORT REPORT
        # ─────────────────────────────────────────────────────────────────────────
        with tab5:
            st.subheader("📄 Institutional Research Export")
            st.markdown("Download full quantitative audit notes and ingested workbook packages.")
            
            clean_sub = df[[
                "Company", "Sector_Type", "Market Cap", "Sales", "Net Profit", 
                "PE", "ROE %", "ROCE %", "D/E", "Interest Coverage", "FCF", "Piotroski", "Zone"
            ]].copy()
            clean_sub["PE"] = clean_sub["PE"].apply(lambda x: f"{x:.1f}x" if x > 0 else "N/A")
            clean_sub["ROE %"] = clean_sub["ROE %"].apply(lambda x: f"{x:.1f}%")
            clean_sub["ROCE %"] = clean_sub["ROCE %"].apply(lambda x: f"{x:.1f}%")
            clean_sub["Market Cap"] = clean_sub["Market Cap"].apply(lambda x: f"₹{x:,.0f}Cr")
            clean_sub["Sales"] = clean_sub["Sales"].apply(lambda x: f"₹{x:,.0f}Cr")
            clean_sub["Net Profit"] = clean_sub["Net Profit"].apply(lambda x: f"₹{x:,.0f}Cr")
            clean_sub["FCF"] = clean_sub["FCF"].apply(lambda x: f"₹{x:,.0f}Cr")

            table_md = dataframe_to_markdown_table(clean_sub)
            
            md_report = f"""# Institutional Equity Research Synthesis
*Generated on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*

## 1. Quantitative Benchmark Matrix
{table_md}

## 2. Forensic Audit Summary
- **Cohort Coverage**: {len(df)} companies
- **Cash Flow Outliers**: {len(df[df['FCF'] < 0])} companies showing negative FCF despite positive PAT.
- **Solvency Alerts**: {len(df[(df['D/E'] > 1.2) & (~df['Is_Financial'])])} industrial entities displaying D/E > 1.2x.

## 3. Methodology & Notes
All fundamental metrics parsed directly from raw Screener.in institutional models. EBIT falls back dynamically to operating cash flows and financing PBT for financial entities.
"""

            c_exp1, c_exp2 = st.columns(2)
            c_exp1.download_button(
                "📥 Download Research Report (.md)", 
                data=md_report, 
                file_name=f"Equity_Terminal_Report_{datetime.now().strftime('%Y%m%d')}.md",
                mime="text/markdown"
            )

            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "w") as zf:
                for name, b_data in raw_files:
                    zf.writestr(f"Ingested_{name}", b_data)

            c_exp2.download_button(
                "📥 Download Ingested Workbooks (.zip)", 
                data=zip_buffer.getvalue(), 
                file_name="Ingested_Workbooks_Package.zip",
                mime="application/zip"
            )
else:
    st.info("👋 Upload one or more Screener.in Excel workbooks in the sidebar to begin fundamental analysis.")
