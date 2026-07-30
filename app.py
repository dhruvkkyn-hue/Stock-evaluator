"""
Master Quantitative & Business Risk Evaluator
for Indian Stocks (NSE/BSE) — Screener.in / Safal Niveshak exports
"""

import streamlit as st
import pandas as pd
import sqlite3
import os
import shutil
import datetime
import json
import re
import plotly.graph_objects as go

# ─────────────────────────────────────────────────────────────────────────────
# Page config
# ─────────────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Master Quantitative & Business Risk Evaluator",
    page_icon="🏦",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─────────────────────────────────────────────────────────────────────────────
# Constants & paths
# ─────────────────────────────────────────────────────────────────────────────
PDF_DIR = "stored_pdfs"
DB_PATH = "evaluations.db"
os.makedirs(PDF_DIR, exist_ok=True)

TARGET_BETA = 1.10
BETA_TOLERANCE = 0.30

# ─────────────────────────────────────────────────────────────────────────────
# SQLite helpers
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
# Parsing helpers
# ─────────────────────────────────────────────────────────────────────────────

def to_num(val):
    """Convert a cell value to float; handles Screener formats (₹, Cr, %, x)."""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    s = str(val).strip()
    if not s or s.lower() in ("na", "n/a", "-", "—", "nan", "none", "#n/a"):
        return None
    s = s.replace("\u20b9", "").replace("₹", "").replace("Rs.", "").replace("Rs", "")
    s = s.replace(",", "")
    s = re.sub(r"\s*(cr|crores?|lakh|lac|%|x|×|times|inr)\.?\s*$", "", s, flags=re.I)
    s = s.strip()
    if s.startswith("(") and s.endswith(")"):
        s = "-" + s[1:-1]
    try:
        return float(s)
    except (ValueError, TypeError):
        match = re.search(r"-?\d+(?:\.\d+)?", s)
        if match:
            try:
                return float(match.group())
            except ValueError:
                pass
        return None


def find_row(df: pd.DataFrame, label: str):
    """Return (row, label_col_index) for the first row containing label in any cell."""
    label_lower = label.lower()
    best_row, best_col = None, None
    for _, row in df.iterrows():
        for i, cell in enumerate(row):
            cell_s = str(cell).strip().lower()
            if cell_s in ("nan", "none", ""):
                continue
            if label_lower in cell_s:
                if best_row is None or i < best_col:
                    best_row, best_col = row, i
    if best_row is None:
        return None, None
    return best_row, best_col


def row_latest(df: pd.DataFrame, label: str):
    """Return the rightmost numeric value in a row matching label."""
    nums = row_series(df, label)
    return nums[-1] if nums else None


def row_series(df: pd.DataFrame, label: str):
    """Return all numeric values (left→right) for a row matching label."""
    row, label_col = find_row(df, label)
    if row is None:
        return []
    start = label_col + 1
    return [to_num(v) for v in row.iloc[start:] if to_num(v) is not None]


def scalar_cell(df: pd.DataFrame, label: str, col_idx: int | None = None):
    """Return the first numeric value after the label cell in a matching row."""
    row, label_col = find_row(df, label)
    if row is None:
        return None
    if col_idx is not None:
        try:
            val = to_num(row.iloc[col_idx])
            if val is not None:
                return val
        except IndexError:
            pass
    for v in row.iloc[label_col + 1:]:
        val = to_num(v)
        if val is not None:
            return val
    return None


def cagr(start, end, years):
    """Calculate CAGR given start, end values and number of years."""
    if start and end and years and start > 0:
        return ((end / start) ** (1 / years) - 1) * 100
    return None


def load_sheets(file) -> dict:
    """Load all sheets from xlsx; return dict of sheet_name → DataFrame."""
    sheets = {}
    try:
        xl = pd.ExcelFile(file, engine="openpyxl")
        for name in xl.sheet_names:
            try:
                sheets[name] = pd.read_excel(xl, sheet_name=name, header=None, dtype=str)
            except Exception:
                pass
    except Exception as e:
        st.error(f"Could not open Excel file: {e}")
    return sheets


def find_sheet(sheets: dict, *keywords) -> pd.DataFrame | None:
    """Return the first sheet whose name matches any of the keywords."""
    for key in keywords:
        for name, df in sheets.items():
            if key.lower() in name.lower():
                return df
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Core parser — extract all metrics
# ─────────────────────────────────────────────────────────────────────────────

def parse_file(file) -> dict:
    data: dict = {}

    is_csv = file.name.endswith(".csv")

    if is_csv:
        try:
            df_main = pd.read_csv(file, header=None, dtype=str)
        except Exception as e:
            st.error(f"Could not read CSV: {e}")
            return data
        sheets = {"Data Sheet": df_main}
    else:
        sheets = load_sheets(file)

    # ── identify key sheets ──────────────────────────────────────────────────
    df_data    = find_sheet(sheets, "data sheet", "data")
    df_summary = find_sheet(sheets, "summary")
    df_cf      = find_sheet(sheets, "cash flow", "cashflow")
    df_dcf     = find_sheet(sheets, "dcf")
    df_graham  = find_sheet(sheets, "ben graham", "graham")
    df_dhandho = find_sheet(sheets, "dhandho")
    df_pl      = find_sheet(sheets, "profit", "p&l", "pl")
    df_bs      = find_sheet(sheets, "balance sheet", "balance")

    # Fall back to first sheet if data sheet not found
    primary = None
if df_data is not None and not df_data.empty:
    primary = df_data
elif df_pl is not None and not df_pl.empty:
    primary = df_pl
