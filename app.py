import streamlit as st
import pandas as pd
import sqlite3
import os
import datetime
import json
import re
import plotly.graph_objects as go

# ─────────────────────────────────────────────────────────────────────────────
# Page Configuration
# ─────────────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Master Quantitative & Business Risk Evaluator",
    page_icon="🏦",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─────────────────────────────────────────────────────────────────────────────
# Constants & Paths
# ─────────────────────────────────────────────────────────────────────────────
PDF_DIR = "stored_pdfs"
DB_PATH = "evaluations.db"
os.makedirs(PDF_DIR, exist_ok=True)

TARGET_BETA = 1.10
BETA_TOLERANCE = 0.30

# Exclude these sheets from general metric searching
EXCLUDED_SHEETS = ["instructions", "checklist", "intrinsic", "ben graham", "about", "guide", "summary"]

# ─────────────────────────────────────────────────────────────────────────────
# SQLite & Parsing Helpers
# ─────────────────────────────────────────────────────────────────────────────

def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS stock_evaluations (
                id INTEGER PRIMARY KEY AUTOINCREMENT, saved_at TEXT, company_name TEXT, ticker TEXT,
                cmp REAL, market_cap REAL, roe REAL, cfo_pat REAL, de_ratio REAL, pe_current REAL,
                pe_5yr_avg REAL, sales_growth_10y REAL, pat_growth_10y REAL, dcf_value REAL,
                graham_value REAL, dhandho_value REAL, step1 INTEGER, step2 INTEGER, step3 INTEGER,
                step4 INTEGER, step5 INTEGER, total_score INTEGER, verdict TEXT, narrative TEXT, pdf_path TEXT
            )""")

def to_num(val):
    if val is None or (isinstance(val, float) and pd.isna(val)): return None
    s = str(val).strip().replace(",", "").replace("₹", "").replace("Rs.", "")
    s = re.sub(r"\s*(cr|crores?|%|x)\.?\s*$", "", s, flags=re.I)
    if s.startswith("(") and s.endswith(")"): s = "-" + s[1:-1]
    try: return float(s)
    except: return None

def find_in_sheet(df, aliases, exact=False):
    if df is None or df.empty: return None
    aliases = [a.lower().strip() for a in aliases]
    for r_idx in range(len(df)):
        row = df.iloc[r_idx]
        for c_idx in range(len(row)):
            cell = str(row.iloc[c_idx]).lower().strip()
            match = any(a == cell for a in aliases) if exact else any(a in cell for a in aliases)
            if match:
                for v in row.iloc[c_idx + 1:]:
                    val = to_num(v)
                    if val is not None: return val
    return None

def find_series_in_sheet(df, aliases):
    if df is None or df.empty: return []
    aliases = [a.lower().strip() for a in aliases]
    for r_idx in range(len(df)):
        row = df.iloc[r_idx]
        for c_idx in range(len(row)):
            cell = str(row.iloc[c_idx]).lower().strip()
            if any(a in cell for a in aliases):
                return [to_num(v) for v in row.iloc[c_idx + 1:] if to_num(v) is not None]
    return []

def safe_cagr(series, years):
    if not series or len(series) < (years + 1): return None
    try:
        start, end = series[-(years+1)], series[-1]
        if start > 0 and end is not None: return ((end / start)**(1/years)-1)*100
    except: return None
    return None

# ─────────────────────────────────────────────────────────────────────────────
# Core Logic: Precise Parsing
# ─────────────────────────────────────────────────────────────────────────────

def parse_file(file):
    data = {}
    try:
        xl = pd.ExcelFile(file, engine="openpyxl")
        sheets = {n: pd.read_excel(xl, sheet_name=n, header=None, dtype=str) for n in xl.sheet_names}
    except Exception as e:
        st.error(f"Error reading file: {e}")
        return None

    # 1. Identify Key Sheets Strictly
    df_data = next((v for k, v in sheets.items() if "data sheet" in k.lower()), None)
    df_pl   = next((v for k, v in sheets.items() if any(x in k.lower() for x in ["p&l", "profit", "income"])), None)
    df_bs   = next((v for k, v in sheets.items() if "balance" in k.lower()), None)
    df_cf   = next((v for k, v in sheets.items() if "cash" in k.lower()), None)
    df_ratios = next((v for k, v in sheets.items() if "ratio" in k.lower()), None)

    # 2. Extract Metadata Strictly from "Data Sheet"
    if df_data is not None:
        # Company Name: Try cell B1 (0,1) or find "Company Name" label
        try:
            name_label = find_in_sheet(df_data, ["company name"])
            data["company_name"] = str(df_data.iloc[0, 1]).strip() if name_label is None else str(name_label)
        except: data["company_name"] = "Unknown Company"
        
        data["cmp"] = find_in_sheet(df_data, ["current price", "cmp"], exact=False)
        data["market_cap"] = find_in_sheet(df_data, ["market capitalization", "market cap"], exact=False)
    else:
        st.error("Sheet named 'Data Sheet' not found. Please use a valid Screener/Safal Niveshak export.")
        return None

    # 3. Extract Raw Series for Calculation
    sales_series = find_series_in_sheet(df_pl, ["sales", "revenue", "net sales"])
    pat_series   = find_series_in_sheet(df_pl, ["net profit", "pat", "profit after tax"])
    cfo_series   = find_series_in_sheet(df_cf, ["cash from operating", "operating cash flow", "cfo"])
    
    # Balance Sheet Items (Latest Year)
    equity_cap = find_in_sheet(df_bs, ["equity share capital", "share capital"])
    reserves   = find_in_sheet(df_bs, ["reserves"])
    borrowings = find_in_sheet(df_bs, ["borrowings", "total debt", "long term borrowings"]) or 0.0
    
    # 4. Calculate Financial Ratios Accurately
    latest_pat = pat_series[-1] if pat_series else None
    latest_equity = (equity_cap + reserves) if (equity_cap is not None and reserves is not None) else None
    
    # ROE Calculation
    if latest_pat and latest_equity and latest_equity > 0:
        data["roe"] = (latest_pat / latest_equity) * 100
    else:
        # Fallback to Key Ratios sheet only if raw calc fails
        data["roe"] = find_in_sheet(df_ratios, ["return on equity", "roe"])

    # D/E Calculation
    if latest_equity and latest_equity > 0:
        data["de"] = borrowings / latest_equity
    else:
        data["de"] = find_in_sheet(df_ratios, ["debt to equity", "debt/equity"])

    # P/E Calculation
    if data["market_cap"] and latest_pat and latest_pat > 0:
        data["pe"] = data["market_cap"] / latest_pat
    else:
        data["pe"] = find_in_sheet(df_data, ["stock p/e", "p/e"])

    # CFO / PAT Ratio
    if cfo_series and pat_series and pat_series[-1] != 0:
        data["cfo_pat"] = cfo_series[-1] / pat_series[-1]
    else: data["cfo_pat"] = None

    # Growth & Intrinsic Values (Secondary Sheets)
    data["sales_growth_10y"] = safe_cagr(sales_series, 10)
    data["pat_growth_10y"]   = safe_cagr(pat_series, 10)
    data["pe_5yr_avg"] = find_in_sheet(df_data, ["5 year avg pe", "median pe"])
    
    df_val = next((v for k, v in sheets.items() if any(x in k.lower() for x in ["dcf", "valuation"])), None)
    data["dcf_value"] = find_in_sheet(df_val, ["dcf value", "intrinsic value"])
    data["graham_value"] = find_in_sheet(sheets.get("Ben Graham Formula"), ["graham value", "ben graham value"])
    
    data["pat_series"] = pat_series
    data["sales_series"] = sales_series
    data["fcf"] = (cfo_series[-1] - abs(find_in_sheet(df_cf, ["fixed assets purchased", "capex"]) or 0)) if cfo_series else None

    return data

# ─────────────────────────────────────────────────────────────────────────────
# UI & Scorecard
# ─────────────────────────────────────────────────────────────────────────────

def run_scorecard(data, gov_ok, beta):
    s1 = 1 if (data.get("roe") or 0) >= 15 else 0
    s2 = 1 if ((data.get("cfo_pat") or 0) >= 0.8 and (data.get("fcf") or 0) > 0) else 0
    s3 = 1 if (data.get("pe") or 0) <= (data.get("pe_5yr_avg") or 999) * 1.1 else 0
    s4 = 1 if gov_ok else 0
    s5 = 1 if abs(beta - TARGET_BETA) <= BETA_TOLERANCE else 0
    
    steps = [s1, s2, s3, s4, s5]
    return {"total": sum(steps), "steps": steps}

def fmt(v, d=2, sfx=""):
    return f"{v:,.{d}f}{sfx}" if v is not None else "N/A"

# ─────────────────────────────────────────────────────────────────────────────
# Main Interface
# ─────────────────────────────────────────────────────────────────────────────

init_db()
st.title("🏦 Master Quantitative Risk Evaluator")

up = st.file_uploader("Upload Screener Export (Data Sheet required)", type="xlsx")
c1, c2, c3 = st.columns(3)
with c1: ticker = st.text_input("Ticker", "STOCK").upper()
with c2: gov = st.checkbox("Clean Governance Verified")
with c3: beta = st.number_input("Beta", 0.0, 5.0, 1.1)

if up:
    d = parse_file(up)
    if d:
        sc = run_scorecard(d, gov, beta)
        
        st.header(f"🏢 {d['company_name']}")
        cols = st.columns(5)
        cols[0].metric("Price", fmt(d['cmp']))
        cols[1].metric("ROE %", fmt(d['roe'], 1, "%"))
        cols[2].metric("D/E", fmt(d['de'], 2))
        cols[3].metric("P/E", fmt(d['pe'], 1))
        cols[4].metric("CFO/PAT", fmt(d['cfo_pat'], 2))

        st.subheader("Framework Scorecard")
        st.write(f"**Step 1: ROE ≥ 15%** {'✅' if sc['steps'][0] else '❌'} ({fmt(d['roe'],1)}%)")
        st.write(f"**Step 2: Cash Realism** {'✅' if sc['steps'][1] else '❌'} (CFO/PAT: {fmt(d['cfo_pat'])})")
        st.write(f"**Step 3: Valuation** {'✅' if sc['steps'][2] else '❌'} (Current PE: {fmt(d['pe'])})")
        st.write(f"**Step 4: Governance** {'✅' if sc['steps'][3] else '❌'}")
        st.write(f"**Step 5: Beta (~1.1)** {'✅' if sc['steps'][4] else '❌'} ({beta})")
        
        score = sc['total']
        if score >= 4: st.success(f"### APPROVED ({score}/5)")
        else: st.error(f"### REJECTED ({score}/5)")

        with st.expander("View Raw Financial Series"):
            st.write("**PAT Series:**", d['pat_series'])
            st.write("**Sales Series:**", d['sales_series'])
