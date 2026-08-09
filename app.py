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
    for _, row in df_sub.iterrows():
        r_str = [str(val) for val in row.values]
        data_rows.append("| " + " | ".join(r_str) + " |")
    return "\n".join([header_row, sep_row] + data_rows)

# ─────────────────────────────────────────────────────────────────────────────
# 3. EXTREME PLAIN-ENGLISH TRANSLATOR & LIMITATIONS ENGINE (ALL 12 METRICS)
# ─────────────────────────────────────────────────────────────────────────────

def generate_extreme_beginner_translator(row):
    """
    Generates Real-World Analogy, Benchmark Tag, What It Means For This Stock,
    and When This Metric Could Be WRONG (Limitations) for ALL 12 Financial Metrics.
    """
    comp = row["Company"]
    is_fin = row["Is_Financial"]
    
    # 1. Market Capitalization
    mcap = row["Market Cap"]
    if mcap >= 50000:
        mcap_tag = "[🟢 STRONG]"
        mcap_stock = f"₹{mcap:,.0f} Cr classifies {comp} as a Large-Cap titan with high market liquidity."
    elif mcap >= 15000:
        mcap_tag = "[🟡 AVERAGE]"
        mcap_stock = f"₹{mcap:,.0f} Cr makes {comp} a Mid-Cap business with a balance of growth and stability."
    else:
        mcap_tag = "[🟡 AVERAGE]"
        mcap_stock = f"₹{mcap:,.0f} Cr places {comp} as a Small-Cap with high growth potential but higher stock volatility."
    mcap_text = f"#### 1. Market Capitalization (Company Size Tag) {mcap_tag}\n" \
                f"- 💡 **Real-World Analogy:** Think of Market Cap as the total price tag to buy 100% of the company's shares today.\n" \
                f"- 🔍 **What It Means For {comp}:** {mcap_stock}\n" \
                f"- ⚠️ **When This Metric Can LIE:** Large cap doesn't automatically mean safe; giant companies can still stagnate or decline if their core market disrupts.\n"

    # 2. P/E Ratio
    pe = row["PE"]
    if pe > 0:
        if pe <= 20:
            pe_tag = "[🟢 STRONG]"
            pe_stock = f"P/E is {pe:.1f}x, meaning you pay ₹{pe:.1f} for every ₹1 of annual profit."
        elif pe <= 40:
            pe_tag = "[🟡 AVERAGE]"
            pe_stock = f"P/E is moderate at {pe:.1f}x, reflecting standard growth expectations."
        else:
            pe_tag = "[🔴 WEAK]"
            pe_stock = f"P/E is high at {pe:.1f}x, pricing in aggressive growth expectations."
    else:
        pe_tag = "[🔴 WEAK]"
        pe_stock = "P/E is negative because the company reported a net loss recently."
    pe_text = f"#### 2. P/E Ratio (Price-to-Earnings Multiple) {pe_tag}\n" \
              f"- 💡 **Real-World Analogy:** Think of P/E as how many years of current profit it takes to pay back your stock purchase price.\n" \
              f"- 🔍 **What It Means For {comp}:** {pe_stock}\n" \
              f"- ⚠️ **When This Metric Can LIE (Value Trap):** A super-low P/E (e.g. 4x) looks cheap but can be a 'Value Trap' if earnings are about to collapse or belong to a dying industry.\n"

    # 3. EV/EBITDA
    eve = row["EV/EBITDA"]
    if eve > 0:
        if eve <= 12:
            eve_tag = "[🟢 STRONG]"
            eve_stock = f"EV/EBITDA is attractive at {eve:.1f}x, taking debt and cash into valuation account."
        elif eve <= 22:
            eve_tag = "[🟡 AVERAGE]"
            eve_stock = f"EV/EBITDA is fair at {eve:.1f}x."
        else:
            eve_tag = "[🔴 WEAK]"
            eve_stock = f"EV/EBITDA is high at {eve:.1f}x."
    else:
        eve_tag = "[🔴 WEAK]"
        eve_stock = "EV/EBITDA is N/A due to negative cash earnings."
    eve_text = f"#### 3. EV/EBITDA (Acquisition Price Multiple) {eve_tag}\n" \
               f"- 💡 **Real-World Analogy:** Think of EV/EBITDA as buying a house including taking over its mortgage minus cash left in its safe, divided by annual rent.\n" \
               f"- 🔍 **What It Means For {comp}:** {eve_stock}\n" \
               f"- ⚠️ **When This Metric Can LIE:** Ignores heavy physical machinery replacement costs (Depreciation); high CapEx companies can look deceptively cheap on EBITDA.\n"

    # 4. Operating Profit Margin (OPM %)
    opm = row["OPM %"]
    if is_fin:
        opm_name = "Net Margin (Banking Profitability)"
        if opm >= 20: opm_tag = "[🟢 STRONG]"
        elif opm >= 10: opm_tag = "[🟡 AVERAGE]"
        else: opm_tag = "[🔴 WEAK]"
        opm_stock = f"Net margin is {opm:.1f}%, capturing credit spread efficiency after provisions."
    else:
        opm_name = "Operating Profit Margin (OPM %)"
        if opm >= 18: opm_tag = "[🟢 STRONG]"
        elif opm >= 10: opm_tag = "[🟡 AVERAGE]"
        else: opm_tag = "[🔴 WEAK]"
        opm_stock = f"OPM is {opm:.1f}%, keeping ₹{opm:.1f} as operating profit out of every ₹100 sold."
    opm_text = f"#### 4. {opm_name} {opm_tag}\n" \
               f"- 💡 **Real-World Analogy:** Think of OPM as how many dollars a store owner keeps after paying rent, electricity, and inventory out of every $100 in sales.\n" \
               f"- 🔍 **What It Means For {comp}:** {opm_stock}\n" \
               f"- ⚠️ **When This Metric Can LIE:** A temporarily high OPM might be inflated by one-off commodity price spikes that quickly reverse.\n"

    # 5. Return on Equity (ROE %)
    roe = row["ROE %"]
    if roe >= 18: roe_tag = "[🟢 STRONG]"
    elif roe >= 12: roe_tag = "[🟡 AVERAGE]"
    else: roe_tag = "[🔴 WEAK]"
    roe_stock = f"ROE of {roe:.1f}% demonstrates efficiency in generating profit from shareholder equity."
    roe_text = f"#### 5. Return on Equity (ROE %) {roe_tag}\n" \
               f"- 💡 **Real-World Analogy:** Think of ROE as how many interest dollars your savings account gives you per $100 of your own money deposited.\n" \
               f"- 🔍 **What It Means For {comp}:** {roe_stock}\n" \
               f"- ⚠️ **When This Metric Can LIE (Leverage Trick):** A company can artificially inflate ROE by taking on dangerous bank debt, which shrinks equity while risking bankruptcy.\n"

    # 6. Return on Capital Employed (ROCE %)
    roce = row["ROCE %"]
    if roce >= 15: roce_tag = "[🟢 STRONG]"
    elif roce >= 10: roce_tag = "[🟡 AVERAGE]"
    else: roce_tag = "[🔴 WEAK]"
    roce_stock = f"ROCE of {roce:.1f}% measures total profit return generated from all funds (equity + debt)."
    roce_text = f"#### 6. Return on Capital Employed (ROCE %) {roce_tag}\n" \
                f"- 💡 **Real-World Analogy:** Think of ROCE as how much profit a factory generates using both the owner's money AND the bank loan combined.\n" \
                f"- 🔍 **What It Means For {comp}:** {roce_stock}\n" \
                f"- ⚠️ **When This Metric Can LIE:** Old, fully depreciated factories can make ROCE look artificially high because book asset values look tiny.\n"

    # 7. Debt-to-Equity (D/E)
    de = row["D/E"]
    if is_fin:
        de_tag = "[🟢 STRONG]" if de <= 6.0 else ("[🟡 AVERAGE]" if de <= 8.5 else "[🔴 WEAK]")
        de_stock = f"Banking D/E is {de:.2f}x, within standard financial leverage bounds for deposit-taking institutions."
    else:
        de_tag = "[🟢 STRONG]" if de <= 0.5 else ("[🟡 AVERAGE]" if de <= 1.2 else "[🔴 WEAK]")
        de_stock = f"D/E leverage stands at {de:.2f}x."
    de_text = f"#### 7. Debt-to-Equity Ratio (Borrowing Risk) {de_tag}\n" \
              f"- 💡 **Real-World Analogy:** Think of D/E as comparing your credit card debt to cash in your savings account.\n" \
              f"- 🔍 **What It Means For {comp}:** {de_stock}\n" \
              f"- ⚠️ **When This Metric Can LIE:** Capital-intensive utility/infrastructure companies naturally operate with high D/E safely due to long-term government contracts.\n"

    # 8. Interest Coverage Ratio
    ic = row["Interest Coverage"]
    if is_fin or ic is None:
        ic_tag = "[🟢 STRONG]"
        ic_stock = "Interest coverage is N/A for banks where interest is an operating cost."
    else:
        ic_val = ic if isinstance(ic, (int, float)) else 999
        ic_tag = "[🟢 STRONG]" if ic_val >= 4.0 else ("[🟡 AVERAGE]" if ic_val >= 2.0 else "[🔴 WEAK]")
        ic_stock = f"Interest Coverage stands at {ic_val:.1f}x operating profit."
    ic_text = f"#### 8. Interest Coverage Ratio (Debt Paydown Buffer) {ic_tag}\n" \
              f"- 💡 **Real-World Analogy:** Think of Interest Coverage as how many times over your monthly salary can pay your mortgage interest installment.\n" \
              f"- 🔍 **What It Means For {comp}:** {ic_stock}\n" \
              f"- ⚠️ **When This Metric Can LIE:** In cyclical industries, high interest coverage during peak boom years can vanish rapidly during demand downturns.\n"

    # 9. Sloan Accrual Ratio
    sloan = row["Sloan %"]
    if is_fin or sloan is None:
        sloan_tag = "[🟡 AVERAGE]"
        sloan_stock = "Sloan Accrual Ratio is N/A for financial entities."
    else:
        if sloan <= 5.0 and sloan >= -10.0: sloan_tag = "[🟢 STRONG]"
        elif sloan <= 10.0: sloan_tag = "[🟡 AVERAGE]"
        else: sloan_tag = "[🔴 WEAK]"
        sloan_stock = f"Sloan Ratio is {sloan:.1f}%." + (" (WARNING: >10% paper profit risk)" if sloan > 10 else " (Pristine cash earnings backing)")
    sloan_text = f"#### 9. Sloan Accrual Ratio (Earnings Quality Check) {sloan_tag}\n" \
                 f"- 💡 **Real-World Analogy:** Think of Sloan Ratio as a lie-detector test for profits—checking if reported income is real cash in the bank or just uncollected paper promises.\n" \
                 f"- 🔍 **What It Means For {comp}:** {sloan_stock}\n" \
                 f"- ⚠️ **When This Metric Can LIE:** Fast-growing companies expanding sales rapidly may show temporary high accruals due to legitimate customer payment terms.\n"

    # 10. Altman Z-Score
    alt_z = row["Altman Z"]
    zone = row["Zone"]
    if is_fin or alt_z is None:
        alt_tag = "[🟢 STRONG]"
        alt_stock = "Altman Z is N/A for banks (regulated under capital adequacy ratios)."
    else:
        alt_tag = "[🟢 STRONG]" if zone == "Safe" else ("[🟡 AVERAGE]" if zone == "Grey" else "[🔴 WEAK]")
        alt_stock = f"Altman Z of {alt_z:.2f} classifies the balance sheet in the **{zone} Zone**."
    alt_text = f"#### 10. Altman Z-Score (Bankruptcy Health Check) {alt_tag}\n" \
               f"- 💡 **Real-World Analogy:** Think of Altman Z as a doctor's overall health score for a company; scores above 3.0 mean robust health, while below 1.8 warn of bankruptcy distress.\n" \
               f"- 🔍 **What It Means For {comp}:** {alt_stock}\n" \
               f"- ⚠️ **When This Metric Can LIE:** Tech and asset-light software firms can trigger false 'Grey' warnings because they don't hold physical machinery assets.\n"

    # 11. Piotroski F-Score
    p_score = row["Piotroski"]
    p_tag = "[🟢 STRONG]" if p_score >= 6 else ("[🟡 AVERAGE]" if p_score >= 4 else "[🔴 WEAK]")
    p_stock = f"Piotroski Score is {p_score}/8, rating operational momentum across 8 key financial checks."
    p_text = f"#### 11. Piotroski F-Score (9-Point Report Card) {p_tag}\n" \
             f"- 💡 **Real-World Analogy:** Think of Piotroski as a 9-point fundamental report card covering profitability growth, balance sheet debt reduction, and operational efficiency.\n" \
             f"- 🔍 **What It Means For {comp}:** {p_stock}\n" \
             f"- ⚠️ **When This Metric Can LIE:** Piotroski compares current year to previous year; a great company undergoing temporary 1-year CapEx expansion might score low.\n"

    # 12. Free Cash Flow Yield
    fcf_y = row["FCF Yield %"]
    fcf_tag = "[🟢 STRONG]" if fcf_y >= 5.0 else ("[🟡 AVERAGE]" if fcf_y >= 1.0 else "[🔴 WEAK]")
    fcf_stock = f"Free Cash Flow Yield is {fcf_y:.1f}% relative to market capitalization."
    fcf_text = f"#### 12. Free Cash Flow Yield (Spare Cash Power) {fcf_tag}\n" \
               f"- 💡 **Real-World Analogy:** Think of Free Cash Flow as spare cash left in your wallet after paying for your rent, food, and home repairs.\n" \
               f"- 🔍 **What It Means For {comp}:** {fcf_stock}\n" \
               f"- ⚠️ **When This Metric Can LIE:** A company completing a massive once-in-a-decade factory expansion can show temporarily negative FCF Yield despite strong health.\n"

    return "\n".join([mcap_text, pe_text, eve_text, opm_text, roe_text, roce_text, de_text, ic_text, sloan_text, alt_text, p_text, fcf_text])

