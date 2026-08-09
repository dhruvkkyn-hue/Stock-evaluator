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
# 3. BEGINNER TRANSLATOR & ACTIONABLE TRIGGER ENGINE
# ─────────────────────────────────────────────────────────────────────────────

def generate_beginner_metric_translator(row):
    """
    Generates plain-English beginner explanations, benchmark signals [🟢 STRONG], [🟡 AVERAGE], [🔴 WEAK],
    and stock-specific breakdown for each key financial metric.
    """
    comp = row["Company"]
    is_fin = row["Is_Financial"]
    
    # 1. Market Capitalization
    mcap = row["Market Cap"]
    if mcap >= 50000:
        mcap_sig = "[🟢 STRONG]"
        mcap_eval = f"₹{mcap:,.0f} Cr places {comp} as a Large-Cap giant, providing high liquidity and stability."
    elif mcap >= 15000:
        mcap_sig = "[🟡 AVERAGE]"
        mcap_eval = f"₹{mcap:,.0f} Cr makes {comp} a Mid-Cap stock, offering a balanced mix of growth potential and stability."
    else:
        mcap_sig = "[🟡 AVERAGE]"
        mcap_eval = f"₹{mcap:,.0f} Cr places {comp} as a Small-Cap firm with high growth upside but higher market volatility."
        
    mcap_text = f"**1. Market Capitalization (Company Size) {mcap_sig}**\n" \
                f"- *Beginner Explanation:* Think of Market Cap as the total price tag to buy the entire company today.\n" \
                f"- *Stock Insight:* {mcap_eval}\n"

    # 2. P/E Ratio
    pe = row["PE"]
    if pe > 0:
        if pe <= 20:
            pe_sig = "[🟢 STRONG]"
            pe_eval = f"At {pe:.1f}x earnings, the stock is reasonably priced relative to its profit generation."
        elif pe <= 40:
            pe_sig = "[🟡 AVERAGE]"
            pe_eval = f"At {pe:.1f}x earnings, investors are paying a moderate premium for expected future growth."
        else:
            pe_sig = "[🔴 WEAK]"
            pe_eval = f"At a high {pe:.1f}x P/E multiple, the stock is expensive, requiring high future profit growth to justify its price."
    else:
        pe_sig = "[🔴 WEAK]"
        pe_eval = "P/E is negative because the company reported a net loss recently."

    pe_text = f"**2. P/E Ratio (Valuation Price Tag) {pe_sig}**\n" \
              f"- *Beginner Explanation:* Think of P/E as how many dollars you are paying for every $1 of annual profit the company earns.\n" \
              f"- *Stock Insight:* {pe_eval}\n"

    # 3. Profitability (OPM %)
    opm = row["OPM %"]
    if is_fin:
        if opm >= 20:
            opm_sig = "[🟢 STRONG]"
            opm_eval = f"Net Margin is strong at {opm:.1f}%, showing high efficiency in converting income to net profit."
        elif opm >= 10:
            opm_sig = "[🟡 AVERAGE]"
            opm_eval = f"Net Margin is fair at {opm:.1f}%."
        else:
            opm_sig = "[🔴 WEAK]"
            opm_eval = f"Net Margin is thin at {opm:.1f}%, leaving little margin for credit losses."
        opm_name = "Net Margin (Banking Profitability)"
    else:
        if opm >= 18:
            opm_sig = "[🟢 STRONG]"
            opm_eval = f"OPM is healthy at {opm:.1f}%, keeping over 18 cents of profit for every dollar sold."
        elif opm >= 10:
            opm_sig = "[🟡 AVERAGE]"
            opm_eval = f"OPM is average at {opm:.1f}%, keeping 10-18 cents per dollar sold."
        else:
            opm_sig = "[🔴 WEAK]"
            opm_eval = f"OPM is low at {opm:.1f}%, meaning raw material or operating costs absorb most revenue."
        opm_name = "Operating Profit Margin (OPM %)"

    opm_text = f"**3. {opm_name} {opm_sig}**\n" \
               f"- *Beginner Explanation:* Think of OPM as how much cash profit the company keeps out of every $100 it collects in sales after paying production costs.\n" \
               f"- *Stock Insight:* {opm_eval}\n"

    # 4. ROE %
    roe = row["ROE %"]
    if roe >= 18:
        roe_sig = "[🟢 STRONG]"
        roe_eval = f"ROE of {roe:.1f}% shows excellent compounding efficiency on shareholder equity."
    elif roe >= 12:
        roe_sig = "[🟡 AVERAGE]"
        roe_eval = f"ROE of {roe:.1f}% represents steady, solid return on shareholder capital."
    else:
        roe_sig = "[🔴 WEAK]"
        roe_eval = f"ROE of {roe:.1f}% is weak, indicating low profit yield on invested equity."

    roe_text = f"**4. Return on Equity (ROE %) {roe_sig}**\n" \
               f"- *Beginner Explanation:* Think of ROE as how many dollars of profit the company generates for every $100 of shareholders' own money invested.\n" \
               f"- *Stock Insight:* {roe_eval}\n"

    # 5. ROCE %
    roce = row["ROCE %"]
    if roce >= 15:
        roce_sig = "[🟢 STRONG]"
        roce_eval = f"ROCE of {roce:.1f}% proves the company generates high returns on all employed capital (equity + debt)."
    elif roce >= 10:
        roce_sig = "[🟡 AVERAGE]"
        roce_eval = f"ROCE of {roce:.1f}% is adequate."
    else:
        roce_sig = "[🔴 WEAK]"
        roce_eval = f"ROCE of {roce:.1f}% is poor, suggesting low efficiency across physical assets and debt."

    roce_text = f"**5. Return on Capital Employed (ROCE %) {roce_sig}**\n" \
                f"- *Beginner Explanation:* Think of ROCE as how effectively the business earns profits from ALL capital raised (both owner equity and borrowed bank debt).\n" \
                f"- *Stock Insight:* {roce_eval}\n"

    # 6. Debt-to-Equity (D/E)
    de = row["D/E"]
    if is_fin:
        if de <= 6.0:
            de_sig = "[🟢 STRONG]"
            de_eval = f"Banking D/E of {de:.2f}x reflects conservative financial leverage relative to deposits."
        elif de <= 8.5:
            de_sig = "[🟡 AVERAGE]"
            de_eval = f"Banking D/E of {de:.2f}x is within normal deposit-taking leverage bounds."
        else:
            de_sig = "[🔴 WEAK]"
            de_eval = f"Banking D/E of {de:.2f}x is high, requiring diligent credit risk management."
    else:
        if de <= 0.5:
            de_sig = "[🟢 STRONG]"
            de_eval = f"D/E of {de:.2f}x is low, indicating a pristine, low-debt balance sheet."
        elif de <= 1.2:
            de_sig = "[🟡 AVERAGE]"
            de_eval = f"D/E of {de:.2f}x represents manageable borrowing."
        else:
            de_sig = "[🔴 WEAK]"
            de_eval = f"D/E of {de:.2f}x is heavy, meaning the company relies heavily on borrowed funds."

    de_text = f"**6. Debt-to-Equity Ratio (Borrowing Risk) {de_sig}**\n" \
              f"- *Beginner Explanation:* Think of D/E as comparing how much money the business owes to banks versus how much money the owners put in.\n" \
              f"- *Stock Insight:* {de_eval}\n"

    # 7. Sloan Accrual Ratio
    sloan = row["Sloan %"]
    if is_fin or sloan is None:
        sloan_sig = "[🟡 AVERAGE]"
        sloan_eval = "Sloan Ratio is N/A for banks due to specialized loan-loss reserve accounting."
    else:
        if sloan <= 5.0 and sloan >= -10.0:
            sloan_sig = "[🟢 STRONG]"
            sloan_eval = f"Sloan Ratio of {sloan:.1f}% confirms that profits are backed by actual cash receipts."
        elif sloan <= 10.0:
            sloan_sig = "[🟡 AVERAGE]"
            sloan_eval = f"Sloan Ratio of {sloan:.1f}% is acceptable."
        else:
            sloan_sig = "[🔴 WEAK]"
            sloan_eval = f"Sloan Ratio of {sloan:.1f}% (>10%) warns that paper profits exceed actual cash collected."

    sloan_text = f"**7. Sloan Accrual Ratio (Earnings Quality Check) {sloan_sig}**\n" \
                 f"- *Beginner Explanation:* Think of Sloan Ratio as a lie-detector test for profits—it checks if reported income is real cash in the bank or just unpaid IOU promises on paper.\n" \
                 f"- *Stock Insight:* {sloan_eval}\n"

    # 8. Altman Z-Score
    alt_z = row["Altman Z"]
    zone = row["Zone"]
    if is_fin or alt_z is None:
        alt_sig = "[🟢 STRONG]"
        alt_eval = "Altman Z is N/A for banks (regulated by capital adequacy ratios instead)."
    else:
        if zone == "Safe":
            alt_sig = "[🟢 STRONG]"
            alt_eval = f"Altman Z of {alt_z:.2f} puts {comp} in the **Safe Zone**, showing zero insolvency danger."
        elif zone == "Grey":
            alt_sig = "[🟡 AVERAGE]"
            alt_eval = f"Altman Z of {alt_z:.2f} puts {comp} in the **Grey Zone**, suggesting caution."
        else:
            alt_sig = "[🔴 WEAK]"
            alt_eval = f"Altman Z of {alt_z:.2f} puts {comp} in the **Distress Zone**, signaling elevated financial stress."

    alt_text = f"**8. Altman Z-Score (Bankruptcy Health Check) {alt_sig}**\n" \
               f"- *Beginner Explanation:* Think of Altman Z as a doctor's health score for a company's balance sheet; scores above 3.0 mean robust health, while scores below 1.8 warn of bankruptcy risk.\n" \
               f"- *Stock Insight:* {alt_eval}\n"

    # 9. Piotroski F-Score
    p_score = row["Piotroski"]
    if p_score >= 6:
        p_sig = "[🟢 STRONG]"
        p_eval = f"Score of {p_score}/8 shows high financial strength and improving operating momentum."
    elif p_score >= 4:
        p_sig = "[🟡 AVERAGE]"
        p_eval = f"Score of {p_score}/8 indicates stable, average business health."
    else:
        p_sig = "[🔴 WEAK]"
        p_eval = f"Score of {p_score}/8 reveals weak fundamental momentum."

    p_text = f"**9. Piotroski F-Score (9-Point Report Card) {p_sig}**\n" \
             f"- *Beginner Explanation:* Think of Piotroski as a 9-point report card covering profitability, cash flow, debt reduction, and operational efficiency.\n" \
             f"- *Stock Insight:* {p_eval}\n"

    # 10. Free Cash Flow Yield
    fcf_y = row["FCF Yield %"]
    if fcf_y >= 5.0:
        fcf_sig = "[🟢 STRONG]"
        fcf_eval = f"FCF Yield of {fcf_y:.1f}% is high, proving the business generates abundant spare cash."
    elif fcf_y >= 1.0:
        fcf_sig = "[🟡 AVERAGE]"
        fcf_eval = f"FCF Yield of {fcf_y:.1f}% is moderate."
    else:
        fcf_sig = "[🔴 WEAK]"
        fcf_eval = f"FCF Yield of {fcf_y:.1f}% is low or negative due to heavy capital spending or cash drain."

    fcf_text = f"**10. Free Cash Flow Yield (Spare Cash Power) {fcf_sig}**\n" \
               f"- *Beginner Explanation:* Think of Free Cash Flow as the money left in your wallet after paying for your house, food, and bills. FCF Yield compares this spare cash to the company's price tag.\n" \
               f"- *Stock Insight:* {fcf_eval}\n"

    return "\n".join([mcap_text, pe_text, opm_text, roe_text, roce_text, de_text, sloan_text, alt_text, p_text, fcf_text])

