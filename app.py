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
    page_title="Screener Batch Quant Engine",
    layout="wide",
    page_icon="📑"
)

# ─────────────────────────────────────────────────────────────────────────────
# 2. CORE QUANTITATIVE HELPERS (NON-AI)
# ─────────────────────────────────────────────────────────────────────────────

def to_float(val):
    """Cleans strings and converts to float for calculation/comparison."""
    if val is None or isinstance(val, (int, float)):
        return val
    try:
        # Remove currency symbols and commas
        s = str(val).replace(',', '').replace('₹', '').replace('Rs.', '').strip()
        # Handle percentages
        if '%' in s:
            return float(s.replace('%', '')) / 100
        return float(s)
    except:
        return None

def find_metric_in_ws(ws, label_regex, offset_col=1):
    """Searches a worksheet for a label and returns the adjacent value."""
    if not ws:
        return "N/A"
    for row in ws.iter_rows():
        for cell in row:
            if cell.value and re.search(label_regex, str(cell.value), re.IGNORECASE):
                return ws.cell(row=cell.row, column=cell.column + offset_col).value
    return "N/A"

# ─────────────────────────────────────────────────────────────────────────────
# 3. PROCESSING PIPELINE
# ─────────────────────────────────────────────────────────────────────────────

def process_screener_workbook(file_bytes, file_name):
    """
    Handles sanitization of raw data and extraction of calculated metrics.
    """
    # Load for both formula preservation and data extraction
    # We use io.BytesIO to keep everything in memory
    in_mem_file = io.BytesIO(file_bytes)
    
    # Step 1: Load Workbook
    # Note: data_only=False preserves formulas for the sanitized output
    # but we need data_only=True to extract the 'Calculated' values for the dashboard
    wb_formulas = openpyxl.load_workbook(in_mem_file, data_only=False)
    
    # Reload a copy to get the calculated values (Screener exports usually have cached values)
    in_mem_file.seek(0)
    wb_values = openpyxl.load_workbook(in_mem_file, data_only=True)
    
    # --- STEP A: DATA SANITIZATION ('Data Sheet') ---
    if 'Data Sheet' in wb_formulas.sheetnames:
        ds = wb_formulas['Data Sheet']
        # Requirements: Rows 1 to 14, Columns C (3) to L (12)
        for r in range(1, 15):
            for c in range(3, 13):
                cell = ds.cell(row=r, column=c)
                val = cell.value
                # If cell contains non-numeric text (excluding None and numeric types)
                if val is not None and not isinstance(val, (int, float)):
                    # Check if it's a string that doesn't look like a number
                    if not str(val).replace('.', '', 1).isdigit():
                        cell.value = None # Clear it to prevent float errors in Screener backend
    
    # --- STEP B: METRIC EXTRACTION FOR DASHBOARD ---
    # We pull from wb_values to get the results of the formulas
    metrics = {"File Name": file_name}
    
    # Define sheets to scan
    summary_ws = wb_values['Summary'] if 'Summary' in wb_values.sheetnames else None
    health_ws = wb_values['Piotroski & Financial Health'] if 'Piotroski & Financial Health' in wb_values.sheetnames else None
    intrinsic_ws = wb_values['Intrinsic Values'] if 'Intrinsic Values' in wb_values.sheetnames else summary_ws
    
    # Extraction Logic
    metrics["Company"] = find_metric_in_ws(summary_ws or wb_values['Data Sheet'], r"Company|Name", 1)
    metrics["MCap (Cr)"] = find_metric_in_ws(summary_ws, r"Market Cap", 1)
    
    # Health Metrics
    metrics["Piotroski F-Score"] = find_metric_in_ws(health_ws, r"Piotroski", 1)
    metrics["Altman Z-Score"] = find_metric_in_ws(health_ws, r"Altman Z", 1)
    metrics["Altman Zone"] = find_metric_in_ws(health_ws, r"Zone", 1)
    metrics["Sloan Accrual"] = find_metric_in_ws(health_ws, r"Sloan", 1)
    
    # Efficiency & Solvency
    metrics["D/E Ratio"] = find_metric_in_ws(summary_ws, r"Debt to equity", 1)
    metrics["ROE (5Yr)"] = find_metric_in_ws(summary_ws, r"Average return on equity 5Years", 1)
    
    # Valuation Multiples
    metrics["P/E"] = find_metric_in_ws(summary_ws, r"Price to Earning", 1)
    metrics["EV/EBITDA"] = find_metric_in_ws(summary_ws, r"EV / EBITDA", 1)
    
    # Valuation Spreads
    metrics["DCF Spread %"] = find_metric_in_ws(intrinsic_ws, r"DCF.*Spread|Spread.*DCF", 1)
    metrics["Graham Spread %"] = find_metric_in_ws(intrinsic_ws, r"Graham.*Spread", 1)

    # Save sanitized workbook to memory
    processed_output = io.BytesIO()
    wb_formulas.save(processed_output)
    processed_output.seek(0)
    
    return processed_output, metrics

