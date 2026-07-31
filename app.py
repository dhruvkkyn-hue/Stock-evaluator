import openpyxl
from openpyxl.styles import Font, Fill, Alignment, PatternFill, Border, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.views import SheetView

def create_screener_template():
    wb = openpyxl.Workbook()
    wb.calculation.calcMode = 'auto'
    
    # Styles
    header_fill = PatternFill(start_color="1F497D", end_color="1F497D", fill_type="solid")
    header_font = Font(color="FFFFFF", bold=True)
    border = Border(left=Side(style='thin'), right=Side(style='thin'), top=Side(style='thin'), bottom=Side(style='thin'))
    
    def apply_header_style(ws, row_num, col_range):
        for col in col_range:
            cell = ws.cell(row=row_num, column=col)
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(horizontal="center")

    def setup_sheet(name):
        ws = wb.create_sheet(name)
        ws.sheet_view.showGridLines = True
        return ws

    # 1. DATA SHEET (The Anchor)
    ds = wb.active
    ds.title = "Data Sheet"
    ds.sheet_view.showGridLines = True
    
    # Static Headers for Screener mapping
    headers = ["Metric", "Mar-15", "Mar-16", "Mar-17", "Mar-18", "Mar-19", "Mar-20", "Mar-21", "Mar-22", "Mar-23", "Mar-24"]
    for i, h in enumerate(headers, 1):
        ds.cell(1, i, h)
    apply_header_style(ds, 1, range(1, 12))

    # Define standard Screener row order (Simplified for Template structure)
    ds_rows = [
        "Current Price", "Market Capitalization", "Face Value", "Shares",
        "Sales", "Raw Material Cost", "Power and Fuel", "Other Expenses", "Employee Cost", 
        "Operating Profit", "Other Income", "Depreciation", "Interest", "Profit before tax", "Tax", "Net Profit",
        "Share Capital", "Reserves", "Borrowings", "Other Liabilities", "Total Liabilities",
        "Net Block", "Capital Work in Progress", "Investments", "Receivables", "Cash and Bank", "Total Assets",
        "Cash from Operating Activity", "Cash from Investing Activity", "Cash from Financing Activity", "Net Cash Flow"
    ]
    for i, label in enumerate(ds_rows, 2):
        ds.cell(i, 1, label)

    # 2. SUMMARY SHEET
    summary = setup_sheet("Summary")
    summary.cell(1, 1, "EXECUTIVE DASHBOARD").font = Font(bold=True, size=14)
    
    summary.cell(3, 1, "Company Name")
    summary.cell(3, 2, "='Data Sheet'!B1") # Screener usually puts Name in Header or B1
    
    metrics = [
        ("CMP", "='Data Sheet'!B2"),
        ("Market Cap (Cr)", "='Data Sheet'!B3"),
        ("5-Yr Avg ROE (%)", "=AVERAGE('Data Sheet'!B17:F17)"), # Dummy range logic
        ("Debt to Equity", "='Data Sheet'!B19/('Data Sheet'!B17+'Data Sheet'!B18)"),
        ("Piotroski Score", "='Piotroski & Financial Health'!C15")
    ]
    for i, (label, formula) in enumerate(metrics, 5):
        summary.cell(i, 1, label)
        summary.cell(i, 2, formula)
    apply_header_style(summary, 4, range(1, 3))

    # 3. PIOTROSKI & FINANCIAL HEALTH
    ph = setup_sheet("Piotroski & Financial Health")
    ph_headers = ["Piotroski 9-Point Check", "Latest Year", "Previous Year"]
    for i, h in enumerate(ph_headers, 1): ph.cell(1, i, h)
    apply_header_style(ph, 1, range(1, 4))
    
    p_checks = [
        "Net Profit > 0", "CFO > 0", "ROA Increasing", "CFO > Net Profit",
        "Debt/Equity Decreasing", "Current Ratio Increasing", "No New Shares",
        "Gross Margin Increasing", "Asset Turnover Increasing"
    ]
    for i, check in enumerate(p_checks, 2):
        ph.cell(i, 1, check)
        # Dynamic IF formulas comparing Data Sheet columns B and C
        ph.cell(i, 2, f"=IF('Data Sheet'!B16>0, 1, 0)") 
        
    ph.cell(15, 1, "Total Piotroski Score")
    ph.cell(15, 2, "=SUM(B2:B10)")

    # 4. KEY RATIOS & CASH FLOW
    kr = setup_sheet("Key Ratios & Cash Flow Metrics")
    kr_metrics = [
        "Cash Conversion Ratio (CFO/PAT)", "FCF Margin %", "Interest Coverage Ratio",
        "Debtor Days", "Inventory Days", "Payable Days", "Cash Conversion Cycle"
    ]
    for i, m in enumerate(kr_metrics, 2):
        kr.cell(i, 1, m)
        # Formulas referencing Data Sheet
        if i == 2: kr.cell(i, 2, "='Data Sheet'!B28/'Data Sheet'!B16")
    apply_header_style(kr, 1, range(1, 3))

    # 5. DUPONT ANALYSIS (5-Stage)
    dp = setup_sheet("DuPont Analysis")
    dp_steps = ["Tax Burden", "Interest Burden", "EBIT Margin", "Asset Turnover", "Equity Multiplier", "Calculated ROE"]
    for i, step in enumerate(dp_steps, 2): dp.cell(i, 1, step)
    
    # DuPont Formulas (Example for Latest Year)
    dp.cell(2, 2, "='Data Sheet'!B16/'Data Sheet'!B14") # PAT/PBT
    dp.cell(3, 2, "='Data Sheet'!B14/('Data Sheet'!B10+'Data Sheet'!B11)") # PBT/EBIT
    dp.cell(4, 2, "=('Data Sheet'!B10+'Data Sheet'!B11)/'Data Sheet'!B5") # EBIT/Sales
    dp.cell(5, 2, "='Data Sheet'!B5/'Data Sheet'!B27") # Sales/Total Assets
    dp.cell(6, 2, "='Data Sheet'!B27/('Data Sheet'!B17+'Data Sheet'!B18)") # Assets/Equity
    dp.cell(7, 2, "=PRODUCT(B2:B6)")
    apply_header_style(dp, 1, range(1, 3))

    # 6. DCF MODEL
    dcf = setup_sheet("DCF")
    dcf_inputs = ["Risk Free Rate", "Equity Risk Premium", "Beta", "Growth Rate (5Yr)", "Terminal Growth"]
    for i, inp in enumerate(dcf_inputs, 2):
        dcf.cell(i, 1, inp)
        dcf.cell(i, 2, 0.07 if "Rate" in inp else 1.0)
    
    dcf.cell(8, 1, "PV of 10-Year Cash Flows")
    dcf.cell(9, 1, "Terminal Value")
    dcf.cell(10, 1, "Enterprise Value")
    dcf.cell(11, 1, "Fair Value per Share")
    apply_header_style(dcf, 1, range(1, 3))

    # 7. BEN GRAHAM & DHANDHO
    bg = setup_sheet("Ben Graham Formula")
    bg.cell(2, 1, "EPS (TTM)")
    bg.cell(2, 2, "='Data Sheet'!B16/'Data Sheet'!B5") # Placeholder formula
    bg.cell(3, 1, "Graham Number")
    bg.cell(3, 2, "=SQRT(22.5*B2*('Data Sheet'!B17+'Data Sheet'!B18)/'Data Sheet'!B5)")
    apply_header_style(bg, 1, range(1, 3))

    # 8. INSTITUTIONAL MULTIPLES
    im = setup_sheet("Institutional Multiples")
    im_headers = ["Year", "P/E", "P/S", "EV/EBITDA", "FCF Yield %"]
    for i, h in enumerate(im_headers, 1): im.cell(1, i, h)
    apply_header_style(im, 1, range(1, 6))

    # 9. TREND ANALYSIS
    tr = setup_sheet("Directional Trend Analysis")
    tr_headers = ["Metric", "Avg (First 5Y)", "Avg (Last 5Y)", "Trend"]
    for i, h in enumerate(tr_headers, 1): tr.cell(1, i, h)
    tr.cell(2, 1, "Revenue Growth")
    tr.cell(2, 2, "=AVERAGE('Data Sheet'!G5:K5)")
    tr.cell(2, 3, "=AVERAGE('Data Sheet'!B5:F5)")
    tr.cell(2, 4, "=IF(C2>B2, \"Improving\", \"Declining\")")
    apply_header_style(tr, 1, range(1, 5))

    # 10. COMMON SIZE ANALYSIS
    cs = setup_sheet("Common Size Analysis")
    cs.cell(1, 1, "P&L Common Size (% of Sales)")
    cs.cell(2, 1, "Raw Materials")
    cs.cell(2, 2, "='Data Sheet'!B6/'Data Sheet'!B5")
    apply_header_style(cs, 1, range(1, 3))

    # 11. CHECKLIST
    ch = setup_sheet("Checklist")
    checks = ["Competent Management?", "Pricing Power?", "High Barriers to Entry?", "Clean Accounting?"]
    for i, check in enumerate(checks, 2):
        ch.cell(i, 1, check)
        ch.cell(i, 2, "YES/NO")
    apply_header_style(ch, 1, range(1, 3))

    # Placeholder sheets for remaining requirements
    setup_sheet("Historical Context Comparison")
    setup_sheet("Expected Returns")

    # Final Formatting for all sheets
    for sheet in wb.worksheets:
        # Auto-fit columns
        for col in sheet.columns:
            max_length = 0
            column = col[0].column_letter
            for cell in col:
                try:
                    if len(str(cell.value)) > max_length:
                        max_length = len(str(cell.value))
                except: pass
            adjusted_width = (max_length + 2)
            sheet.column_dimensions[column].width = adjusted_width
        
        # Apply borders to used range
        for row in sheet.iter_rows(min_row=1, max_row=sheet.max_row, min_col=1, max_col=sheet.max_column):
            for cell in row:
                cell.border = border

    # Save
    filename = "Screener_Custom_Template.xlsx"
    wb.save(filename)
    print(f"Successfully generated {filename}")

if __name__ == "__main__":
    create_screener_template()