def generate_pros_and_cons(row):
    """Generates detailed bulleted Pros and Cons for a stock."""
    comp = row["Company"]
    is_fin = row["Is_Financial"]
    roe = row["ROE %"]
    roce = row["ROCE %"]
    pe = row["PE"]
    de = row["D/E"]
    sloan = row["Sloan %"]
    p_score = row["Piotroski"]
    zone = row["Zone"]
    fcf_y = row["FCF Yield %"]

    pros = [
        f"**Capital Compounding:** Generates an ROE of {roe:.1f}% and ROCE of {roce:.1f}%, proving strong reinvestment yields.",
        f"**Cash Generation:** Delivers a Free Cash Flow Yield of {fcf_y:.1f}%, confirming profits translate into real bankable cash.",
        f"**Fundamental Health:** Piotroski Quality Score of {p_score}/8 confirms healthy operational momentum and asset efficiency.",
        f"**Growth Track Record:** 3-Year Sales CAGR of {row['3Yr Sales CAGR %']:.1f}% demonstrating resilient commercial demand."
    ]

    cons = [
        f"**Valuation Premium:** Trades at a P/E multiple of {pe:.1f}x, requiring sustained profit execution.",
        f"**Leverage & Borrowing:** Debt-to-Equity stands at {de:.2f}x, exposing earnings to interest rate fluctuations.",
        f"**Solvency Classification:** Balance sheet is classified under the {zone} solvency zone."
    ]
    if not is_fin and sloan is not None and sloan > 10.0:
        cons.append(f"**Accrual Accounting Risk:** Sloan Accrual Ratio is elevated at {sloan:.1f}% (>10%), signaling non-cash paper profit disconnect.")

    pros_md = "\n".join([f"- 🟢 {p}" for p in pros])
    cons_md = "\n".join([f"- 🔴 {c}" for c in cons])

    return f"### ⚖️ Exhaustive Pros & Cons for {comp}\n\n**🟢 Deep Strengths (Pros):**\n{pros_md}\n\n**🔴 Deep Vulnerabilities (Cons):**\n{cons_md}\n"