# ─────────────────────────────────────────────────────────────────────────────
# 4. STREAMLIT UI & ORCHESTRATION
# ─────────────────────────────────────────────────────────────────────────────

def main():
    st.title("📑 Screener.in Batch Quant Engine")
    st.markdown("""
    **Standalone Workbook Processor**: Sanitize 'Data Sheet' inputs, preserve formula integrity, 
    and extract institutional metrics into a master dashboard.
    """)

    with st.sidebar:
        st.header("Upload Sector Batch")
        uploaded_files = st.file_uploader(
            "Select Screener.in Excel Files", 
            type=["xlsx"], 
            accept_multiple_files=True
        )
        process_btn = st.button("🚀 Process Batch", type="primary")

    if uploaded_files and process_btn:
        all_metrics = []
        processed_files_map = {} # Filename -> BytesIO
        
        progress_bar = st.progress(0)
        status_text = st.empty()

        for idx, uploaded_file in enumerate(uploaded_files):
            try:
                status_text.text(f"Processing: {uploaded_file.name}...")
                
                # Run Pipeline
                file_bytes = uploaded_file.getvalue()
                processed_buffer, file_metrics = process_screener_workbook(file_bytes, uploaded_file.name)
                
                all_metrics.append(file_metrics)
                processed_files_map[uploaded_file.name] = processed_buffer
                
                progress_bar.progress((idx + 1) / len(uploaded_files))
            except Exception as e:
                st.error(f"Failed to process {uploaded_file.name}: {e}")

        status_text.success("Batch Processing Complete!")

        # --- MASTER DASHBOARD ---
        if all_metrics:
            st.subheader("📊 Master Stock Comparison Dashboard")
            df = pd.DataFrame(all_metrics)
            
            # Formatting for display
            st.dataframe(df.style.highlight_max(axis=0, subset=["ROE (5Yr)"], color='lightgreen'))

            # --- ZIP EXPORT ---
            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED, False) as zip_file:
                # Add individual sanitized files
                for name, data in processed_files_map.items():
                    zip_file.writestr(f"Sanitized_{name}", data.getvalue())
                
                # Add Master Excel Summary
                master_summary_buffer = io.BytesIO()
                with pd.ExcelWriter(master_summary_buffer, engine='openpyxl') as writer:
                    df.to_excel(writer, index=False, sheet_name='Comparison_Summary')
                zip_file.writestr("Master_Stock_Comparison.xlsx", master_summary_buffer.getvalue())

            st.divider()
            st.download_button(
                label="📥 Download Processed Batch (.zip)",
                data=zip_buffer.getvalue(),
                file_name=f"Screener_Batch_{pd.Timestamp.now().strftime('%Y%m%d_%H%M')}.zip",
                mime="application/zip"
            )

    elif not uploaded_files:
        st.info("Waiting for files to be uploaded via the sidebar.")

if __name__ == "__main__":
    main()