elif sheets:
    primary = list(sheets.values())[0]

    if primary is None:
        st.error("No readable sheet found in the uploaded file.")
        return data

    # ── Company basics ───────────────────────────────────────────────────────
    try:
        data["company_name"] = str(primary.iloc[0, 1]).strip()
    except Exception:
        data["company_name"] = "Unknown Company"

    for df in [primary, df_summary]:
        if df is None:
            continue
        if not data.get("cmp"):
            data["cmp"] = (
                scalar_cell(df, "Current Price")
                or scalar_cell(df, "Current Price (INR)")
                or scalar_cell(df, "CMP")
                or scalar_cell(df, "Market Price")
            )
        if not data.get("market_cap"):
            data["market_cap"] = (
                scalar_cell(df, "Market Capitalization")
                or scalar_cell(df, "Market Cap")
                or scalar_cell(df, "Market Cap (Cr)")
            )

    # ── Profit & Loss ────────────────────────────────────────────────────────
    df_for_pl = df_pl or primary
    sales_series = row_series(df_for_pl, "Net Sales") or row_series(df_for_pl, "Revenue") or row_series(df_for_pl, "Sales")
    pat_series   = row_series(df_for_pl, "Net Profit") or row_series(df_for_pl, "PAT") or row_series(df_for_pl, "Profit after tax")

    data["net_profit_latest"] = pat_series[-1] if pat_series else None

    if len(sales_series) >= 10:
        data["sales_growth_10y"] = cagr(sales_series[-11], sales_series[-1], 10)
    elif len(sales_series) >= 3:
        data["sales_growth_10y"] = cagr(sales_series[0], sales_series[-1], len(sales_series) - 1)
    else:
        data["sales_growth_10y"] = None

    if len(pat_series) >= 10:
        data["pat_growth_10y"] = cagr(pat_series[-11], pat_series[-1], 10)
    elif len(pat_series) >= 3:
        data["pat_growth_10y"] = cagr(pat_series[0], pat_series[-1], len(pat_series) - 1)
    else:
        data["pat_growth_10y"] = None

    # recent vs historical growth for narrative
    if len(pat_series) >= 4:
        data["pat_growth_3y"] = cagr(pat_series[-4], pat_series[-1], 3)
    else:
        data["pat_growth_3y"] = None

    # ── Balance sheet ────────────────────────────────────────────────────────
    df_for_bs = df_bs or primary
    reserves_series   = row_series(df_for_bs, "Reserves")
    equity_sc_series  = row_series(df_for_bs, "Equity Share Capital")
    borrowings_series = row_series(df_for_bs, "Borrowings") or row_series(df_for_bs, "Total Debt")
    capex_series      = row_series(df_for_bs, "Capital Expenditure") or row_series(df_for_bs, "Capex")

    data["reserves"]          = reserves_series[-1]   if reserves_series   else None
    data["equity_sc"]         = equity_sc_series[-1]  if equity_sc_series  else None
    data["borrowings"]        = borrowings_series[-1]  if borrowings_series  else None
    data["capex_latest"]      = capex_series[-1]       if capex_series       else None

    shareholder_equity = None
    if data.get("reserves") is not None and data.get("equity_sc") is not None:
        shareholder_equity = data["reserves"] + data["equity_sc"]
    data["shareholder_equity"] = shareholder_equity

    # ── Cash Flow ────────────────────────────────────────────────────────────
    df_for_cf = df_cf or primary
    cfo_series = (
        row_series(df_for_cf, "Cash from Operating")
        or row_series(df_for_cf, "Cash from Operations")
        or row_series(df_for_cf, "Cash from Operating Activity")
        or row_series(df_for_cf, "Net Cash from Operating")
        or row_series(df_for_cf, "Operating Cash")
        or row_series(df_for_cf, "CFO")
    )
    fcf_series = row_series(df_for_cf, "Free Cash Flow") or row_series(df_for_cf, "FCF")

    data["cfo"] = cfo_series[-1] if cfo_series else None
    data["fcf"] = fcf_series[-1] if fcf_series else None

    # derive FCF from CFO - Capex if not found
    if data["fcf"] is None and data.get("cfo") is not None and data.get("capex_latest") is not None:
        data["fcf"] = data["cfo"] - abs(data["capex_latest"])

    # ── Ratios ───────────────────────────────────────────────────────────────
    net_profit = data.get("net_profit_latest")
    cfo        = data.get("cfo")
    borrowings = data.get("borrowings")
    eq         = shareholder_equity
    mkt_cap    = data.get("market_cap")

    for df in [df_summary, primary]:
        if df is None:
            continue
        if data.get("roe") is None:
            data["roe"] = (
                scalar_cell(df, "ROE")
                or scalar_cell(df, "Return on Equity")
                or scalar_cell(df, "Return on Equity %")
                or scalar_cell(df, "Latest FY ROAE")
                or scalar_cell(df, "ROAE")
            )

    if data.get("roe") is None:
        data["roe"] = (net_profit / eq * 100) if net_profit and eq else None
    data["cfo_pat"] = (cfo / net_profit) if cfo and net_profit and net_profit != 0 else None
    data["de"]      = (borrowings / eq) if borrowings is not None and eq else None
    data["pe"]      = (mkt_cap / net_profit) if mkt_cap and net_profit and net_profit != 0 else None

    # ── P/E ratio (from primary / summary) ──────────────────────────────────
    for df in [df_summary, primary]:
        if df is None:
            continue
        if data.get("pe") is None:
            data["pe"] = (
                scalar_cell(df, "PE Ratio")
                or scalar_cell(df, "P/E")
                or scalar_cell(df, "P/E Ratio")
                or scalar_cell(df, "TTM P/E")
                or scalar_cell(df, "Price to Earnings")
            )
        v5 = (
            scalar_cell(df, "5 Year Avg PE")
            or scalar_cell(df, "5-Year P/E")
            or scalar_cell(df, "5Yr PE")
            or scalar_cell(df, "Average PE")
            or scalar_cell(df, "Median PE")
        )
        if v5 and not data.get("pe_5yr_avg"):
            data["pe_5yr_avg"] = v5
        if data.get("pe") and data.get("pe_5yr_avg"):
            break

    # ── Intrinsic valuation ──────────────────────────────────────────────────
    for df, key in [(df_dcf, "dcf_value"), (df_graham, "graham_value"), (df_dhandho, "dhandho_value")]:
        if df is None:
            data[key] = None
            continue
        val = (
            scalar_cell(df, "Intrinsic Value")
            or scalar_cell(df, "Fair Value")
            or scalar_cell(df, "DCF Value")
            or scalar_cell(df, "Graham Value")
            or scalar_cell(df, "Dhandho Value")
            or scalar_cell(df, "IV")
        )
        data[key] = val

    data["pat_series"]   = pat_series
    data["sales_series"] = sales_series

    return data


