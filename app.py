import streamlit as st
import pandas as pd
import openpyxl
import io
import zipfile
import re

# ─────────────────────────────────────────────────────────────────────────────
# 1. MANDATORY: PAGE CONFIG
# ─────────────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Institutional Quant Terminal",
    layout="wide",
    page_icon="⚖️"
)

# ─────────────────────────────────────────────────────────────────────────────
# 2. QUANTITATIVE ENGINE (PURE PYTHON)
# ─────────────────────────────────────────────────────────────────────────────

def safe_float(val):
    if val is None or val == "": return 0.0
    if isinstance(val, (int, float)): return float(val)
    try:
        s = str(val).replace(',', '').replace('₹', '').replace('Rs.', '').strip()
        if '(' in s and ')' in s:
            s = "-" + s.replace('(', '').replace(')', '')
        return float(s)
    except:
        return 0.0

def get_row_values(ws, row_idx):
    """Extracts a series of floats from a specific row, skipping the label."""
    row = ws[row_idx]
    return [safe_float(cell.value) for cell in row[1:] if cell.value is not None]

def process_and_calculate(file_bytes, file_name):
    """Processes workbook: Sanitizes for Screener & calculates metrics for Dashboard."""
    try:
        # Load for data extraction
        in_mem_data = io.BytesIO(file_bytes)
        wb_data = openpyxl.load_workbook(in_mem_data, data_only=True)
        
        if 'Data Sheet' not in wb_data.sheetnames:
            return None, None
        
        ws = wb_data['Data Sheet']
        
        # --- DATA EXTRACTION ---
        cmp_val = safe_float(ws.cell(row=10, column=2).value)
        mcap_val = safe_float(ws.cell(row=11, column=2).value)
        
        sales = get_row_values(ws, 15)
        net_profit = get_row_values(ws, 27)
        op_profit = get_row_values(ws, 32)
        equity_cap = get_row_values(ws, 40)
        reserves = get_row_values(ws, 41)
        borrowings = get_row_values(ws, 43)
        other_liab = get_row_values(ws, 44)
        receivables = get_row_values(ws, 52)
        inventory = get_row_values(ws, 53)
        cash_bank = get_row_values(ws, 54)
        cfo = get_row_values(ws, 58)
        
        # Derived Total Assets (Equity + Liab)
        total_assets = [ (e + r + b + ol) for e, r, b, ol in zip(equity_cap, reserves, borrowings, other_liab) ]

        # Current vs Previous Snapshot
        curr_p = net_profit[-1]; prev_p = net_profit[-2] if len(net_profit) > 1 else curr_p
        curr_s = sales[-1]; prev_s = sales[-2] if len(sales) > 1 else curr_s
        curr_cfo = cfo[-1]
        curr_a = total_assets[-1]; prev_a = total_assets[-2] if len(total_assets) > 1 else curr_a
        curr_b = borrowings[-1]; prev_b = borrowings[-2] if len(borrowings) > 1 else curr_b
        curr_r = reserves[-1]
        curr_e = equity_cap[-1]
        curr_op = op_profit[-1]; prev_op = op_profit[-2] if len(op_profit) > 1 else curr_op
        curr_ol = other_liab[-1]; prev_ol = other_liab[-2] if len(other_liab) > 1 else curr_ol
        curr_ca = receivables[-1] + inventory[-1] + cash_bank[-1]
        prev_ca = (receivables[-2] + inventory[-2] + cash_bank[-2]) if len(receivables) > 1 else curr_ca

        # --- CORE METRICS ---
        metrics = {
            "Company": file_name.replace(".xlsx", ""),
            "Market Cap": mcap_val,
            "Latest P/E": mcap_val / curr_p if curr_p > 0 else 0.0,
            "Debt/Equity": curr_b / (curr_e + curr_r) if (curr_e + curr_r) != 0 else 0.0,
            "Sloan Accrual": (curr_p - curr_cfo) / curr_a if curr_a != 0 else 0.0,
            "OPM %": (curr_op / curr_s) if curr_s != 0 else 0.0,
            "CFO": curr_cfo,
            "Net Profit": curr_p,
            "Borrowings": curr_b
        }
        
        # Altman Z-Score
        x1 = (curr_ca - curr_ol) / curr_a if curr_a != 0 else 0
        x2 = curr_r / curr_a if curr_a != 0 else 0
        x3 = curr_op / curr_a if curr_a != 0 else 0
        x4 = mcap_val / (curr_b + curr_ol) if (curr_b + curr_ol) != 0 else 0
        x5 = curr_s / curr_a if curr_a != 0 else 0
        z = (1.2 * x1) + (1.4 * x2) + (3.3 * x3) + (0.6 * x4) + (0.99 * x5)
        metrics["Altman Z-Score"] = z
        metrics["Altman Zone"] = "Safe" if z > 2.99 else ("Grey" if z >= 1.81 else "Distress")
        
        # Piotroski F-Score (out of 8 Proxy)
        f = 0
        if curr_p > 0: f += 1
        if curr_cfo > 0: f += 1
        if curr_p/curr_a > prev_p/prev_a: f += 1
        if curr_cfo > curr_p: f += 1
        if curr_b <= prev_b: f += 1
        if curr_ca/curr_ol > (prev_ca/prev_ol if prev_ol != 0 else 0): f += 1
        if (curr_op/curr_s) > (prev_op/prev_s if prev_s != 0 else 0): f += 1
        if curr_s > prev_s: f += 1
        metrics["Piotroski Score"] = f

        # --- SANITIZATION (Preserving Workbook for ZIP) ---
        in_mem_sanit = io.BytesIO(file_bytes)
        wb_sanit = openpyxl.load_workbook(in_mem_sanit, data_only=False)
        ds = wb_sanit['Data Sheet']
        for r in range(1, 15):
            for c in range(3, 13):
                cell = ds.cell(row=r, column=c)
                if cell.value is not None and not isinstance(cell.value, (int, float)):
                    if not str(cell.value).replace('.', '', 1).isdigit():
                        cell.value = None

        processed_output = io.BytesIO()
        wb_sanit.save(processed_output)
        processed_output.seek(0)
        
        return processed_output, metrics

    except Exception as e:
        st.error(f"Error processing {file_name}: {e}")
        return None, None

