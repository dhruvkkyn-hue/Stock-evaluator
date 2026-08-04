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
    page_title="Screener Batch Quant Engine (Python Logic)",
    layout="wide",
    page_icon="⚖️"
)

# ─────────────────────────────────────────────────────────────────────────────
# 2. QUANTITATIVE CALCULATION ENGINE (PURE PYTHON)
# ─────────────────────────────────────────────────────────────────────────────

def safe_float(val):
    """Converts messy Excel/Screener strings to clean floats."""
    if val is None or val == "": return 0.0
    if isinstance(val, (int, float)): return float(val)
    try:
        s = str(val).replace(',', '').replace('₹', '').replace('Rs.', '').strip()
        if '(' in s and ')' in s: # Handle accounting negative: (100.00)
            s = "-" + s.replace('(', '').replace(')', '')
        return float(s)
    except:
        return 0.0

def get_row_values(ws, row_idx):
    """
    Returns a list of floats for a specific row index.
    Screener columns usually: [Label, Mar-2018, Mar-2019, ..., Latest]
    Index 0: Label | Index 1 onwards: Years
    """
    row = ws[row_idx]
    # We skip the first column (label) and take the rest
    return [safe_float(cell.value) for cell in row[1:] if cell.value is not None]

def process_and_calculate(file_bytes, file_name):
    # Load for formulas (to keep zip export intact)
    in_mem_formulas = io.BytesIO(file_bytes)
    wb_formulas = openpyxl.load_workbook(in_mem_formulas, data_only=False)
    
    # Load for static data extraction
    in_mem_data = io.BytesIO(file_bytes)
    wb_data = openpyxl.load_workbook(in_mem_data, data_only=True)
    
    metrics = {"File Name": file_name, "Company": file_name.replace(".xlsx", "")}
    
    try:
        if 'Data Sheet' not in wb_data.sheetnames:
            return None, None
        
        ws = wb_data['Data Sheet']
        
        # 1. EXTRACT DATA SERIES (Row indices in openpyxl are 1-based)
        # We assume the LAST item in the row is the 'Latest' year.
        cmp_val      = safe_float(ws.cell(row=10, column=2).value)
        mcap_val     = safe_float(ws.cell(row=11, column=2).value)
        
        sales        = get_row_values(ws, 15)
        net_profit   = get_row_values(ws, 27)
        op_profit    = get_row_values(ws, 32)
        equity_cap   = get_row_values(ws, 40)
        reserves     = get_row_values(ws, 41)
        borrowings   = get_row_values(ws, 43)
        other_liab   = get_row_values(ws, 44)
        receivables  = get_row_values(ws, 52)
        inventory    = get_row_values(ws, 53)
        cash_bank    = get_row_values(ws, 54)
        cfo          = get_row_values(ws, 58)
        
        # Total Assets calculation (Sum of Liab + Equity)
        total_assets = [ (e + r + b + ol) for e, r, b, ol in zip(equity_cap, reserves, borrowings, other_liab) ]

        # 2. SELECT LATEST AND PREVIOUS (for YoY)
        # Use -1 for latest, -2 for previous
        curr_p = net_profit[-1];   prev_p = net_profit[-2] if len(net_profit) > 1 else curr_p
        curr_s = sales[-1];        prev_s = sales[-2] if len(sales) > 1 else curr_s
        curr_cfo = cfo[-1]
        curr_a = total_assets[-1]
        curr_b = borrowings[-1];   prev_b = borrowings[-2] if len(borrowings) > 1 else curr_b
        curr_r = reserves[-1]
        curr_e = equity_cap[-1]
        curr_op = op_profit[-1];   prev_op = op_profit[-2] if len(op_profit) > 1 else curr_op
        curr_ol = other_liab[-1]
        curr_ca = receivables[-1] + inventory[-1] + cash_bank[-1]

        # 3. CALCULATE DASHBOARD METRICS
        metrics["Market Cap"] = mcap_val
        metrics["Latest P/E"] = mcap_val / curr_p if curr_p > 0 else 0.0
        metrics["Debt/Equity"] = curr_b / (curr_e + curr_r) if (curr_e + curr_r) != 0 else 0.0
        metrics["Sloan Accrual"] = (curr_p - curr_cfo) / curr_a if curr_a != 0 else 0.0
        
        # Altman Z-Score Proxy
        x1 = (curr_ca - curr_ol) / curr_a if curr_a != 0 else 0
        x2 = curr_r / curr_a if curr_a != 0 else 0
        x3 = curr_op / curr_a if curr_a != 0 else 0
        x4 = mcap_val / (curr_b + curr_ol) if (curr_b + curr_ol) != 0 else 0
        x5 = curr_s / curr_a if curr_a != 0 else 0
        z_score = (1.2 * x1) + (1.4 * x2) + (3.3 * x3) + (0.6 * x4) + (0.99 * x5)
        
        zone = "Safe" if z_score > 2.99 else ("Grey" if z_score >= 1.81 else "Distress")
        metrics["Altman Z-Score"] = f"{z_score:.2f} ({zone})"
        
        # Piotroski F-Score (out of 8 Proxy)
        f_score = 0
        if curr_p > 0: f_score += 1             # 1. Profitability
        if curr_cfo > 0: f_score += 1           # 2. Cash Flow
        if curr_p / curr_a > prev_p / (total_assets[-2] if len(total_assets)>1 else curr_a): f_score += 1 # 3. ROA YoY
        if curr_cfo > curr_p: f_score += 1      # 4. Accrual
        if curr_b <= prev_b: f_score += 1       # 5. Leverage Improvement
        if curr_ca/curr_ol > ( (receivables[-2]+inventory[-2]+cash_bank[-2])/other_liab[-2] if len(other_liab)>1 else 0): f_score += 1 # 6. Liquidity
        if (curr_op/curr_s) > (prev_op/prev_s if prev_s != 0 else 0): f_score += 1 # 7. OPM improvement
        if curr_s > prev_s: f_score += 1        # 8. Sales Growth
        
        metrics["Piotroski Score"] = f"{f_score}/8"
        metrics["OPM %"] = (curr_op / curr_s)

    except Exception as e:
        metrics["Status"] = f"Calculation Error: {e}"

    # Sanitization Range (Preserving formula workbook for zip)
    ds_formulas = wb_formulas['Data Sheet']
    for r in range(1, 15):
        for c in range(3, 13):
            cell = ds_formulas.cell(row=r, column=c)
            if cell.value is not None and not isinstance(cell.value, (int, float)):
                if not str(cell.value).replace('.', '', 1).isdigit():
                    cell.value = None

    processed_output = io.BytesIO()
    wb_formulas.save(processed_output)
    processed_output.seek(0)
    
    return processed_output, metrics

