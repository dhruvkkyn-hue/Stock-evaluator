import streamlit as st
import pandas as pd
import openpyxl
import io
import re

# ─────────────────────────────────────────────────────────────────────────────
# 1. PAGE CONFIGURATION & THEME
# ─────────────────────────────────────────────────────────────────────────────
st.set_page_config(page_title="Institutional Quant Terminal", layout="wide", page_icon="⚖️")

# ─────────────────────────────────────────────────────────────────────────────
# 2. SAFE PARSING & MATH HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def safe_div(numerator, denominator, default=0.0):
    """Prevents ZeroDivisionError and handles None/NaN values."""
    try:
        if denominator is None or numerator is None:
            return default
        num = float(numerator)
        den = float(denominator)
        if den == 0:
            return default
        return num / den
    except (ValueError, TypeError, ZeroDivisionError):
        return default

def safe_float(val, default=0.0):
    """Cleans currency/string formatting and safely converts to float."""
    try:
        if val is None:
            return default
        if isinstance(val, (int, float)):
            return float(val)
        # Remove currency symbols, commas, and spaces
        s = str(val).replace(',', '').replace('₹', '').replace('Rs.', '').strip()
        if '(' in s and ')' in s: # Handle accounting negative numbers (100)
            s = "-" + s.replace('(', '').replace(')', '')
        return float(s)
    except (ValueError, TypeError):
        return default

# ─────────────────────────────────────────────────────────────────────────────
# 3. DYNAMIC DATA EXTRACTION ENGINE
# ─────────────────────────────────────────────────────────────────────────────

def get_row_data(ws, labels):
    """
    Finds row index by matching labels in Column A and returns 
    the numeric series from that row.
    """
    target_row = None
    # Search for the first matching label (case-insensitive substring match)
    for row in ws.iter_rows(min_col=1, max_col=1):
        cell_val = str(row[0].value).lower() if row[0].value else ""
        if any(lbl.lower() in cell_val for lbl in labels):
            target_row = row[0].row
            break
    
    if not target_row:
        return []

    # Extract all numeric values in that row (skipping the label in Col A)
    data = []
    for col in range(2, ws.max_column + 1):
        val = ws.cell(row=target_row, column=col).value
        if val is not None:
            data.append(safe_float(val))
    return data