def generate_actionable_triggers_framework(row):
    """
    Generates explicit BUY / ACCUMULATE Triggers, SELL / EXIT Triggers, and Current Signal Summary tag.
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

    # Calculate overall rating tag
    score_points = 0
    if roe >= 15: score_points += 1
    if pe > 0 and pe <= 25: score_points += 1
    if de <= 0.8 or (is_fin and de <= 7.0): score_points += 1
    if p_score >= 6: score_points += 1
    if fcf_y >= 3.0: score_points += 1
    if zone == "Safe" or is_fin: score_points += 1

    if score_points >= 5:
        signal_tag = "STRONG BUY"
        tag_html = f"<div class='signal-tag-strong-buy'>🟢 OVERALL RATING: [STRONG BUY]</div>"
    elif score_points >= 3:
        signal_tag = "ACCUMULATE ON DIPS"
        tag_html = f"<div class='signal-tag-accumulate'>🔵 OVERALL RATING: [ACCUMULATE ON DIPS]</div>"
    elif score_points >= 2:
        signal_tag = "HOLD / WATCHLIST"
        tag_html = f"<div class='signal-tag-hold'>🟡 OVERALL RATING: [HOLD / WATCHLIST]</div>"
    else:
        signal_tag = "AVOID / EXIT"
        tag_html = f"<div class='signal-tag-avoid'>🔴 OVERALL RATING: [AVOID / EXIT]</div>"

    # Actionable Triggers
    buy_triggers = [
        f"Buy if P/E drops below 25.0x (currently {pe:.1f}x) while ROE remains strong above 15.0%.",
        f"Accumulate if Free Cash Flow Yield expands above 4.0% (currently {fcf_y:.1f}%), confirming high cash generation.",
        f"Buy/Add if Piotroski Quality Score remains >= 6/8 (currently {p_score}/8) alongside debt reduction."
    ]

    sell_triggers = [
        f"Sell/Exit if Altman Z-Score falls below 1.81 into Distress Zone (currently {zone}).",
        f"Exit if Debt-to-Equity ratio exceeds 1.5x (currently {de:.2f}x) due to unmanaged borrowing.",
        f"Sell/Avoid if Sloan Accrual Ratio spikes above 10.0%" + (f" (currently {sloan:.1f}%)" if sloan is not None else "") + " indicating paper profit accounting disconnect."
    ]

    buy_str = "\n".join([f"- 🟢 **Rule {idx+1}:** {bt}" for idx, bt in enumerate(buy_triggers)])
    sell_str = "\n".join([f"- 🔴 **Rule {idx+1}:** {st}" for idx, st in enumerate(sell_triggers)])

    framework_md = f"### 🚦 Actionable Trading & Investment Framework for {comp}\n\n" \
                   f"**Current Signal:** `[{signal_tag}]`\n\n" \
                   f"#### 🎯 Exact BUY / ACCUMULATE Rules:\n{buy_str}\n\n" \
                   f"#### ⚠️ Exact SELL / EXIT Rules:\n{sell_str}\n"

    return tag_html, framework_md

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
    st.caption(f"Institutional Terminal v4.0 | {datetime.now().year}")

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
        
        tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
            "📊 Matrix", "💡 Beginner Translator", "🚦 Actionable Strategy", 
            "📈 Visuals", "🚨 Risk Audit", "📄 Export Report"
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
        # TAB 2: PLAIN-ENGLISH BEGINNER TRANSLATOR
        # ─────────────────────────────────────────────────────────────────────────
        with tab2:
            st.subheader("💡 Plain-English Beginner Metric Translator")
            
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
                "Select Companies for Beginner Translation:", 
                df["Company"].unique(), 
                default=df["Company"].unique()[:min(4, len(df))]
            )
            
            if selection:
                subset = df[df["Company"].isin(selection)]
                for _, row in subset.iterrows():
                    with st.expander(f"Beginner Guide & Metric Signals: {row['Company']} ({row['Sector_Type']})", expanded=True):
                        st.markdown(generate_beginner_metric_translator(row))

        # ─────────────────────────────────────────────────────────────────────────
        # TAB 3: ACTIONABLE BUY/SELL STRATEGY & TRIGGERS
        # ─────────────────────────────────────────────────────────────────────────
        with tab3:
            st.subheader("🚦 Actionable Trading & Investment Framework")
            
            if selection:
                subset = df[df["Company"].isin(selection)]
                for _, row in subset.iterrows():
                    with st.expander(f"Trading Triggers & Signals: {row['Company']}", expanded=True):
                        tag_html, framework_md = generate_actionable_triggers_framework(row)
                        st.markdown(tag_html, unsafe_allow_html=True)
                        st.markdown(framework_md)

        # ─────────────────────────────────────────────────────────────────────────
        # TAB 4: VISUAL ANALYTICS (PLOTLY)
        # ─────────────────────────────────────────────────────────────────────────
        with tab4:
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
        # TAB 5: AUTOMATED RISK AUDITOR
        # ─────────────────────────────────────────────────────────────────────────
        with tab5:
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
        # TAB 6: OFFLINE REPORT EXPORT
        # ─────────────────────────────────────────────────────────────────────────
        with tab6:
            st.subheader("📄 Institutional Research Export Engine")
            
            export_sub = df[df["Company"].isin(selection)] if selection else df

            report = f"# INSTITUTIONAL EQUITY RESEARCH REPORT & BEGINNER GUIDE\n"
            report += f"Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            report += f"Total Companies Analyzed: {len(export_sub)}\n\n"
            report += "=" * 80 + "\n\n"
            
            report += "## 1. COHORT SUMMARY GRID\n\n"
            report += dataframe_to_markdown_table(export_sub[["Company", "Sector_Type", "Market Cap", "PE", "ROE %", "ROCE %", "D/E", "Piotroski", "Zone"]])
            report += "\n\n" + "=" * 80 + "\n\n"
            
            report += "## 2. PLAIN-ENGLISH BEGINNER METRIC TRANSLATOR & SIGNALS\n\n"
            for _, row in export_sub.iterrows():
                report += f"### {row['Company']} ({row['Sector_Type']})\n\n"
                report += generate_beginner_metric_translator(row)
                report += "\n\n" + "-" * 60 + "\n\n"
            
            report += "=" * 80 + "\n\n"
            report += "## 3. ACTIONABLE BUY / SELL / HOLD STRATEGY & TRIGGERS\n\n"
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
