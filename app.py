import streamlit as st
import pandas as pd
import openpyxl
import io
import re

# ─────────────────────────────────────────────────────────────────────────────
# 1. SETUP & CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────────
st.set_page_config(page_title="Institutional Equity Terminal", layout="wide", page_icon="⚖️")

# Row Labels to search for (Flexible matching for different sectors/banks)
MAP = {
    "revenue": ["sales", "revenue", "interest earned"],
    "net_profit": ["net profit", "profit after tax"],
    "market_cap": ["market capitalization", "market cap"],
    "borrowings": ["borrowings", "total debt"],
    "equity": ["equity share capital", "share capital"],
    "reserves": ["reserves"],
    "assets": ["total assets"],
    "cfo": ["cash from operating activity", "cfo", "net cashflow from operating"],
    "op_profit": ["operating profit", "pbit", "operating profit / (loss)"],
    "liabilities": ["other liabilities", "total liabilities"],
    "receivables": ["trade receivables", "receivables"],
    "inventory": ["inventory", "inventories"],
    "cash": ["cash & bank", "cash equivalents"]
}

# ─────────────────────────────────────────────────────────────────────────────
# 2. DYNAMIC PARSING ENGINE
# ─────────────────────────────────────────────────────────────────────────────

def get_row_index(ws, search_terms):
    """Finds the row index by searching Column A for specific labels."""
    for row in ws.iter_rows(min_col=1, max_col=1):
        val = str(row[0].value).lower() if row[0].value else ""
        if any(term in val for term in search_terms):
            return row[0].row
    return None

def get_row_data(ws, row_idx):
    """Extracts all numeric values from a row, ignoring labels and empty cells."""
    if not row_idx:
        return []
    data = []
    for col in range(2, ws.max_column + 1):
        val = ws.cell(row=row_idx, column=col).value
        # Clean numeric data (Screener sometimes exports as strings with commas)
        if val is not None:
            try:
                if isinstance(val, str):
                    val = val.replace(",", "").replace("₹", "").strip()
                data.append(float(val))
            except ValueError:
                continue
    return data

def parse_screener_file(uploaded_file):
    """Parses a single Screener.in Excel file dynamically."""
    try:
        # Load workbook (data_only=True to get values, not formulas)
        wb = openpyxl.load_workbook(io.BytesIO(uploaded_file.getvalue()), data_only=True)
        
        # Check for 'Data Sheet'
        ds_name = next((s for s in wb.sheetnames if "data sheet" in s.lower()), None)
        if not ds_name:
            return None
        
        ws = wb[ds_name]
        company_name = str(ws.cell(row=1, column=2).value).strip()

        # Extract latest numeric values dynamically
        def fetch_latest(key):
            idx = get_row_index(ws, MAP[key])
            series = get_row_data(ws, idx)
            return series[-1] if series else 0, series

        mcap, _ = fetch_latest("market_cap")
        net_profit, net_profit_series = fetch_latest("net_profit")
        sales, sales_series = fetch_latest("revenue")
        cfo, _ = fetch_latest("cfo")
        borrowings, borrowings_series = fetch_latest("borrowings")
        assets, asset_series = fetch_latest("assets")
        equity, _ = fetch_latest("equity")
        reserves, _ = fetch_latest("reserves")
        op_profit, op_profit_series = fetch_latest("op_profit")
        curr_liab, _ = fetch_latest("liabilities")
        receivables, _ = fetch_latest("receivables")
        inventory, _ = fetch_latest("inventory")
        cash, _ = fetch_latest("cash")

        # ─────────────────────────────────────────────────────────────────────
        # 3. QUANTITATIVE CALCULATIONS
        # ─────────────────────────────────────────────────────────────────────
        
        # Financial Health Estimates
        total_equity = equity + reserves
        de_ratio = borrowings / total_equity if total_equity != 0 else 0
        pe_ratio = mcap / net_profit if net_profit > 0 else 0
        sloan_ratio = (net_profit - cfo) / assets if assets != 0 else 0
        
        # Altman Z-Score Proxy (Standardized)
        working_cap = (receivables + inventory + cash) - curr_liab
        x1 = working_cap / assets if assets != 0 else 0
        x2 = reserves / assets if assets != 0 else 0
        x3 = op_profit / assets if assets != 0 else 0
        x4 = mcap / (borrowings + curr_liab) if (borrowings + curr_liab) != 0 else 0
        x5 = sales / assets if assets != 0 else 0
        z_score = (1.2 * x1) + (1.4 * x2) + (3.3 * x3) + (0.6 * x4) + (0.99 * x5)

        # Piotroski F-Score (out of 8 simplified)
        f_score = 0
        if net_profit > 0: f_score += 1
        if cfo > 0: f_score += 1
        if cfo > net_profit: f_score += 1
        if len(net_profit_series) > 1 and (net_profit / assets) > (net_profit_series[-2] / (asset_series[-2] if len(asset_series) > 1 else assets)): f_score += 1
        if len(borrowings_series) > 1 and borrowings <= borrowings_series[-2]: f_score += 1
        if len(op_profit_series) > 1 and (op_profit / sales) > (op_profit_series[-2] / (sales_series[-2] if len(sales_series) > 1 else sales)): f_score += 1
        if len(sales_series) > 1 and sales > sales_series[-2]: f_score += 1
        if assets > 0: f_score += 1 # Asset turnover presence

        return {
            "Company": company_name,
            "Market Cap": mcap,
            "P/E Ratio": pe_ratio,
            "D/E Ratio": de_ratio,
            "Piotroski Score": f_score,
            "Altman Z-Score": z_score,
            "Sloan Ratio": sloan_ratio,
            "Sales": sales,
            "Net Profit": net_profit,
            "CFO": cfo
        }
    except Exception as e:
        st.sidebar.error(f"Error parsing {uploaded_file.name}: {e}")
        return None