def generate_actionable_triggers_framework(row):
    """
    Generates explicit BUY Triggers, SELL Triggers, Game-Changer Events, and Final Verdict Badge.
    """
    comp = row["Company"]
    is_fin = row["Is_Financial"]
    roe = row["ROE %"]
    pe = row["PE"]
    de = row["D/E"]
    sloan = row["Sloan %"]
    p_score = row["Piotroski"]
    zone = row["Zone"]
    fcf_y = row["FCF Yield %"]

    score_points = 0
    if roe >= 15: score_points += 1
    if pe > 0 and pe <= 25: score_points += 1
    if de <= 0.8 or (is_fin and de <= 7.0): score_points += 1
    if p_score >= 6: score_points += 1
    if fcf_y >= 3.0: score_points += 1
    if zone == "Safe" or is_fin: score_points += 1

    if score_points >= 5:
        signal_tag = "STRONG BUY"
        tag_html = f"<div class='signal-tag-strong-buy'>🟢 FINAL VERDICT: [STRONG BUY]</div>"
    elif score_points >= 3:
        signal_tag = "ACCUMULATE ON DIPS"
        tag_html = f"<div class='signal-tag-accumulate'>🔵 FINAL VERDICT: [ACCUMULATE ON DIPS]</div>"
    elif score_points >= 2:
        signal_tag = "HOLD / WATCHLIST"
        tag_html = f"<div class='signal-tag-hold'>🟡 FINAL VERDICT: [HOLD / WATCHLIST]</div>"
    else:
        signal_tag = "AVOID / EXIT"
        tag_html = f"<div class='signal-tag-avoid'>🔴 FINAL VERDICT: [AVOID / EXIT]</div>"

    buy_triggers = [
        f"Buy if P/E drops below 25.0x (currently {pe:.1f}x) while ROE remains strong above 15.0%.",
        f"Accumulate if Free Cash Flow Yield expands above 4.0% (currently {fcf_y:.1f}%), proving high cash conversion.",
        f"Buy/Add if Piotroski Score remains >= 6/8 (currently {p_score}/8) alongside balance sheet debt paydown."
    ]

    sell_triggers = [
        f"Sell/Exit if Altman Z-Score falls below 1.81 into Distress Zone (currently {zone}).",
        f"Exit if Debt-to-Equity ratio exceeds 1.5x (currently {de:.2f}x) due to unmanaged borrowing.",
        f"Sell/Avoid if Sloan Accrual Ratio spikes above 10.0%" + (f" (currently {sloan:.1f}%)" if sloan is not None else "") + " indicating paper profit disconnect."
    ]

    game_changers = [
        f"**CWIP Commissioning Catalyst:** Major ongoing expansion projects completing and driving revenue acceleration by >20% YoY.",
        f"**Debt Payoff Catalyst:** De-leveraging balance sheet bringing D/E below 0.3x, significantly lowering interest expense.",
        f"**Macro Risk Event:** Severe raw material price spike or key customer default contracting OPM by >250 bps."
    ]

    buy_str = "\n".join([f"- 🟢 **Trigger {idx+1}:** {bt}" for idx, bt in enumerate(buy_triggers)])
    sell_str = "\n".join([f"- 🔴 **Trigger {idx+1}:** {st}" for idx, st in enumerate(sell_triggers)])
    gc_str = "\n".join([f"- 🔄 **Catalyst {idx+1}:** {gc}" for idx, gc in enumerate(game_changers)])

    framework_md = f"### 🚦 Actionable Decision Framework for {comp}\n\n" \
                   f"**Verdict Tag:** `[{signal_tag}]`\n\n" \
                   f"#### 🟢 Exact BUY Triggers (When to Buy):\n{buy_str}\n\n" \
                   f"#### 🔴 Exact SELL Triggers (When to Sell / Avoid):\n{sell_str}\n\n" \
                   f"#### 🔄 Game-Changer Events (What Changes Thesis):\n{gc_str}\n"

    return tag_html, framework_md