# ─────────────────────────────────────────────────────────────────────────────
# 6-Step Framework
# ─────────────────────────────────────────────────────────────────────────────

def run_scorecard(data: dict, governance_ok: bool, beta_value: float) -> dict:
    roe     = data.get("roe")
    cfo_pat = data.get("cfo_pat")
    fcf     = data.get("fcf")
    pe      = data.get("pe")
    pe_5avg = data.get("pe_5yr_avg")

    def passed(condition) -> int | None:
        if condition is None:
            return None
        return 1 if condition else 0

    s1 = passed(roe >= 15.0)                           if roe is not None else None
    s2_ratio = (cfo_pat >= 0.80)                        if cfo_pat is not None else None
    s2_fcf   = (fcf > 0)                               if fcf is not None else None
    if s2_ratio is not None and s2_fcf is not None:
        s2 = passed(s2_ratio and s2_fcf)
    elif s2_ratio is not None:
        s2 = passed(s2_ratio)
    else:
        s2 = None

    if pe is not None and pe_5avg is not None:
        s3 = passed(pe <= pe_5avg * 1.10)
    else:
        s3 = None

    s4 = 1 if governance_ok else 0
    s5_pass = abs(beta_value - TARGET_BETA) <= BETA_TOLERANCE
    s5 = 1 if s5_pass else 0

    steps = [s1, s2, s3, s4, s5]
    known = [s for s in steps if s is not None]
    total = sum(known)

    return {
        "s1": s1, "s2": s2, "s3": s3, "s4": s4, "s5": s5,
        "total": total, "max": len(known) + 1,  # +1 for step 6 (overall)
        "steps_raw": steps,
        "s2_ratio": s2_ratio, "s2_fcf": s2_fcf,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Plain-English Narrative Engine
# ─────────────────────────────────────────────────────────────────────────────

def build_narrative(data: dict, scorecard: dict) -> dict:
    roe       = data.get("roe")
    cfo_pat   = data.get("cfo_pat")
    de        = data.get("de")
    pe        = data.get("pe")
    pe_5avg   = data.get("pe_5yr_avg")
    sg10      = data.get("sales_growth_10y")
    pg10      = data.get("pat_growth_10y")
    pg3       = data.get("pat_growth_3y")
    cmp       = data.get("cmp")
    dcf       = data.get("dcf_value")
    graham    = data.get("graham_value")
    dhandho   = data.get("dhandho_value")
    company   = data.get("company_name", "This company")
    capex     = data.get("capex_latest")
    cfo_val   = data.get("cfo")

    def fmt(v, d=1, sfx=""):
        return f"{v:,.{d}f}{sfx}" if v is not None else "N/A"

    strengths = []
    weaknesses = []
    red_flags = []

    # ── Strengths ────────────────────────────────────────────────────────────
    if roe and roe >= 20:
        strengths.append(
            f"**Exceptional Return on Equity ({fmt(roe, 1)}%):** {company} earns ₹{fmt(roe/100, 2)} for every ₹1 of shareholders' money — a hallmark of a business with genuine pricing power or a strong competitive moat."
        )
    elif roe and roe >= 15:
        strengths.append(
            f"**Solid Return on Equity ({fmt(roe, 1)}%):** Meets the 15% quality threshold, indicating the business creates real value for shareholders rather than just recycling capital."
        )

    if cfo_pat and cfo_pat >= 1.0:
        strengths.append(
            f"**Excellent Cash Conversion ({fmt(cfo_pat, 2)}× CFO/PAT):** For every rupee of profit reported, the business actually collects more than a rupee in cash. This is rare and powerfully confirms earnings quality."
        )
    elif cfo_pat and cfo_pat >= 0.80:
        strengths.append(
            f"**Healthy Cash Flow Conversion ({fmt(cfo_pat, 2)}× CFO/PAT):** Profits are broadly backed by real operating cash — a sign of accounting discipline and genuine business health."
        )

    if de is not None and de <= 0.25:
        strengths.append(
            f"**Near Debt-Free Balance Sheet (D/E: {fmt(de, 2)}×):** {company} runs with minimal borrowed capital. In a downturn or rising interest rate environment, this is a fortress-like advantage."
        )
    elif de is not None and de <= 0.50:
        strengths.append(
            f"**Conservative Leverage (D/E: {fmt(de, 2)}×):** The company uses modest debt, keeping interest obligations low and preserving financial flexibility."
        )

    if sg10 and sg10 >= 15:
        strengths.append(
            f"**Strong Long-Run Sales Growth ({fmt(sg10, 1)}% CAGR over ~10 years):** Revenue has compounded impressively, suggesting the business has consistently expanded its market without losing pricing discipline."
        )

    if not strengths:
        strengths.append("Insufficient data to identify quantitative strengths. Review the uploaded file to ensure all required sheets are populated.")

    # ── Weaknesses ───────────────────────────────────────────────────────────
    if pg10 and pg3 and pg3 < pg10 * 0.5:
        weaknesses.append(
            f"**Sharply Decelerating Profit Growth:** 10-year PAT CAGR is {fmt(pg10, 1)}%, but the recent 3-year CAGR has slowed to just {fmt(pg3, 1)}%. This gap signals that the business's best growth years may be behind it, or it is navigating structural headwinds."
        )
    elif pg10 and pg3 and pg3 < pg10:
        weaknesses.append(
            f"**Slowing Profit Momentum:** Long-run PAT growth ({fmt(pg10, 1)}% CAGR) outpaces recent 3-year growth ({fmt(pg3, 1)}% CAGR). Monitor whether this is a temporary blip or the beginning of a structural slowdown."
        )

    if roe and roe < 15:
        weaknesses.append(
            f"**Below-Threshold ROE ({fmt(roe, 1)}%):** Returns fall short of the 15% quality bar. The business is not yet generating enough profit relative to shareholder equity to qualify as a high-quality compounder."
        )

    if cfo_val is not None and capex is not None and cfo_val > 0:
        capex_intensity = abs(capex) / cfo_val
        if capex_intensity > 0.70:
            weaknesses.append(
                f"**High Capital Intensity (Capex is {fmt(capex_intensity*100, 0)}% of CFO):** The business is consuming a large share of its operating cash just to maintain or expand assets. This leaves little free cash for dividends, buybacks, or debt repayment."
            )

    if de is not None and de > 0.5:
        weaknesses.append(
            f"**Elevated Leverage (D/E: {fmt(de, 2)}×):** The company carries more debt than the 0.50× safety threshold. Higher borrowings increase interest costs and amplify risk during economic downturns."
        )

    if not weaknesses:
        weaknesses.append("No major quantitative weaknesses identified. The business appears financially well-managed based on available data.")

    # ── Red Flags ─────────────────────────────────────────────────────────────
    valuation_warnings = []
    intrinsic_vals = {k: v for k, v in [("DCF", dcf), ("Ben Graham Formula", graham), ("Dhandho IV", dhandho)] if v is not None}
    if cmp and intrinsic_vals:
        for model, iv in intrinsic_vals.items():
            if cmp > iv * 1.20:
                premium = ((cmp / iv) - 1) * 100
                valuation_warnings.append(f"{model} ({fmt(iv, 0, ' ₹')}): trading at a {fmt(premium, 0)}% **premium**")
            elif cmp < iv * 0.80:
                discount = ((iv / cmp) - 1) * 100
                valuation_warnings.append(f"{model} ({fmt(iv, 0, ' ₹')}): trading at a {fmt(discount, 0)}% **discount** — potential margin of safety")
        if valuation_warnings:
            red_flags.append(
                f"**Valuation vs Intrinsic Models:** CMP is ₹{fmt(cmp, 0)}. Compared to intrinsic estimates — " + "; ".join(valuation_warnings) + ". Always demand a margin of safety before buying."
            )

    if pe and pe_5avg and pe > pe_5avg * 1.25:
        red_flags.append(
            f"**P/E Stretched Relative to History:** Current P/E ({fmt(pe, 1)}×) is more than 25% above the 5-year average ({fmt(pe_5avg, 1)}×). The market is pricing in significant future growth. If that growth disappoints, the stock could re-rate sharply downward."
        )

    if cfo_pat and cfo_pat < 0.5:
        red_flags.append(
            f"**Low Cash Conversion Warning (CFO/PAT: {fmt(cfo_pat, 2)}×):** Reported profits are significantly higher than actual cash collected. This is a classic red flag for potential earnings quality issues — scrutinize receivables and accounting policies."
        )

    if cmp:
        red_flags.append(
            "**Governance & Pledging:** Always verify 0% promoter share pledging on screener.in or the BSE/NSE shareholding pattern. Also check the latest audit report for any qualifications, emphasis of matter paragraphs, or related-party transactions. These cannot be quantified from the Excel — they require a manual read of the annual report."
        )

    if not red_flags:
        red_flags.append("No major red flags identified from the quantitative data. Proceed with qualitative checks (management quality, competitive moat, industry dynamics).")

    # ── Verdict ───────────────────────────────────────────────────────────────
    score = scorecard["total"]
    known_steps = [s for s in scorecard["steps_raw"] if s is not None]
    max_steps = len(known_steps)

    if score == max_steps and max_steps >= 4:
        verdict = (
            f"{data.get('company_name', 'This stock')} clears all {score} quantitative checks — business quality is strong, cash flows are real, the balance sheet is conservative, and valuation appears reasonable. "
            "Subject to your manual governance verification, this stock merits deeper qualitative analysis and consideration for portfolio inclusion."
        )
    elif score >= max_steps - 1:
        verdict = (
            f"{data.get('company_name', 'This stock')} passes {score}/{max_steps} checks — a near-miss that warrants careful review of the one failing criterion before committing capital. "
            "A single weak link (especially in valuation or governance) can meaningfully increase downside risk."
        )
    else:
        verdict = (
            f"{data.get('company_name', 'This stock')} fails {max_steps - score} out of {max_steps} checks — the business does not currently meet the full Master Framework bar. "
            "Buying here would require accepting risks the framework is specifically designed to avoid. Consider monitoring rather than buying today."
        )

    return {
        "strengths": strengths,
        "weaknesses": weaknesses,
        "red_flags": red_flags,
        "verdict": verdict,
    }


# ─────────────────────────────────────────────────────────────────────────────
# PDF archiving
# ─────────────────────────────────────────────────────────────────────────────

def archive_pdf(uploaded_pdf, ticker: str) -> str:
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_ticker = "".join(c for c in ticker.upper() if c.isalnum() or c in "_-")
    filename = f"{safe_ticker}_{ts}.pdf"
    dest = os.path.join(PDF_DIR, filename)
    with open(dest, "wb") as f:
        f.write(uploaded_pdf.getbuffer())
    return dest


# ─────────────────────────────────────────────────────────────────────────────
# UI helpers
# ─────────────────────────────────────────────────────────────────────────────

def step_box(label: str, passed, detail: str = "", fail_detail: str = ""):
    if passed is None:
        st.warning(f"⚠️ **{label}** — *Data unavailable*{' — ' + detail if detail else ''}")
    elif passed:
        st.success(f"✅ **{label}** — **PASS**{' — ' + detail if detail else ''}")
    else:
        msg = fail_detail or detail
        st.error(f"❌ **{label}** — **FAIL**{' — ' + msg if msg else ''}")


def fmt(v, d=2, sfx=""):
    if v is None:
        return "N/A"
    return f"{v:,.{d}f}{sfx}"


# ─────────────────────────────────────────────────────────────────────────────
# Sidebar
# ─────────────────────────────────────────────────────────────────────────────

with st.sidebar:
    st.title("🏦 Master Evaluator")
    st.caption("Indian Stocks — 6-Step Framework")
    st.markdown("---")
    st.subheader("📋 6-Step Framework")
    st.markdown("""
**Step 1 – Business Quality**
ROE ≥ 15% → Strong moat / capital efficiency

**Step 2 – Cash Realism**
CFO/PAT ≥ 0.80× **and** Positive FCF → Real earnings

**Step 3 – Valuation Safety Margin**
Current P/E ≤ 5-Yr Avg P/E (±10%) → Not overpriced

**Step 4 – Governance Shield**
0% Promoter Pledging + Clean Audit → Trust

**Step 5 – Beta Check**
Beta ≈ 1.10 (±0.30) → Portfolio fit

**Step 6 – Overall Verdict**
All 5 checks → APPROVED / LOCKED IN
""")
    st.markdown("---")
    st.caption("Data sourced from Screener.in / Safal Niveshak exports. Always verify governance manually.")


# ─────────────────────────────────────────────────────────────────────────────
# Main tabs
# ─────────────────────────────────────────────────────────────────────────────

tab_eval, tab_vault = st.tabs(["📊 Evaluate Stock", "🗃️ Portfolio Vault"])


# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 – Evaluate
# ══════════════════════════════════════════════════════════════════════════════

with tab_eval:
    st.title("📊 Master Quantitative & Business Risk Evaluator")
    st.caption("Upload a Screener.in / Safal Niveshak export (Excel preferred) to run a full quantitative evaluation.")

    # ── Upload ────────────────────────────────────────────────────────────────
    col_up1, col_up2 = st.columns(2)
    with col_up1:
        uploaded_excel = st.file_uploader(
            "📁 Excel / CSV Export",
            type=["xlsx", "csv"],
            help="Screener.in multi-sheet export or Safal Niveshak Data Sheet (.xlsx or .csv)",
        )
    with col_up2:
        uploaded_pdf = st.file_uploader(
            "📄 Company PDF (optional)",
            type=["pdf"],
            help="Annual report, investor presentation, or brokerage note — will be archived locally.",
        )

    # ── Manual inputs ─────────────────────────────────────────────────────────
    col_m1, col_m2, col_m3 = st.columns(3)
    with col_m1:
        ticker = st.text_input("Stock Ticker (for PDF archiving)", value="TICKER", max_chars=20)
    with col_m2:
        governance_ok = st.checkbox(
            "✅ Governance Shield — 0% Promoter Pledging & Clean Audit verified",
            value=False,
        )
    with col_m3:
        beta_value = st.number_input(
            "Stock Beta", min_value=0.0, max_value=5.0, value=1.10, step=0.01, format="%.2f"
        )

    if uploaded_excel is None:
        st.info(
            "👆 Upload a Screener.in or Safal Niveshak Excel export above to begin.\n\n"
            "**Tip:** The multi-sheet `.xlsx` export gives the richest results (DCF, Graham, Dhandho valuations, Cash Flow sheet, etc.)."
        )

    if uploaded_excel is not None:
        with st.spinner("Parsing file…"):
            data = parse_file(uploaded_excel)

        if not data:
            st.stop()

        # Archive PDF
        pdf_path = ""
        if uploaded_pdf is not None:
            pdf_path = archive_pdf(uploaded_pdf, ticker)
            st.toast(f"PDF archived → `{pdf_path}`", icon="📄")

        # Metrics & scorecard
        scorecard = run_scorecard(data, governance_ok, beta_value)
        narrative = build_narrative(data, scorecard)

        # ── Header ────────────────────────────────────────────────────────────
        st.markdown(f"## 🏢 {data.get('company_name', 'Unknown Company')}")
        if ticker.upper() != "TICKER":
            st.caption(f"Ticker: **{ticker.upper()}**")
        st.divider()

        # ── Metric Cards ──────────────────────────────────────────────────────
        st.subheader("📌 Key Metrics")
        m_cols = st.columns(8)
        cards = [
            ("CMP (₹)",        fmt(data.get("cmp"), 2)),
            ("Market Cap (Cr)", fmt(data.get("market_cap"), 0)),
            ("ROE %",           fmt(data.get("roe"), 1, "%")),
            ("CFO/PAT",         fmt(data.get("cfo_pat"), 2, "×")),
            ("D/E",             fmt(data.get("de"), 2, "×")),
            ("P/E (Current)",   fmt(data.get("pe"), 1, "×")),
            ("P/E (5-Yr Avg)",  fmt(data.get("pe_5yr_avg"), 1, "×")),
            ("Net Profit (Cr)", fmt(data.get("net_profit_latest"), 0)),
        ]
        for col, (label, value) in zip(m_cols, cards):
            col.metric(label, value)

        # Growth row
        g_cols = st.columns(4)
        g_cols[0].metric("Sales CAGR (10Y)", fmt(data.get("sales_growth_10y"), 1, "%"))
        g_cols[1].metric("PAT CAGR (10Y)",   fmt(data.get("pat_growth_10y"), 1, "%"))
        g_cols[2].metric("PAT CAGR (3Y)",    fmt(data.get("pat_growth_3y"), 1, "%"))
        g_cols[3].metric("Free Cash Flow",   fmt(data.get("fcf"), 0, " Cr"))

        st.divider()

        # ── Valuation triangle ────────────────────────────────────────────────
        dcf_v    = data.get("dcf_value")
        graham_v = data.get("graham_value")
        dhandho_v = data.get("dhandho_value")
        cmp      = data.get("cmp")

        if any(v is not None for v in [dcf_v, graham_v, dhandho_v]):
            st.subheader("🎯 Intrinsic Valuation Triangle")
            v_cols = st.columns(4)
            v_cols[0].metric("CMP (₹)",             fmt(cmp, 0))
            v_cols[1].metric("DCF Value (₹)",        fmt(dcf_v, 0) if dcf_v else "N/A")
            v_cols[2].metric("Ben Graham Value (₹)", fmt(graham_v, 0) if graham_v else "N/A")
            v_cols[3].metric("Dhandho IV (₹)",       fmt(dhandho_v, 0) if dhandho_v else "N/A")

            # gauge chart
            known_ivs = {k: v for k, v in [("DCF", dcf_v), ("Graham", graham_v), ("Dhandho", dhandho_v)] if v is not None}
            if cmp and known_ivs:
                fig = go.Figure()
                labels = list(known_ivs.keys()) + ["CMP"]
                values = list(known_ivs.values()) + [cmp]
                colors = ["#2196F3" if v >= cmp else "#FF5722" for v in list(known_ivs.values())] + ["#FFC107"]
                fig.add_trace(go.Bar(
                    x=labels, y=values,
                    marker_color=colors,
                    text=[f"₹{v:,.0f}" for v in values],
                    textposition="outside",
                ))
                fig.update_layout(
                    title="CMP vs Intrinsic Value Estimates (₹)",
                    yaxis_title="Value (₹)",
                    height=300,
                    margin=dict(t=50, b=20, l=20, r=20),
                    plot_bgcolor="rgba(0,0,0,0)",
                    paper_bgcolor="rgba(0,0,0,0)",
                )
                st.plotly_chart(fig, use_container_width=True)
            st.divider()

        # ── 6-Step Scorecard ──────────────────────────────────────────────────
        st.subheader("🎯 6-Step Master Framework Scorecard")

        roe     = data.get("roe")
        cfo_pat = data.get("cfo_pat")
        fcf     = data.get("fcf")
        pe      = data.get("pe")
        pe_5avg = data.get("pe_5yr_avg")
        de      = data.get("de")

        step_box(
            "Step 1: Business Quality — ROE ≥ 15%",
            scorecard["s1"],
            detail=f"ROE = {fmt(roe, 1, '%')} {'≥' if roe and roe >= 15 else '<'} 15.00%",
        )

        cfo_detail = f"CFO/PAT = {fmt(cfo_pat, 2, '×')} {'≥' if cfo_pat and cfo_pat >= 0.8 else '<'} 0.80× | FCF = {fmt(fcf, 0, ' Cr')} ({'Positive ✓' if fcf and fcf > 0 else 'Negative ✗'})"
        step_box("Step 2: Cash Realism — CFO/PAT ≥ 0.80× & Positive FCF", scorecard["s2"], detail=cfo_detail)

        if pe is not None and pe_5avg is not None:
            threshold = pe_5avg * 1.10
            pe_detail = f"Current P/E = {fmt(pe, 1, '×')} {'≤' if pe <= threshold else '>'} 5-Yr Avg P/E × 1.10 = {fmt(threshold, 1, '×')}"
        else:
            pe_detail = "P/E or 5-Yr Avg P/E not available in file"
        step_box("Step 3: Valuation Safety Margin — P/E ≤ 5-Yr Avg P/E (×1.10)", scorecard["s3"], detail=pe_detail)

        step_box(
            "Step 4: Governance Shield — 0% Promoter Pledging & Clean Audit",
            scorecard["s4"],
            detail="Manually verified ✓" if governance_ok else "Not yet verified — check screener.in shareholding pattern",
        )

        beta_detail = f"Beta = {beta_value:.2f} | Target = {TARGET_BETA:.2f} ± {BETA_TOLERANCE:.2f}"
        step_box("Step 5: Beta Check — Portfolio Fit (~1.10 ± 0.30)", scorecard["s5"], detail=beta_detail)

        st.divider()

        # ── Final verdict badge ───────────────────────────────────────────────
        total   = scorecard["total"]
        max_val = 5  # steps 1-5; step 6 is the verdict itself
        all_pass = total == max_val and all(s is not None for s in [scorecard["s1"], scorecard["s2"], scorecard["s3"]])

        if all_pass:
            st.markdown(
                f"""<div style="background:#1a7a4a;padding:28px 36px;border-radius:14px;text-align:center;">
                    <h1 style="color:white;margin:0;font-size:2.4rem;">✅ APPROVED / LOCKED IN ({total}/5 + Scorecard = 6/6)</h1>
                    <p style="color:#d4f7e8;margin:8px 0 0 0;font-size:1.05rem;">All 5 quantitative checks pass. Subject to final manual governance verification.</p>
                </div>""",
                unsafe_allow_html=True,
            )
        else:
            data_gaps = sum(1 for s in [scorecard["s1"], scorecard["s2"], scorecard["s3"]] if s is None)
            st.markdown(
                f"""<div style="background:#7a1a1a;padding:28px 36px;border-radius:14px;text-align:center;">
                    <h1 style="color:white;margin:0;font-size:2.4rem;">❌ REJECTED ({total}/{max_val} checks passed)</h1>
                    <p style="color:#f7d4d4;margin:8px 0 0 0;font-size:1.05rem;">
                        Does not meet all Master Framework criteria.{' Some checks could not be scored due to missing data.' if data_gaps else ''}
                    </p>
                </div>""",
                unsafe_allow_html=True,
            )

        st.divider()

        # ── Plain-English Narrative ───────────────────────────────────────────
        st.subheader("📝 Plain-English Business Risk Analysis")

        with st.expander("💪 A. Core Strengths — What makes this business strong?", expanded=True):
            for s in narrative["strengths"]:
                st.markdown(f"- {s}")

        with st.expander("⚠️ B. Weaknesses & Vulnerabilities — Where is it hurting?", expanded=True):
            for w in narrative["weaknesses"]:
                st.markdown(f"- {w}")

        with st.expander("🚩 C. Red Flags & Investor Awareness", expanded=True):
            for r in narrative["red_flags"]:
                st.markdown(f"- {r}")

        with st.expander("🏆 D. Plain-English Verdict", expanded=True):
            st.info(narrative["verdict"])

        st.divider()

        # ── Growth trend chart ────────────────────────────────────────────────
        pat_series   = data.get("pat_series", [])
        sales_series = data.get("sales_series", [])
        if pat_series or sales_series:
            with st.expander("📈 Historical Growth Trends"):
                fig2 = go.Figure()
                if pat_series:
                    fig2.add_trace(go.Scatter(y=pat_series, name="Net Profit (Cr)", mode="lines+markers", line=dict(color="#4CAF50")))
                if sales_series:
                    fig2.add_trace(go.Scatter(y=sales_series, name="Net Sales (Cr)", mode="lines+markers", line=dict(color="#2196F3")))
                fig2.update_layout(
                    title="Net Sales & Profit Trend (earliest → latest year)",
                    yaxis_title="₹ Crore",
                    height=320,
                    margin=dict(t=50, b=20, l=20, r=20),
                    plot_bgcolor="rgba(0,0,0,0)",
                    paper_bgcolor="rgba(0,0,0,0)",
                )
                st.plotly_chart(fig2, use_container_width=True)

        # ── Raw data expander ─────────────────────────────────────────────────
        with st.expander("🔍 Raw Parsed Data"):
            raw = {
                "Company Name": data.get("company_name"),
                "CMP (₹)": data.get("cmp"),
                "Market Cap (Cr)": data.get("market_cap"),
                "Net Profit / PAT (Cr)": data.get("net_profit_latest"),
                "CFO (Cr)": data.get("cfo"),
                "FCF (Cr)": data.get("fcf"),
                "Borrowings (Cr)": data.get("borrowings"),
                "Reserves (Cr)": data.get("reserves"),
                "Equity Share Capital (Cr)": data.get("equity_sc"),
                "Shareholder Equity (Cr)": data.get("shareholder_equity"),
                "ROE (%)": data.get("roe"),
                "CFO/PAT": data.get("cfo_pat"),
                "D/E Ratio": data.get("de"),
                "P/E (Current)": data.get("pe"),
                "P/E (5-Yr Avg)": data.get("pe_5yr_avg"),
                "Sales CAGR 10Y (%)": data.get("sales_growth_10y"),
                "PAT CAGR 10Y (%)": data.get("pat_growth_10y"),
                "PAT CAGR 3Y (%)": data.get("pat_growth_3y"),
                "DCF Value (₹)": data.get("dcf_value"),
                "Ben Graham Value (₹)": data.get("graham_value"),
                "Dhandho IV (₹)": data.get("dhandho_value"),
                "PDF Archived": pdf_path or "None",
            }
            st.table(pd.DataFrame(list(raw.items()), columns=["Metric", "Value"]))

        # ── Save to DB ────────────────────────────────────────────────────────
        st.divider()
        if st.button("💾 Save Evaluation to Portfolio Vault", type="primary"):
            narrative_json = json.dumps(narrative)
            save_evaluation({
                "saved_at":        datetime.datetime.now().isoformat(),
                "company_name":    data.get("company_name"),
                "ticker":          ticker.upper(),
                "cmp":             data.get("cmp"),
                "market_cap":      data.get("market_cap"),
                "roe":             data.get("roe"),
                "cfo_pat":         data.get("cfo_pat"),
                "de_ratio":        data.get("de"),
                "pe_current":      data.get("pe"),
                "pe_5yr_avg":      data.get("pe_5yr_avg"),
                "sales_growth_10y": data.get("sales_growth_10y"),
                "pat_growth_10y":   data.get("pat_growth_10y"),
                "dcf_value":       data.get("dcf_value"),
                "graham_value":    data.get("graham_value"),
                "dhandho_value":   data.get("dhandho_value"),
                "step1":           scorecard["s1"],
                "step2":           scorecard["s2"],
                "step3":           scorecard["s3"],
                "step4":           scorecard["s4"],
                "step5":           scorecard["s5"],
                "total_score":     scorecard["total"],
                "verdict":         "APPROVED" if all_pass else "REJECTED",
                "narrative":       narrative_json,
                "pdf_path":        pdf_path,
            })
            st.success(f"✅ Saved **{data.get('company_name')}** to Portfolio Vault. Switch to the **Portfolio Vault** tab to view.")
            st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 – Portfolio Vault
# ══════════════════════════════════════════════════════════════════════════════

with tab_vault:
    st.title("🗃️ Master Portfolio Vault & Comparison")

    rows = load_all_evaluations()

    if not rows:
        st.info("No evaluations saved yet. Evaluate a stock and click **Save to Portfolio Vault**.")
    else:
        # ── Search & filter ────────────────────────────────────────────────────
        search = st.text_input("🔍 Search by company name or ticker", "")
        if search:
            rows = [r for r in rows if search.lower() in (r.get("company_name") or "").lower()
                    or search.lower() in (r.get("ticker") or "").lower()]

        verdict_filter = st.selectbox("Filter by verdict", ["All", "APPROVED", "REJECTED"])
        if verdict_filter != "All":
            rows = [r for r in rows if r.get("verdict") == verdict_filter]

        st.caption(f"Showing {len(rows)} evaluation(s)")

        # ── Summary table ──────────────────────────────────────────────────────
        if rows:
            tbl_data = []
            for r in rows:
                tbl_data.append({
                    "Company":      r.get("company_name", ""),
                    "Ticker":       r.get("ticker", ""),
                    "Saved":        (r.get("saved_at") or "")[:16].replace("T", " "),
                    "CMP (₹)":     fmt(r.get("cmp"), 0),
                    "ROE %":       fmt(r.get("roe"), 1),
                    "CFO/PAT":     fmt(r.get("cfo_pat"), 2),
                    "D/E":         fmt(r.get("de_ratio"), 2),
                    "P/E":         fmt(r.get("pe_current"), 1),
                    "Score":       f"{r.get('total_score') or 0}/5",
                    "Verdict":     r.get("verdict", ""),
                    "PDF":         "✅" if r.get("pdf_path") else "—",
                })
            st.dataframe(pd.DataFrame(tbl_data), use_container_width=True, hide_index=True)

        st.divider()

        # ── Side-by-side comparison ────────────────────────────────────────────
        st.subheader("📊 Side-by-Side Comparison")
        names = [f"{r.get('company_name', 'Unknown')} ({r.get('ticker', '')}) [{r.get('saved_at', '')[:10]}]" for r in rows]
        selected = st.multiselect("Select 2–4 stocks to compare", options=names, max_selections=4)

        if selected:
            sel_rows = [rows[names.index(s)] for s in selected if s in names]
            metrics_compare = ["roe", "cfo_pat", "de_ratio", "pe_current", "pe_5yr_avg", "sales_growth_10y", "pat_growth_10y", "total_score"]
            labels_compare  = ["ROE %", "CFO/PAT×", "D/E×", "P/E Current", "P/E 5Yr Avg", "Sales CAGR 10Y %", "PAT CAGR 10Y %", "Score /5"]

            comp_fig = go.Figure()
            for row in sel_rows:
                comp_fig.add_trace(go.Scatterpolar(
                    r=[row.get(m) or 0 for m in metrics_compare],
                    theta=labels_compare,
                    fill="toself",
                    name=f"{row.get('company_name', '')} ({row.get('ticker', '')})",
                ))
            comp_fig.update_layout(
                polar=dict(radialaxis=dict(visible=True)),
                title="Multi-Metric Radar Comparison",
                height=450,
            )
            st.plotly_chart(comp_fig, use_container_width=True)

            # Tabular comparison
            comp_tbl = {"Metric": labels_compare}
            for row in sel_rows:
                name = f"{row.get('company_name', '')} ({row.get('ticker', '')})"
                comp_tbl[name] = [fmt(row.get(m), 2) for m in metrics_compare]
            st.dataframe(pd.DataFrame(comp_tbl), use_container_width=True, hide_index=True)

        st.divider()

        # ── Individual record viewer ───────────────────────────────────────────
        st.subheader("📁 Evaluation Details & PDF Download")
        for r in rows:
            label = f"{r.get('company_name', 'Unknown')} | {r.get('ticker', '')} | {(r.get('saved_at') or '')[:10]} | {r.get('verdict', '')}"
            with st.expander(label):
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("CMP (₹)", fmt(r.get("cmp"), 0))
                c2.metric("ROE %",   fmt(r.get("roe"), 1))
                c3.metric("Score",   f"{r.get('total_score') or 0}/5")
                c4.metric("Verdict", r.get("verdict", "N/A"))

                # Narrative
                try:
                    narr = json.loads(r.get("narrative") or "{}")
                    if narr:
                        st.markdown("**Strengths:**")
                        for s in narr.get("strengths", []):
                            st.markdown(f"- {s}")
                        st.markdown("**Verdict:**")
                        st.info(narr.get("verdict", ""))
                except Exception:
                    pass

                # PDF download
                pdf_path = r.get("pdf_path")
                if pdf_path and os.path.exists(pdf_path):
                    with open(pdf_path, "rb") as pf:
                        st.download_button(
                            label="⬇️ Download Archived PDF",
                            data=pf.read(),
                            file_name=os.path.basename(pdf_path),
                            mime="application/pdf",
                        )

                # Delete
                if st.button(f"🗑️ Delete this record", key=f"del_{r['id']}"):
                    delete_evaluation(r["id"])
                    if pdf_path and os.path.exists(pdf_path):
                        os.remove(pdf_path)
                    st.rerun()