# ─────────────────────────────────────────────────────────────────────────────
# 3. STREAMLIT UI
# ─────────────────────────────────────────────────────────────────────────────

def main():
    st.title("⚖️ Institutional Quant Dashboard Engine")
    st.subheader("Batch Process Screener.in Files with Python Calculation Logic")

    uploaded_files = st.sidebar.file_uploader(
        "Upload Raw Screener Excel Files", 
        type=["xlsx"], 
        accept_multiple_files=True
    )
    
    if st.sidebar.button("🚀 Process & Generate Dashboard"):
        if not uploaded_files:
            st.warning("Please upload files first.")
            return

        all_metrics = []
        zip_buffer = io.BytesIO()
        
        with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED, False) as zip_file:
            progress = st.progress(0)
            
            for idx, up_file in enumerate(uploaded_files):
                processed_buffer, m = process_and_calculate(up_file.getvalue(), up_file.name)
                
                if m:
                    all_metrics.append(m)
                    zip_file.writestr(f"Processed_{up_file.name}", processed_buffer.getvalue())
                
                progress.progress((idx + 1) / len(uploaded_files))

            # Add master summary to ZIP
            df_summary = pd.DataFrame(all_metrics)
            summary_buffer = io.BytesIO()
            df_summary.to_excel(summary_buffer, index=False)
            zip_file.writestr("Master_Comparison_Report.xlsx", summary_buffer.getvalue())

        st.success("Analysis Complete!")

        # ── MASTER DASHBOARD DISPLAY ──
        df = pd.DataFrame(all_metrics)
        
        # Use columns if they exist
        display_cols = ["Company", "Market Cap", "Latest P/E", "Debt/Equity", "Sloan Accrual", "Altman Z-Score", "Piotroski Score", "OPM %"]
        df_display = df[[c for c in display_cols if c in df.columns]]

        # Formatting
        st.dataframe(
            df_display.style.format({
                "Market Cap": "₹ {:,.0f} Cr",
                "Latest P/E": "{:.1f}x",
                "Debt/Equity": "{:.2f}",
                "Sloan Accrual": "{:.1%}",
                "OPM %": "{:.1%}"
            }).background_gradient(subset=["Latest P/E"], cmap="RdYlGn_r")
        )

        st.download_button(
            label="📥 Download All Processed Files & Master Report (.zip)",
            data=zip_buffer.getvalue(),
            file_name=f"Quant_Batch_Report.zip",
            mime="application/zip"
        )

if __name__ == "__main__":
    main()