def parse_screener_xlsx(file):
    """Parses a single Screener.in export file dynamically."""
    try:
        # Load with data_only=True to get calculated results, not formula strings
        wb = openpyxl.load_workbook(io.BytesIO(file.getvalue()), data_only=True)
        ds_name = next((s for s in wb.sheetnames if "data sheet" in s.lower()), None)
        if not ds_name:
            return None
        
        ws = wb[ds_name]
        company_name = str(ws.cell(row=1, column=2).value).strip()

        # Dynamic Row Lookups
        sales_series = get_row_data(ws, ["Sales", "Revenue", "Interest Earned"])
        profit_series = get_row_data(ws, ["Net Profit", "Profit after tax"])
        op_profit_series = get_row_data(ws, ["Operating Profit", "Operating Profit / (Loss)", "PBIT"])
        borrowing_series = get_row_data(ws, ["Borrowings", "Total Debt"])
        cfo_series = get_row_data(ws, ["Cash from Operating", "Net Cashflow from Operating"])
        asset_series = get_row_data(ws, ["Total Assets"])
        equity_series = get_row_data(ws, ["Equity Share Capital", "Share Capital"])
        reserves_series = get_row_data(ws, ["Reserves"])
        mcap = safe_float(ws.cell(row=11, column=2).value) # Fixed Screener Summary Metadata
        
        # Latest Values (Snapshot)
        curr_sales = sales_series[-1] if sales_series else 0
        curr_profit = profit_series[-1] if profit_series else 0
        curr_op_profit = op_profit_series[-1] if op_profit_series else 0
        curr_borrowings = borrowing_series[-1] if borrowing_series else 0
        curr_cfo = cfo_series[-1] if cfo_series else 0
        curr_assets = asset_series[-1] if asset_series else 0
        curr_equity = equity_series[-1] if equity_series else 0
        curr_reserves = reserves_series[-1] if reserves_series else 0
        total_equity = curr_equity + curr_reserves

        # ─── QUANTITATIVE RATIOS (SAFE) ───
        pe = safe_div(mcap, curr_profit)
        de = safe_div(curr_borrowings, total_equity)
        sloan = safe_div(curr_profit - curr_cfo, curr_assets)
        
        # Altman Z-Score Proxy
        # Simplified for Screener structure: WC/TA, RE/TA, EBIT/TA, MCap/Debt, Sales/TA
        x1 = 0 # Working capital proxy often missing in summary data sheet
        x2 = safe_div(curr_reserves, curr_assets)
        x3 = safe_div(curr_op_profit, curr_assets)
        x4 = safe_div(mcap, curr_borrowings)
        x5 = safe_div(curr_sales, curr_assets)
        z_score = (1.2 * x1) + (1.4 * x2) + (3.3 * x3) + (0.6 * x4) + (0.99 * x5)

        # Piotroski F-Score (out of 8 simplified)
        f_score = 0
        if curr_profit > 0: f_score += 1
        if curr_cfo > 0: f_score += 1
        if curr_cfo > curr_profit: f_score += 1
        if len(profit_series) > 1 and curr_profit > profit_series[-2]: f_score += 1
        if len(borrowing_series) > 1 and curr_borrowings <= borrowing_series[-2]: f_score += 1
        if len(sales_series) > 1 and curr_sales > sales_series[-2]: f_score += 1
        if curr_assets > 0: f_score += 1 
        if curr_op_profit > 0: f_score += 1

        return {
            "Company": company_name,
            "Market Cap": mcap,
            "P/E": pe,
            "D/E": de,
            "Sloan": sloan,
            "Z-Score": z_score,
            "F-Score": f_score,
            "Net Profit": curr_profit,
            "Sales": curr_sales,
            "CFO": curr_cfo,
            "Assets": curr_assets
        }
    except Exception as e:
        st.sidebar.error(f"Error parsing file: {e}")
        return None

# ─────────────────────────────────────────────────────────────────────────────
# 4. MAIN UI DASHBOARD
# ─────────────────────────────────────────────────────────────────────────────

st.title("🏛️ Institutional Quantitative Dashboard")
st.markdown("---")

files = st.sidebar.file_uploader("Upload Screener.in Excels", type="xlsx", accept_multiple_files=True)