def generate_beginner_executive_summary(df_sub):
    """Generates plain-English executive summary declaring Safest, Highest Growth, and Highest Risk picks."""
    if df_sub.empty:
        return "No stocks selected for comparison."

    safest_df = df_sub.sort_values(by=["Piotroski", "ROE %"], ascending=[False, False])
    safest_pick = safest_df.iloc[0]

    growth_df = df_sub.sort_values(by=["3Yr Sales CAGR %", "ROCE %"], ascending=[False, False])
    growth_pick = growth_df.iloc[0]

    risk_df = df_sub.sort_values(by=["D/E", "Sloan %"], ascending=[False, False])
    risk_pick = risk_df.iloc[0]

    summary_md = f"## 🏆 Ultimate Beginner Executive Summary\n\n" \
                 f"### 🛡️ 1. The Safest Long-Term Pick: **{safest_pick['Company']}**\n" \
                 f"- **Why It Wins:** Delivers a top Piotroski Score of **{safest_pick['Piotroski']}/8**, ROE of **{safest_pick['ROE %']:.1f}%**, and strong balance sheet health (**{safest_pick['Zone']} Zone**).\n\n" \
                 f"### 🚀 2. The Highest Growth Pick: **{growth_pick['Company']}**\n" \
                 f"- **Why It Wins:** Leads the cohort with a 3-Year Revenue CAGR of **{growth_pick['3Yr Sales CAGR %']:.1f}%** and ROCE of **{growth_pick['ROCE %']:.1f}%**.\n\n" \
                 f"### 💣 3. The Highest Risk Pick: **{risk_pick['Company']}**\n" \
                 f"- **Why It Requires Caution:** Carries the highest balance sheet leverage (D/E: **{risk_pick['D/E']:.2f}x**) or elevated accruals, requiring strict monitoring.\n"

    return summary_md