# ─────────────────────────────────────────────────────────────────────────────
# 4. MAIN INTERFACE
# ─────────────────────────────────────────────────────────────────────────────

st.title("🏛️ Institutional Equity Research Terminal")
st.markdown("---")

uploaded_files = st.sidebar.file_uploader("Upload Screener.in Excel Files", type="xlsx", accept_multiple_files=True)

if uploaded_files:
    results = []
    for file in uploaded_files:
        data = parse_screener_file(file)
        if data:
            results.append(data)

    if not results:
        st.error("No valid data could be parsed. Ensure files are original Screener.in exports.")
        st.stop()

    df = pd.DataFrame(results)

    # Main Comparison Table
    st.subheader("📊 Master Metrics Comparison")
    st.dataframe(
        df.style.format({
            "Market Cap": "₹{:,.0f} Cr",
            "P/E Ratio": "{:.2f}x",
            "D/E Ratio": "{:.2f}",
            "Altman Z-Score": "{:.2f}",
            "Sloan Ratio": "{:.2%}",
            "Sales": "₹{:,.0f} Cr",
            "Net Profit": "₹{:,.0f} Cr"
        }).background_gradient(subset=["Piotroski Score"], cmap="RdYlGn")
    )

    # ─────────────────────────────────────────────────────────────────────────
    # 5. COMPARATIVE ANALYSIS ENGINE (PLAIN ENGLISH)
    # ─────────────────────────────────────────────────────────────────────────
    st.markdown("---")
    st.subheader("🕵️ Side-by-Side Investment Deep-Dive")
    
    col_sel1, col_sel2 = st.columns(2)
    stock_a_name = col_sel1.selectbox("Select Stock A", df["Company"].unique(), index=0)
    stock_b_name = col_sel2.selectbox("Select Stock B", df["Company"].unique(), index=min(1, len(df)-1))

    stock_a = df[df["Company"] == stock_a_name].iloc[0]
    stock_b = df[df["Company"] == stock_b_name].iloc[0]

    # Analysis Logic
    def get_z_zone(val):
        if val > 2.99: return "Safe ✅", "Low bankruptcy risk; fortress balance sheet."
        if val >= 1.81: return "Grey ⚠️", "Moderate risk; monitor debt obligations closely."
        return "Distress 🚨", "High risk of financial insolvency within 2 years."

    def get_sloan_desc(val):
        if abs(val) < 0.10: return "High Quality 💎", "Earnings are backed by solid cash flow."
        return "Aggressive Accruals 🚩", "Non-cash earnings; potential accounting manipulation."

    # 1. Executive Summary
    st.info(f"### 🏁 Executive Summary")
    safety_lead = stock_a_name if stock_a["Altman Z-Score"] > stock_b["Altman Z-Score"] else stock_b_name
    value_lead = stock_a_name if (0 < stock_a["P/E Ratio"] < stock_b["P/E Ratio"]) or (stock_b["P/E Ratio"] <= 0) else stock_b_name
    
    st.write(f"""
    * **Financial Safety Leader:** {safety_lead} (Superior Z-Score and Solvency)
    * **Valuation / Margin of Safety:** {value_lead} (Lower relative P/E Multiple)
    """)

    # 2. Deep Dive Metrics
    c1, c2 = st.columns(2)
    
    for stock, col in [(stock_a, c1), (stock_b, c2)]:
        z_zone, z_desc = get_z_zone(stock["Altman Z-Score"])
        sloan_zone, sloan_desc = get_sloan_desc(stock["Sloan Ratio"])
        
        with col:
            st.markdown(f"#### {stock['Company']} Analysis")
            st.write(f"**Piotroski Score:** `{stock['Piotroski Score']}/8` — " + 
                     ("Robust operational momentum." if stock['Piotroski Score'] >= 6 else "Weak fundamental trends."))
            
            st.write(f"**Altman Zone:** {z_zone}")
            st.caption(z_desc)
            
            st.write(f"**Earnings Quality:** {sloan_zone}")
            st.caption(sloan_desc)
            
            st.write(f"**Valuation Check:** Trading at `{stock['P/E Ratio']:.1f}x` earnings.")

    # 3. Pros & Cons
    st.markdown("#### ⚖️ Balance Sheet & Growth Quality")
    p_a, p_b = st.columns(2)
    
    for stock, col in [(stock_a, p_a), (stock_b, p_b)]:
        with col:
            st.write(f"**Strengths for {stock['Company']}:**")
            if stock['D/E Ratio'] < 0.5: st.write("- Low leverage; high interest coverage resilience.")
            if stock['Piotroski Score'] >= 7: st.write("- Exceptional internal management and efficiency.")
            if stock['CFO'] > stock['Net Profit']: st.write("- Cash conversion is superior to reported profits.")
            
            st.write(f"**Potential Risks:**")
            if stock['D/E Ratio'] > 1.5: st.write("- High debt burden; sensitive to interest rate hikes.")
            if stock['P/E Ratio'] > 40: st.write("- Aggressive valuation; susceptible to de-rating.")

    # 4. Investor Decision Framework
    st.success("### 🚦 Decision Framework")
    st.write(f"""
    **Choose {stock_a_name} if:** You are looking for a **{'Defensive Value' if stock_a['P/E Ratio'] < stock_b['P/E Ratio'] else 'Quality Growth'}** play. 
    It is best suited for an investor who prioritizes {('earnings purity' if abs(stock_a['Sloan Ratio']) < abs(stock_b['Sloan Ratio']) else 'fundamental safety')}.

    **Choose {stock_b_name} if:** You believe the market is underestimating its **{'pricing power' if stock_b['Piotroski Score'] > stock_a['Piotroski Score'] else 'solvency strength'}**.

    **Thesis Inversion Triggers:**
    1. **Interest Rate Hikes:** Will disproportionately hurt **{stock_a_name if stock_a['D/E Ratio'] > stock_b['D/E Ratio'] else stock_b_name}** due to higher debt levels.
    2. **Credit Cycle Contraction:** Companies in the **{ 'Distress' if min(stock_a['Altman Z-Score'], stock_b['Altman Z-Score']) < 1.81 else 'Grey'}** Altman zone will face immediate liquidity pressures.
    3. **Margin Compression:** If raw material costs rise, **{stock_a_name if stock_a['Piotroski Score'] < stock_b['Piotroski Score'] else stock_b_name}** has less operational cushion to protect the bottom line.
    """)

else:
    st.info("👋 Welcome! Please upload one or more Screener.in Excel exports in the sidebar to begin institutional-grade analysis.")
