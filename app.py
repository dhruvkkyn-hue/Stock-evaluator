import streamlit as st
import pandas as pd
import openpyxl
import io
import re
import os

# ─────────────────────────────────────────────────────────────────────────────
# 1. PAGE CONFIGURATION & THEME
# ─────────────────────────────────────────────────────────────────────────────
st.set_page_config(page_title="Institutional Quant Terminal", layout="wide", page_icon="⚖️")

# ─────────────────────────────────────────────────────────────────────────────
# 2. SAFE PARSING & MATH HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def safe_div(numerator, denominator, default=0.0):
    try:
        num, den = float(numerator or 0), float(denominator or 0)
        return num / den if den != 0 else default
    except (ValueError, TypeError):
        return default

def safe_float(val, default=0.0):
    try:
        if val is None: return default
        if isinstance(val, (int, float)): return float(val)
        s = str(val).replace(',', '').replace('₹', '').replace('Rs.', '').strip()
        if '(' in s and ')' in s: s = "-" + s.replace('(', '').replace(')', '')
        return float(s)
    except (ValueError, TypeError):
        return default

# ─────────────────────────────────────────────────────────────────────────────
# 3. DYNAMIC DATA EXTRACTION ENGINE
# ─────────────────────────────────────────────────────────────────────────────

def get_row_data(ws, labels):
    """Finds row by matching label in Col A and returns numeric series."""
    for row in ws.iter_rows(min_col=1, max_col=1):
        cell_val = str(row[0].value).lower() if row[0].value else ""
        if any(lbl.lower() in cell_val for lbl in labels):
            data = []
            for col in range(2, ws.max_column + 1):
                val = ws.cell(row=row[0].row, column=col).value
                if val is not None: data.append(safe_float(val))
            return data
    return []

def parse_screener_xlsx(file):
    """Parses a Screener.in export file dynamically with fallback logic."""
    try:
        wb = openpyxl.load_workbook(io.BytesIO(file.getvalue()), data_only=True)
        ds_name = next((s for s in wb.sheetnames if "data sheet" in s.lower()), None)
        if not ds_name: return None
        ws = wb[ds_name]
        
        company_name = str(ws.cell(row=1, column=2).value or "Unknown").strip()

        # Data series mapping
        sales = get_row_data(ws, ["Sales", "Revenue", "Interest Earned"])
        profit = get_row_data(ws, ["Net Profit", "Profit after tax"])
        op_profit = get_row_data(ws, ["Operating Profit", "Operating Profit / (Loss)", "PBIT"])
        borrowings = get_row_data(ws, ["Borrowings", "Total Debt"])
        cfo = get_row_data(ws, ["Cash from Operating", "Net Cashflow from Operating"])
        assets = get_row_data(ws, ["Total Assets"])
        equity = get_row_data(ws, ["Equity Share Capital", "Share Capital"])
        reserves = get_row_data(ws, ["Reserves"])
        mcap = safe_float(ws.cell(row=11, column=2).value)

        # Snapshot Extraction
        c_p = profit[-1] if profit else 0
        c_s = sales[-1] if sales else 0
        c_b = borrowings[-1] if borrowings else 0
        c_a = assets[-1] if assets else 0
        c_op = op_profit[-1] if op_profit else 0
        c_cfo = cfo[-1] if cfo else 0
        total_equity = safe_float(equity[-1] if equity else 0) + safe_float(reserves[-1] if reserves else 0)

        # Calculations
        pe = safe_div(mcap, c_p)
        de = safe_div(c_b, total_equity)
        sloan = safe_div(c_p - c_cfo, c_a)
        
        # Altman Proxy (Simplified)
        z_score = (1.4 * safe_div(reserves[-1] if reserves else 0, c_a)) + \
                  (3.3 * safe_div(c_op, c_a)) + \
                  (0.6 * safe_div(mcap, c_b)) + \
                  (0.99 * safe_div(c_s, c_a))

        # Piotroski F-Score (out of 8 simplified)
        f_score = 0
        if c_p > 0: f_score += 1
        if c_cfo > 0: f_score += 1
        if c_cfo > c_p: f_score += 1
        if len(profit) > 1 and c_p > profit[-2]: f_score += 1
        if len(borrowings) > 1 and c_b <= borrowings[-2]: f_score += 1
        if len(sales) > 1 and c_s > sales[-2]: f_score += 1
        if c_a > 0: f_score += 1
        if c_op > 0: f_score += 1

        return {
            "Company": company_name,
            "Market Cap": mcap,
            "P/E": pe,
            "D/E": de,
            "Sloan Ratio": sloan,
            "Z-Score": z_score,
            "F-Score": f_score,
            "Sales": c_s,
            "Net Profit": c_p
        }
    except Exception as e:
        st.sidebar.error(f"Error parsing file: {e}")
        return None