if files:
    data_list = []
    for f in files:
        parsed = parse_screener_xlsx(f)
        if parsed:
            data_list.append(parsed)

    if data_list:
        df = pd.DataFrame(data_list)
        
        # Display Table
        st.subheader("📊 Comparative Financial Matrix")
        st.dataframe(df.style.format({
            "Market Cap": "₹{:,.0f} Cr",
            "P/E": "{:.2f}x",
            "D/E": "{:.2f}",
            "Sloan": "{:.2%}",
            "Z-Score": "{:.2f}",
            "Net Profit": "₹{:,.0f} Cr",
            "Sales": "₹{:,.0f} Cr"
        }).background_gradient(subset=["F-Score"], cmap="RdYlGn"))

        # ─────────────────────────────────────────────────────────────────────
        # 5. ENGLISH COMPARISON ENGINE (NON-AI)
        # ─────────────────────────────────────────────────────────────────────
        st.markdown("---")
        st.subheader("🕵️ Side-by-Side Qualitative Analysis")
        
        col1, col2 = st.columns(2)
        stock_a_name = col1.selectbox("Select Stock A", df["Company"].tolist(), index=0)
        stock_b_name = col2.selectbox("Select Stock B", df["Company"].tolist(), index=min(1, len(df)-1))

        stock_a = df[df["Company"] == stock_a_name].iloc[0]
        stock_b = df[df["Company"] == stock_b_name].iloc[0]

        # ── Analysis Summary ──
        st.info("### 🏁 Head-to-Head Summary")
        safety_winner = stock_a_name if stock_a["Z-Score"] > stock_b["Z-Score"] else stock_b_name
        value_winner = stock_a_name if (0 < stock_a["P/E"] < stock_b["P/E"]) or (stock_b["P/E"] <= 0) else stock_b_name
        
        st.write(f"- **Safety Leader:** {safety_winner} displays a more resilient balance sheet profile.")
        st.write(f"- **Value Leader:** {value_winner} currently offers more attractive entry pricing relative to earnings.")

        # ── Metric Deep Dive ──
        c_a, c_b = st.columns(2)
        for stock, col in [(stock_a, c_a), (stock_b, c_b)]:
            with col:
                st.markdown(f"#### {stock['Company']} Evaluation")
                
                # Piotroski
                f = stock["F-Score"]
                f_desc = "Strong" if f >= 6 else "Average" if f >= 4 else "Weak"
                st.write(f"**Operational Momentum:** {f}/8 ({f_desc})")
                
                # Altman
                z = stock["Z-Score"]
                z_zone = "Safe ✅" if z > 2.99 else "Grey ⚠️" if z >= 1.81 else "Distress 🚨"
                st.write(f"**Insolvency Risk:** {z_zone} (Score: {z:.2f})")
                
                # Sloan
                s = stock["Sloan"]
                s_desc = "High Quality 💎" if abs(s) < 0.10 else "Low Quality/Aggressive 🚩"
                st.write(f"**Earnings Quality:** {s_desc} (Ratio: {s:.2%})")
                
                # Valuation
                st.write(f"**Financial Leverage:** D/E of {stock['D/E']:.2f}")

        # ── Pros & Cons ──
        st.markdown("#### ⚖️ Strategic Strengths & Constraints")
        p_a, p_b = st.columns(2)
        for stock, peer, col in [(stock_a, stock_b, p_a), (stock_b, stock_a, p_b)]:
            with col:
                st.write(f"**Pros for {stock['Company']}:**")
                if stock["Z-Score"] > 2.99: st.write("- Fortress balance sheet provides high margin of safety.")
                if stock["F-Score"] >= 7: st.write("- Exceptional management efficiency and operational trending.")
                if abs(stock["Sloan"]) < 0.05: st.write("- Conservative accounting; profits are backed by cash.")
                
                st.write(f"**Constraints:**")
                if stock["P/E"] > 50: st.write("- Expensive valuation requires high growth to justify.")
                if stock["D/E"] > 1.5: st.write("- Elevated debt-to-equity may restrict future expansion.")

        # ── Investor Decision Framework ──
        st.success("### 🚦 Strategic Decision Framework")
        st.write(f"""
        1. **When to favor {stock_a_name}:** If you prioritize **{'Safety & Quality' if stock_a['F-Score'] >= stock_b['F-Score'] else 'Value Opportunity'}**. 
        {stock_a_name} is the superior choice for a defensive portfolio looking to weather market volatility.

        2. **When to favor {stock_b_name}:** If the investment thesis relies on **{'Operational Turnaround' if stock_b['F-Score'] > 5 else 'Relative Pricing'}**. 
        This stock is better suited for investors seeking a higher potential return-on-equity play.

        3. **Thesis Inversion Risks:**
        - **Interest Rate Shocks:** Higher risk for **{stock_a_name if stock_a['D/E'] > stock_b['D/E'] else stock_b_name}** due to debt levels.
        - **Cyclical Downturn:** **{stock_a_name if stock_a['Z-Score'] < stock_b['Z-Score'] else stock_b_name}** is more vulnerable to bankruptcy during credit freezes.
        """)
else:
    st.info("👋 Upload Screener.in Excel files in the sidebar to begin analysis.")
