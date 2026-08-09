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
              f"-