# ─────────────────────────────────────────────────────────────────────────────
# 4. UI & CONTROL FLOW
# ─────────────────────────────────────────────────────────────────────────────

with st.sidebar:
    st.header("📂 Batch Ingestion")
    uploads = st.file_uploader("Upload Screener Excels", type=["xlsx", "xls"], accept_multiple_files=True)
    st.divider()
    st.markdown("### ⚙️ Terminal Settings")
    max_pe_bound = st.slider("Scatter Plot Max P/E Axis Limit", min_value=50, max_value=300, value=150, step=25, 
                             help="Clips scatter plot x-axis upper bound to prevent valuation outliers from compressing the chart.")
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
        
        tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs([
            "📊 Matrix", "💡 Extreme Translator", "⚖️ Pros & Cons", 
            "🚦 Actionable Strategy", "📈 Visuals", "🚨 Risk Audit", "📄 Export Report"
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
                    "Interest Coverage": lambda x: f"{x:.1f}x" if isinstance(x, (int, float)) and x < 990 else ("Debt Free" if isinstance(x, (int, float)) else "N/A"),
                    "FCF Yield %": "{:.1f}%", 
                    "Altman Z": lambda x: f"{x:.2f}" if isinstance(x, (int, float)) else "N/A"
                }).background_gradient(subset=["Piotroski"], cmap="RdYlGn"),
                use_container_width=True
            )

        # ─────────────────────────────────────────────────────────────────────────
        # TAB 2: EXTREME PLAIN-ENGLISH TRANSLATOR (ALL 12 METRICS)
        # ─────────────────────────────────────────────────────────────────────────
        with tab2:
            st.subheader("💡 Extreme Plain-English Metric Translator & Limitations")
            
            kpi_col1, kpi_col2, kpi_col3 = st.columns(3)
            
            valid_roe_df = df.dropna(subset=["ROE %"])
            if not valid_roe_df.empty:
                top_roe = valid_roe_df.loc[valid_roe_df["ROE %"].idxmax()]
                kpi_col1.metric("🏆 Cohort ROE Leader", f"{top_roe['Company']}", f"{top_roe['ROE %']:.1f}% ROE")
            
            profitable_df = df[df["PE"] > 0]
            if not profitable_df.empty:
                lowest_pe = profitable_df.loc[profitable_df["PE"].idxmin()]
                kpi_col2.metric("💎 Lowest Valuation (P/E)", f"{lowest_pe['Company']}", f"{lowest_pe['PE']:.1f}x P/E")
            else:
                kpi_col2.metric("💎 Lowest Valuation (P/E)", "N/A", "No Profitable Stocks")
                
            industrial_df = df[df["Altman Z"].notnull()]
            if not industrial_df.empty:
                safest_z = industrial_df.loc[industrial_df["Altman Z"].idxmax()]
                kpi_col3.metric("🛡️ Safest Solvency (Altman Z)", f"{safest_z['Company']}", f"Z-Score {safest_z['Altman Z']:.2f}")
            else:
                kpi_col3.metric("🛡️ Safest Solvency (Altman Z)", "Banking Cohort", "N/A (Financials)")

            st.divider()

            selection = st.multiselect(
                "Select Companies for Deep Analysis:", 
                df["Company"].unique(), 
                default=df["Company"].unique()[:min(4, len(df))]
            )
            
            if selection:
                subset = df[df["Company"].isin(selection)]
                for _, row in subset.iterrows():
                    with st.expander(f"All 12 Metrics Plain-English Guide: {row['Company']} ({row['Sector_Type']})", expanded=True):
                        st.markdown(generate_extreme_beginner_translator(row))

        # ─────────────────────────────────────────────────────────────────────────
        # TAB 3: EXHAUSTIVE PROS & CONS
        # ─────────────────────────────────────────────────────────────────────────
        with tab3:
            st.subheader("⚖️ Exhaustive Pros & Cons Matrix")
            
            if selection:
                subset = df[df["Company"].isin(selection)]
                for _, row in subset.iterrows():
                    with st.expander(f"Deep Strengths & Vulnerabilities: {row['Company']}", expanded=True):
                        st.markdown(generate_pros_and_cons(row))

        # ─────────────────────────────────────────────────────────────────────────
        # TAB 4: ACTIONABLE BUY/SELL STRATEGY & EXECUTIVE SUMMARY
        # ─────────────────────────────────────────────────────────────────────────
        with tab4:
            st.subheader("🚦 Actionable Trading Framework & Executive Summary")
            
            if selection:
                subset = df[df["Company"].isin(selection)]
                
                # Show Executive Summary comparing cohort
                st.markdown(generate_beginner_executive_summary(subset))
                st.divider()
                
                for _, row in subset.iterrows():
                    with st.expander(f"Decision Rules & Game-Changer Catalysts: {row['Company']}", expanded=True):
                        tag_html, framework_md = generate_actionable_triggers_framework(row)
                        st.markdown(tag_html, unsafe_allow_html=True)
                        st.markdown(framework_md)

        # ─────────────────────────────────────────────────────────────────────────
        # TAB 5: VISUAL ANALYTICS (PLOTLY)
        # ─────────────────────────────────────────────────────────────────────────
        with tab5:
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
        # TAB 6: AUTOMATED RISK AUDITOR
        # ─────────────────────────────────────────────────────────────────────────
        with tab6:
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
        # TAB 7: OFFLINE REPORT EXPORT
        # ─────────────────────────────────────────────────────────────────────────
        with tab7:
            st.subheader("📄 Institutional Research Export Engine")
            
            export_sub = df[df["Company"].isin(selection)] if selection else df

            report = f"# INSTITUTIONAL EQUITY RESEARCH REPORT & BEGINNER GUIDE\n"
            report += f"Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            report += f"Total Companies Analyzed: {len(export_sub)}\n\n"
            report += "=" * 80 + "\n\n"
            
            report += "## 1. COHORT SUMMARY GRID\n\n"
            report += dataframe_to_markdown_table(export_sub[["Company", "Sector_Type", "Market Cap", "PE", "EV/EBITDA", "ROE %", "ROCE %", "D/E", "Piotroski", "Zone"]])
            report += "\n\n" + "=" * 80 + "\n\n"
            
            report += generate_beginner_executive_summary(export_sub)
            report += "\n\n" + "=" * 80 + "\n\n"
            
            report += "## 2. EXTREME PLAIN-ENGLISH TRANSLATOR & LIMITATIONS (ALL 12 METRICS)\n\n"
            for _, row in export_sub.iterrows():
                report += f"### {row['Company']} ({row['Sector_Type']})\n\n"
                report += generate_extreme_beginner_translator(row)
                report += "\n\n" + "-" * 60 + "\n\n"
            
            report += "=" * 80 + "\n\n"
            report += "## 3. EXHAUSTIVE PROS & CONS\n\n"
            for _, row in export_sub.iterrows():
                report += generate_pros_and_cons(row)
                report += "\n\n" + "-" * 60 + "\n\n"

            report += "=" * 80 + "\n\n"
            report += "## 4. ACTIONABLE BUY / SELL / HOLD STRATEGY & TRIGGERS\n\n"
            for _, row in export_sub.iterrows():
                _, framework_md = generate_actionable_triggers_framework(row)
                report += framework_md
                report += "\n\n" + "=" * 60 + "\n\n"

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
