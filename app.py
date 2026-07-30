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

# ─────────────────────────────────────────────────────────────────────────────
# SQLite Helpers
# ─────────────────────────────────────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS stock_evaluations (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                saved_at     TEXT,
                company_name TEXT,
                ticker       TEXT,
                cmp          REAL,
                market_cap   REAL,
                roe          REAL,
                cfo_pat      REAL,
                de_ratio     REAL,
                pe_current   REAL,
                pe_5yr_avg   REAL,
                sales_growth_10y REAL,
                pat_growth_10y   REAL,
                dcf_value    REAL,
                graham_value REAL,
                dhandho_value REAL,
                step1        INTEGER,
                step2        INTEGER,
                step3        INTEGER,
                step4        INTEGER,
                step5        INTEGER,
                total_score  INTEGER,
                verdict      TEXT,
                narrative    TEXT,
                pdf_path     TEXT
            )
        """)
        conn.commit()

def save_evaluation(row: dict):
    with get_db() as conn:
        conn.execute("""
            INSERT INTO stock_evaluations (
                saved_at, company_name, ticker, cmp, market_cap,
                roe, cfo_pat, de_ratio, pe_current, pe_5yr_avg,
                sales_growth_10y, pat_growth_10y,
                dcf_value, graham_value, dhandho_value,
                step1, step2, step3, step4, step5, total_score,
                verdict, narrative, pdf_path
            ) VALUES (
                :saved_at, :company_name, :ticker, :cmp, :market_cap,
                :roe, :cfo_pat, :de_ratio, :pe_current, :pe_5yr_avg,
                :sales_growth_10y, :pat_growth_10y,
                :dcf_value, :graham_value, :dhandho_value,
                :step1, :step2, :step3, :step4, :step5, :total_score,
                :verdict, :narrative, :pdf_path
            )
        """, row)
        conn.commit()

def load_all_evaluations():
    with get_db() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM stock_evaluations ORDER BY saved_at DESC"
        ).fetchall()]

def delete_evaluation(eval_id: int):
    with get_db() as conn:
        conn.execute("DELETE FROM stock_evaluations WHERE id=?", (eval_id,))
        conn.commit()

init_db()

# ─────────────────────────────────────────────────────────────────────────────
# Parsing & Metric Extraction Helpers
# ─────────────────────────────────────────────────────────────────────────────

METRIC_ALIASES = {
    "cmp": ["Current Price", "CMP", "Price", "Current Price (INR)", "Market Price"],
    "market_cap": ["Market Capitalization", "Market Cap", "Market Cap (Cr)"],
    "pe": ["Stock P/E", "Price to Earning", "P/E", "PE Ratio", "TTM P/E", "Price to Earnings"],
    "pe_5yr_avg": ["5 Year Avg PE", "5-Year P/E", "5Yr PE", "Median PE", "Average PE"],
    "roe": ["Return on equity", "ROE", "Return on Equity %", "ROAE", "Latest FY ROAE"],
    "roce": ["Return on capital employed", "ROCE"],
    "de": ["Debt to equity", "Debt/Equity", "D/E", "Debt to Equity Ratio"],
    "cfo": ["Cash from Operating Activity", "Operating Cash Flow", "CFO", "Net Cash from Operating"],
    "fcf": ["Free Cash Flow", "FCF"],
    "sales": ["Sales", "Revenue", "Net Sales", "Total Revenue"],
    "pat": ["Net Profit", "PAT", "Profit after tax", "Profit For The Period"],
    "reserves": ["Reserves"],
    "equity_sc": ["Equity Share Capital", "Share Capital"],
    "borrowings": ["Borrowings", "Total Debt", "Long term Borrowings"],
    "capex": ["Capital Expenditure", "Capex", "Purchase of fixed assets"],
    "intrinsic": ["Intrinsic Value", "Fair Value", "DCF Value", "Graham Value", "Dhandho Value"],
}

def to_num(val):
    """Safely convert any cell value into a float, stripping symbols and formatting."""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    s = str(val).strip()
    if not s or s.lower() in ("na", "n/a", "-", "—", "nan", "none", "#n/a"):
        return None
    
    # Remove symbols and common suffixes
    s = s.replace("\u20b9", "").replace("₹", "").replace("Rs.", "").replace("Rs", "").replace(",", "")
    s = re.sub(r"\s*(cr|crores?|lakh|lac|%|x|×|times|inr)\.?\s*$", "", s, flags=re.I)
    
    # Handle accounting parentheses: (100.0) -> -100.0
    if s.startswith("(") and s.endswith(")"):
        s = "-" + s[1:-1]
    
    try:
        return float(s)
    except (ValueError, TypeError):
        # Last resort: find any number in the string
        match = re.search(r"-?\d+(?:\.\d+)?", s)
        if match:
            return float(match.group())
        return None

def find_metric_in_df(df, aliases):
    """
    Scans entire DataFrame for a label matching aliases.
    Returns the first numeric value found to the right of that label.
    """
    if df is None or df.empty:
        return None
    
    aliases_norm = [a.lower().strip() for a in aliases]
    
    for r_idx in range(len(df)):
        row = df.iloc[r_idx]
        for c_idx in range(len(row)):
            cell_val = str(row.iloc[c_idx]).lower().strip()
            if any(alias == cell_val or alias in cell_val for alias in aliases_norm):
                # Found label, now look to the right for the first number
                for next_val in row.iloc[c_idx + 1:]:
                    num = to_num(next_val)
                    if num is not None:
                        return num
    return None

def find_series_in_df(df, aliases):
    """
    Scans entire DataFrame for a label and returns all numeric values in that row.
    Used for historical data like Sales or PAT.
    """
    if df is None or df.empty:
        return []
    
    aliases_norm = [a.lower().strip() for a in aliases]
    
    for r_idx in range(len(df)):
        row = df.iloc[r_idx]
        for c_idx in range(len(row)):
            cell_val = str(row.iloc[c_idx]).lower().strip()
            if any(alias == cell_val or alias in cell_val for alias in aliases_norm):
                # Found label, extract all following numeric values
                nums = [to_num(v) for v in row.iloc[c_idx + 1:] if to_num(v) is not None]
                if nums:
                    return nums
    return []

def cagr(start, end, years):
    if start and end and years and start > 0:
        try:
            return ((end / start) ** (1 / years) - 1) * 100
        except:
            return None
    return None

# ─────────────────────────────────────────────────────────────────────────────
# Core Parser
# ─────────────────────────────────────────────────────────────────────────────

def parse_file(file) -> dict:
    data = {}
    is_csv = file.name.endswith(".csv")

    try:
        if is_csv:
            df_main = pd.read_csv(file, header=None, dtype=str)
            sheets = {"Data": df_main}
        else:
            xl = pd.ExcelFile(file, engine="openpyxl")
            sheets = {name: pd.read_excel(xl, sheet_name=name, header=None, dtype=str) for name in xl.sheet_names}
    except Exception as e:
        st.error(f"Error reading file: {e}")
        return {}

    # Combine all DataFrames for a global search, but prioritize specific sheets
    all_dfs = list(sheets.values())
    
    # Extract Company Name (Usually top left of first sheet)
    try:
        data["company_name"] = str(all_dfs[0].iloc[0, 1]).strip() if not all_dfs[0].empty else "Unknown"
    except:
        data["company_name"] = "Unknown"

    # Scalar Metrics
    data["cmp"] = None
    data["market_cap"] = None
    data["pe"] = None
    data["pe_5yr_avg"] = None
    data["roe"] = None
    data["de"] = None
    data["roce"] = None

    for df in all_dfs:
        if data["cmp"] is None: data["cmp"] = find_metric_in_df(df, METRIC_ALIASES["cmp"])
        if data["market_cap"] is None: data["market_cap"] = find_metric_in_df(df, METRIC_ALIASES["market_cap"])
        if data["pe"] is None: data["pe"] = find_metric_in_df(df, METRIC_ALIASES["pe"])
        if data["pe_5yr_avg"] is None: data["pe_5yr_avg"] = find_metric_in_df(df, METRIC_ALIASES["pe_5yr_avg"])
        if data["roe"] is None: data["roe"] = find_metric_in_df(df, METRIC_ALIASES["roe"])
        if data["de"] is None: data["de"] = find_metric_in_df(df, METRIC_ALIASES["de"])
        if data["roce"] is None: data["roce"] = find_metric_in_df(df, METRIC_ALIASES["roce"])

    # Series Metrics (Growth)
    sales_series = []
    pat_series = []
    cfo_series = []
    fcf_series = []
    capex_series = []
    
    for df in all_dfs:
        if not sales_series: sales_series = find_series_in_df(df, METRIC_ALIASES["sales"])
        if not pat_series: pat_series = find_series_in_df(df, METRIC_ALIASES["pat"])
        if not cfo_series: cfo_series = find_series_in_df(df, METRIC_ALIASES["cfo"])
        if not fcf_series: fcf_series = find_series_in_df(df, METRIC_ALIASES["fcf"])
        if not capex_series: capex_series = find_series_in_df(df, METRIC_ALIASES["capex"])

    data["net_profit_latest"] = pat_series[-1] if pat_series else None
    data["cfo"] = cfo_series[-1] if cfo_series else None
    data["fcf"] = fcf_series[-1] if fcf_series else None
    data["capex_latest"] = capex_series[-1] if capex_series else None
    
    # Growth calculations
    if len(sales_series) >= 10: data["sales_growth_10y"] = cagr(sales_series[-11], sales_series[-1], 10)
    elif len(sales_series) >= 2: data["sales_growth_10y"] = cagr(sales_series[0], sales_series[-1], len(sales_series)-1)
    else: data["sales_growth_10y"] = None

    if len(pat_series) >= 10: data["pat_growth_10y"] = cagr(pat_series[-11], pat_series[-1], 10)
    elif len(pat_series) >= 2: data["pat_growth_10y"] = cagr(pat_series[0], pat_series[-1], len(pat_series)-1)
    else: data["pat_growth_10y"] = None
    
    data["pat_growth_3y"] = cagr(pat_series[-4], pat_series[-1], 3) if len(pat_series) >= 4 else None

    # Ratio derived
    if data["cfo"] and data["net_profit_latest"]:
        data["cfo_pat"] = data["cfo"] / data["net_profit_latest"]
    else:
        data["cfo_pat"] = None

    # Intrinsic values
    data["dcf_value"] = None
    data["graham_value"] = None
    data["dhandho_value"] = None
    for df in all_dfs:
        if data["dcf_value"] is None: data["dcf_value"] = find_metric_in_df(df, ["DCF Value", "Intrinsic Value"])
        if data["graham_value"] is None: data["graham_value"] = find_metric_in_df(df, ["Graham Value", "Ben Graham Value"])
        if data["dhandho_value"] is None: data["dhandho_value"] = find_metric_in_df(df, ["Dhandho Value"])

    data["pat_series"] = pat_series
    data["sales_series"] = sales_series
    
    return data

# ─────────────────────────────────────────────────────────────────────────────
# 6-Step Scorecard & Narrative
# ─────────────────────────────────────────────────────────────────────────────

def run_scorecard(data: dict, governance_ok: bool, beta_value: float) -> dict:
    roe = data.get("roe")
    cfo_pat = data.get("cfo_pat")
    fcf = data.get("fcf")
    pe = data.get("pe")
    pe_5avg = data.get("pe_5yr_avg")

    def check(cond): return 1 if cond else 0

    s1 = check(roe >= 15.0) if roe is not None else None
    
    s2_cond = (cfo_pat is not None and cfo_pat >= 0.80) and (fcf is not None and fcf > 0)
    s2 = check(s2_cond) if cfo_pat is not None else None
    
    s3 = check(pe <= pe_5avg * 1.10) if pe is not None and pe_5avg is not None else None
    s4 = 1 if governance_ok else 0
    s5 = 1 if abs(beta_value - TARGET_BETA) <= BETA_TOLERANCE else 0

    steps = [s1, s2, s3, s4, s5]
    valid_steps = [s for s in steps if s is not None]
    
    return {
        "s1": s1, "s2": s2, "s3": s3, "s4": s4, "s5": s5,
        "total": sum(valid_steps),
        "max": len(valid_steps),
        "steps_raw": steps
    }

def build_narrative(data: dict, scorecard: dict) -> dict:
    # Simplified logic for brevity, ensuring no None errors
    company = data.get("company_name", "The company")
    strengths, weaknesses, red_flags = [], [], []
    
    roe = data.get("roe", 0) or 0
    if roe >= 15: strengths.append(f"Strong ROE of {roe:.1f}%, indicating efficient capital use.")
    else: weaknesses.append(f"ROE of {roe:.1f}% is below the 15% quality threshold.")
    
    cfo_pat = data.get("cfo_pat", 0) or 0
    if cfo_pat >= 0.8: strengths.append(f"High cash conversion ({cfo_pat:.2f}x CFO/PAT).")
    else: red_flags.append(f"Low cash conversion ({cfo_pat:.2f}x CFO/PAT); reported profits aren't matching cash.")

    score = scorecard["total"]
    if score >= 4: verdict = "Strong buy candidate based on quantitative framework."
    elif score >= 3: verdict = "Moderate quality; watch valuation or cash flow improvements."
    else: verdict = "High risk; fails multiple core quality checks."

    return {
        "strengths": strengths,
        "weaknesses": weaknesses,
        "red_flags": red_flags,
        "verdict": verdict
    }

# ─────────────────────────────────────────────────────────────────────────────
# UI Utilities
# ─────────────────────────────────────────────────────────────────────────────

def fmt(v, d=2, sfx=""):
    if v is None: return "N/A"
    return f"{v:,.{d}f}{sfx}"

def step_box(label: str, passed, detail: str = ""):
    if passed is None:
        st.warning(f"⚠️ **{label}** — Data Missing")
    elif passed:
        st.success(f"✅ **{label}** — PASS ({detail})")
    else:
        st.error(f"❌ **{label}** — FAIL ({detail})")

# ─────────────────────────────────────────────────────────────────────────────
# Main Streamlit App
# ─────────────────────────────────────────────────────────────────────────────

with st.sidebar:
    st.title("🏦 Framework Guide")
    st.info("Step 1: ROE > 15%\n\nStep 2: CFO/PAT > 0.8 & +ve FCF\n\nStep 3: P/E < 5Yr Avg + 10%\n\nStep 4: Clean Governance\n\nStep 5: Beta ~1.1")

tab_eval, tab_vault = st.tabs(["📊 Evaluate Stock", "🗃️ Portfolio Vault"])

with tab_eval:
    st.title("Master Stock Evaluator")
    
    col1, col2 = st.columns(2)
    with col1:
        uploaded_excel = st.file_uploader("Upload Screener Excel", type=["xlsx", "csv"])
    with col2:
        ticker = st.text_input("Ticker Symbol", "TICKER").upper()
        gov_ok = st.checkbox("Verified: 0% Pledging & Clean Audit")
        beta = st.number_input("Beta", value=1.1, step=0.1)

    if uploaded_excel:
        data = parse_file(uploaded_excel)
        if data:
            scorecard = run_scorecard(data, gov_ok, beta)
            narrative = build_narrative(data, scorecard)
            
            st.header(f"🏢 {data['company_name']} ({ticker})")
            
            # Metric Cards
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Price", fmt(data['cmp']))
            m2.metric("ROE %", fmt(data['roe'], 1, "%"))
            m3.metric("P/E", fmt(data['pe'], 1))
            m4.metric("D/E", fmt(data['de'], 2))

            # Scorecard
            st.subheader("Framework Scorecard")
            step_box("Business Quality (ROE)", scorecard['s1'], f"ROE: {fmt(data['roe'])}%")
            step_box("Cash Realism (CFO/PAT)", scorecard['s2'], f"CFO/PAT: {fmt(data['cfo_pat'])}")
            step_box("Valuation Margin", scorecard['s3'], f"Current PE: {fmt(data['pe'])}")
            step_box("Governance", scorecard['s4'], "Verified" if gov_ok else "Pending")
            step_box("Portfolio Fit (Beta)", scorecard['s5'], f"Beta: {beta}")

            # Verdict
            total_score = scorecard['total']
            if total_score >= 4:
                st.balloons()
                st.success(f"### FINAL VERDICT: APPROVED ({total_score}/5)")
            else:
                st.error(f"### FINAL VERDICT: REJECTED ({total_score}/5)")

            # Narrative expanders
            with st.expander("Analysis Details"):
                st.write("**Strengths:**")
                for s in narrative['strengths']: st.write(f"- {s}")
                st.write("**Red Flags:**")
                for r in narrative['red_flags']: st.write(f"- {r}")
                st.info(narrative['verdict'])

            if st.button("💾 Save to Vault"):
                save_evaluation({
                    "saved_at": datetime.datetime.now().isoformat(),
                    "company_name": data['company_name'],
                    "ticker": ticker,
                    "cmp": data['cmp'],
                    "market_cap": data['market_cap'],
                    "roe": data['roe'],
                    "cfo_pat": data['cfo_pat'],
                    "de_ratio": data['de'],
                    "pe_current": data['pe'],
                    "pe_5yr_avg": data['pe_5yr_avg'],
                    "sales_growth_10y": data['sales_growth_10y'],
                    "pat_growth_10y": data['pat_growth_10y'],
                    "dcf_value": data['dcf_value'],
                    "graham_value": data['graham_value'],
                    "dhandho_value": data['dhandho_value'],
                    "step1": scorecard['s1'],
                    "step2": scorecard['s2'],
                    "step3": scorecard['s3'],
                    "step4": scorecard['s4'],
                    "step5": scorecard['s5'],
                    "total_score": total_score,
                    "verdict": "APPROVED" if total_score >= 4 else "REJECTED",
                    "narrative": json.dumps(narrative),
                    "pdf_path": ""
                })
                st.success("Saved!")

with tab_vault:
    st.title("Portfolio Vault")
    records = load_all_evaluations()
    if records:
        df_vault = pd.DataFrame(records)
        st.dataframe(df_vault[["saved_at", "company_name", "ticker", "total_score", "verdict"]])
        
        if st.button("Clear All Records"):
            # Minimal safety for deletion
            st.warning("Feature to clear DB manually via SQL or app logic.")
    else:
        st.info("No evaluations saved yet.")