# ─────────────────────────────────────────────────────────────────────────────
# 3. QUALITATIVE ANALYSIS ENGINE (NON-AI)
# ─────────────────────────────────────────────────────────────────────────────

def get_stock_narrative(m):
    """Generates logic-driven strengths and weaknesses."""
    strengths = []
    weaknesses = []
    
    # Safety
    if m["Altman Z-Score"] > 2.99: strengths.append("Fortress Balance Sheet (Safe Altman Zone)")
    elif m["Altman Z-Score"] < 1.81: weaknesses.append("High Insolvency Risk (Distress Altman Zone)")
    
    # Efficiency
    if m["Piotroski Score"] >= 7: strengths.append("Exceptional Operational Momentum (Piotroski 7+)")
    elif m["Piotroski Score"] <= 3: weaknesses.append("Weak Internal Efficiency/Momentum")
    
    # Cash Quality
    if m["Sloan Accrual"] < 0.10: strengths.append("High Earnings Quality (Real Cash backing Profits)")
    else: weaknesses.append("Aggressive Accrual Accounting (Potential Earnings Manipulation)")
    
    # Leverage
    if m["Debt/Equity"] < 0.3: strengths.append("Virtually Debt-Free Operations")
    elif m["Debt/Equity"] > 1.5: weaknesses.append("High Financial Gearing / Interest Burden")

    return strengths, weaknesses

def compare_strategic_logic(a, b):
    """Compares two stocks and provides a lead candidate."""
    analysis = {}
    
    # Safety Lead
    if a["Altman Z-Score"] > b["Altman Z-Score"]:
        analysis["safety_lead"] = a["Company"]
    else:
        analysis["safety_lead"] = b["Company"]
        
    # Value Lead
    pe_a = a["Latest P/E"] if a["Latest P/E"] > 0 else 999
    pe_b = b["Latest P/E"] if b["Latest P/E"] > 0 else 999
    if pe_a < pe_b:
        analysis["value_lead"] = a["Company"]
    else:
        analysis["value_lead"] = b["Company"]
        
    return analysis

# ─────────────────────────────────────────────────────────────────────────────
# 4. STREAMLIT UI
# ─────────────────────────────────────────────────────────────────────────────