# ─────────────────────────────────────────────────────────────────────────────
# 4. MAIN UI DASHBOARD
# ─────────────────────────────────────────────────────────────────────────────

st.title("🏛️ Institutional Quantitative Terminal")
st.markdown("---")

files = st.sidebar.file_uploader("Upload Screener.in Excels", type="xlsx", accept_multiple_files=True)

if files:
    data_list = [parsed for f in files if (parsed := parse_screener_xlsx(f))]

    if data_list:
        df = pd.DataFrame(data_list)
        st.subheader("📊 Master Metrics Comparison")

        # Define all possible columns for formatting
        format_dict = {
            "Market Cap": "₹{:,.0f} Cr",
            "Sales": "₹{:,.0f} Cr",
            "Net Profit": "₹{:,.0f} Cr",
            "P/E": "{:.1f}x",
            "D/E": "{:.2f}",
            "Sloan Ratio": "{:.1%}",
            "Z-Score": "{:.2f}"
        }

        # ── BULLETPROOF TABLE STYLING ──
        styler = df.style
        
        # 1. Apply formatting only to columns that exist
        active_formats = {col: fmt for col, fmt in format_dict.items() if col in df.columns}
        styler = styler.format(active_formats)

        # 2. Safe Background Gradient Wrapper
        try:
            import matplotlib
            import jinja2
            if "F-Score" in df.columns:
                styler = styler.background_gradient(subset=["F-Score"], cmap="RdYlGn")
        except ImportError:
            st.info("💡 Note: Matplotlib not found. Table rendered without color gradients.")
        except Exception as e:
            pass # Silent failure to preserve table visibility

        st.dataframe(styler, use_container_width=True)

        # ─────────────────────────────────────────────────────────────────────
        # 5. ENGLISH COMPARISON ENGINE
        # ─────────────────────────────────────────────────────────────────────
        st.divider()
        st.subheader("🕵️ Side-by-Side Deep-Dive")
        
        c1, c2 = st.columns(2)
        stock_a_name = c1.selectbox("Select Stock A", df["Company"].tolist(), index=0)
        stock_b_name = c2.selectbox("Select Stock B", df["Company"].tolist(), index=min(1, len(df)-1))

        stock_a = df[df["Company"] == stock_a_name].iloc[0]
        stock_b = df[df["Company"] == stock_b_name].iloc[0]

        # Executive Summary
        st.info("### 🏁 Head-to-Head Summary")
        safety_winner = stock_a_name if stock_a["Z-Score"] > stock_b["Z-Score"] else stock_b_name
        value_winner = stock_a_name if (0 < stock_a["P/E"] < stock_b["P/E"]) or (stock_b["P/E"] <= 0) else stock_b_name
        
        st.write(f"- **Safety Leader:** {safety_winner} shows higher insolvency resilience.")
        st.write(f"- **Value Leader:** {value_winner} offers a more attractive P/E multiple.")

        # Metric Breakdown
        ca, cb = st.columns(2)
        for stock, col in [(stock_a, ca), (stock_b, cb)]:
            with col:
                st.markdown(f"#### {stock['Company']} Analysis")
                st.write(f"**Piotroski Score:** `{stock['F-Score']}/8` — " + ("Strong Momentum" if stock["F-Score"] >= 6 else "Weak Fundamentals"))
                
                z = stock["Z-Score"]
                z_zone = "Safe ✅" if z > 2.99 else "Grey ⚠️" if z >= 1.81 else "Distress 🚨"
                st.write(f"**Altman Risk:** {z_zone}")
                
                s = stock["Sloan Ratio"]
                st.write(f"**Earnings Quality:** " + ("High Quality 💎" if abs(s) < 0.10 else "Low/Aggressive 🚩"))

        # Decision Framework
        st.success("### 🚦 Strategic Decision Framework")
        st.write(f"""
        1. **Favor {stock_a_name} if:** You prioritize **{'Quality' if stock_a['F-Score'] >= stock_b['F-Score'] else 'Value'}**.
        2. **Favor {stock_b_name} if:** Your thesis relies on **{'Turnaround' if stock_b['F-Score'] > 5 else 'Relative Pricing'}**.
        3. **Risk Warning:** Rising interest rates will impact **{stock_a_name if stock_a['D/E'] > stock_b['D/E'] else stock_b_name}** more severely due to higher leverage.
        """)

else:
    st.info("👋 Upload Screener.in Excel files in the sidebar to begin.")