def main():
    st.title("⚖️ Institutional Quant Batch Terminal")
    
    uploaded_files = st.sidebar.file_uploader("Upload Screener Excel Files", type=["xlsx"], accept_multiple_files=True)
    
    if st.sidebar.button("🚀 Process Batch"):
        if not uploaded_files:
            st.warning("Please upload files.")
            return

        all_results = []
        zip_buffer = io.BytesIO()
        
        with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED, False) as zip_file:
            p_bar = st.progress(0)
            for idx, f in enumerate(uploaded_files):
                p_out, m = process_and_calculate(f.getvalue(), f.name)
                if m:
                    all_results.append(m)
                    zip_file.writestr(f"Processed_{f.name}", p_out.getvalue())
                p_bar.progress((idx + 1) / len(uploaded_files))

            # Master Export for Zip
            summary_df = pd.DataFrame(all_results)
            sum_io = io.BytesIO()
            summary_df.to_excel(sum_io, index=False)
            zip_file.writestr("Master_Comparison.xlsx", sum_io.getvalue())

        st.session_state['results'] = all_results
        st.session_state['zip'] = zip_buffer.getvalue()
        st.success("Batch Processing Complete!")

    if 'results' in st.session_state:
        df = pd.DataFrame(st.session_state['results'])
        
        # --- FIXING KEYERROR & DYNAMIC STYLING ---
        st.subheader("📊 Master Quant Comparison")
        
        # Define preferred display order
        cols_to_show = ["Company", "Market Cap", "Latest P/E", "Debt/Equity", "Sloan Accrual", "Altman Z-Score", "Altman Zone", "Piotroski Score", "OPM %"]
        df_display = df[[c for c in cols_to_show if c in df.columns]]
        
        # Build Format Dictionary Safely
        fmts = {"Market Cap": "₹ {:,.0f} Cr", "Latest P/E": "{:.1f}x", "Debt/Equity": "{:.2f}", "Sloan Accrual": "{:.1%}", "OPM %": "{:.1%}", "Altman Z-Score": "{:.2f}"}
        active_fmts = {k: v for k, v in fmts.items() if k in df_display.columns}
        
        # Apply Styler
        styler = df_display.style.format(active_fmts)
        
        if "Latest P/E" in df_display.columns:
            styler = styler.background_gradient(subset=["Latest P/E"], cmap="RdYlGn_r")
        if "Piotroski Score" in df_display.columns:
            styler = styler.background_gradient(subset=["Piotroski Score"], cmap="RdYlGn")
            
        st.dataframe(styler, use_container_width=True)

        st.download_button("📥 Download ZIP Package", st.session_state['zip'], "Quant_Batch_Report.zip", "application/zip")

        # ─────────────────────────────────────────────────────────────────────
        # 5. QUALITATIVE COMPARISON ENGINE
        # ─────────────────────────────────────────────────────────────────────
        st.divider()
        st.subheader("🕵️ Strategic Deep-Dive Comparison")
        
        comp_names = df["Company"].tolist()
        col_sel1, col_sel2 = st.columns(2)
        stock_a_name = col_sel1.selectbox("Select Benchmark Stock", comp_names, index=0)
        stock_b_name = col_sel2.selectbox("Select Comparison Stock", comp_names, index=min(1, len(comp_names)-1))
        
        if stock_a_name and stock_b_name:
            a = next(item for item in st.session_state['results'] if item["Company"] == stock_a_name)
            b = next(item for item in st.session_state['results'] if item["Company"] == stock_b_name)
            
            logic = compare_strategic_logic(a, b)
            
            # --- Analysis Block ---
            st.info(f"**Executive Verdict:** {logic['safety_lead']} leads on Financial Safety (Altman/Piotroski), while {logic['value_lead']} offers the more attractive relative valuation.")
            
            col_a, col_b = st.columns(2)
            
            for stock, col in [(a, col_a), (b, col_b)]:
                with col:
                    st.markdown(f"### {stock['Company']}")
                    strn, weak = get_stock_narrative(stock)
                    
                    st.write("**Quick Metrics:**")
                    st.write(f"- **Piotroski:** {stock['Piotroski Score']}/8 ({'High Quality' if stock['Piotroski Score']>6 else 'Struggling' if stock['Piotroski Score']<4 else 'Average'})")
                    st.write(f"- **Altman Z:** {stock['Altman Z-Score']:.2f} ({stock['Altman Zone']} Zone)")
                    st.write(f"- **Earnings Quality:** {'High' if stock['Sloan Accrual'] < 0.1 else 'Poor'} (Sloan: {stock['Sloan Accrual']:.1%})")
                    
                    st.markdown("**🟢 Core Strengths**")
                    for s in strn: st.markdown(f"- {s}")
                    
                    st.markdown("**🔴 Key Drawbacks**")
                    for w in weak: st.markdown(f"- {w}")

            st.divider()
            st.markdown("### 🚦 Investor Decision Framework")
            st.write(f"""
            **Choose {stock_a_name} if:** You prioritize {'Defense & Safety' if a['Altman Z-Score'] > b['Altman Z-Score'] else 'Value Opportunity'}. 
            {stock_a_name} shows {'stronger' if a['Sloan Accrual'] < b['Sloan Accrual'] else 'weaker'} cash conversion metrics than {stock_b_name}.
            
            **Choose {stock_b_name} if:** You are seeking a {'valuation-led entry' if b['Latest P/E'] < a['Latest P/E'] else 'growth momentum play'}. 
            {stock_b_name}'s OPM of {stock_b_name['OPM %']:.1%} suggests {'superior' if b['OPM %'] > a['OPM %'] else 'lower'} pricing power relative to its peer.
            
            **Thesis Inversion Risks:** High inflation or rising interest rates will hit {stock_a_name if a['Debt/Equity'] > b['Debt/Equity'] else stock_b_name} harder due to higher leverage. 
            Conversely, an economic boom would benefit {stock_a_name if a['OPM %'] > b['OPM %'] else stock_b_name} more significantly due to higher operating leverage.
            """)

if __name__ == "__main__":
    main()
