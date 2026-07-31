import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

def create_screener_template():
    wb = openpyxl.Workbook()
    wb.calculation.calcMode = 'auto'
    
    # -------------------------------------------------------------------------
    # STYLES & COLOR PALETTES
    # -------------------------------------------------------------------------
    NAVY_HEADER_FILL = PatternFill(start_color="1F497D", end_color="1F497D", fill_type="solid")
    ACCENT_FILL = PatternFill(start_color="DCE6F1", end_color="DCE6F1", fill_type="solid")
    ALERT_FILL = PatternFill(start_color="F2DCDB", end_color="F2DCDB", fill_type="solid")
    
    WHITE_BOLD = Font(name="Calibri", size=11, color="FFFFFF", bold=True)
    DARK_BOLD = Font(name="Calibri", size=11, color="000000", bold=True)
    REGULAR_FONT = Font(name="Calibri", size=11)
    
    THIN_SIDE = Side(style='thin', color="D9D9D9")
    THICK_BOTTOM = Side(style='medium', color="1F497D")
    DOUBLE_BOTTOM = Side(style='double', color="000000")
    
    BORDER_STANDARD = Border(left=THIN_SIDE, right=THIN_SIDE, top=THIN_SIDE, bottom=THIN_SIDE)
    BORDER_TOTAL = Border(top=THIN_SIDE, bottom=DOUBLE_BOTTOM)

    def apply_header(ws, row_num, max_col):
        for col in range(1, max_col + 1):
            cell = ws.cell(row=row_num, column=col)
            cell.fill = NAVY_HEADER_FILL
            cell.font = WHITE_BOLD
            cell.alignment = Alignment(horizontal="center", vertical="center")

    def setup_sheet(name):
        ws = wb.create_sheet(name)
        ws.sheet_view.showGridLines = True
        return ws

    # -------------------------------------------------------------------------
    # 1. DATA SHEET (THE ANCHOR)
    # -------------------------------------------------------------------------
    ds = wb.active
    ds.title = "Data Sheet"
    ds.sheet_view.showGridLines = True
    
    years = ["Mar-15", "Mar-16", "Mar-17", "Mar-18", "Mar-19", "Mar-20", "Mar-21", "Mar-22", "Mar-23", "Mar-24"]
    ds_headers = ["Metric"] + years
    for i, h in enumerate(ds_headers, 1):
        ds.cell(1, i, h)
    apply_header(ds, 1, 11)

    ds_rows = [
        "Current Price", "Market Capitalization", "Face Value", "Number of Shares",
        "Sales", "Raw Material Cost", "Power and Fuel", "Other Expenses", "Employee Cost", 
        "Operating Profit", "Other Income", "Depreciation", "Interest", "Profit before tax", "Tax", "Net Profit",
        "Share Capital", "Reserves", "Borrowings", "Other Liabilities", "Total Liabilities",
        "Net Block", "Capital Work in Progress", "Investments", "Receivables", "Inventory", "Cash and Bank", "Total Assets",
        "Cash from Operating Activity", "Cash from Investing Activity", "Cash from Financing Activity", "Net Cash Flow", "Capital Expenditure"
    ]
    for row_idx, label in enumerate(ds_rows, 2):
        cell = ds.cell(row_idx, 1, label)
        cell.font = DARK_BOLD

    # -------------------------------------------------------------------------
    # 2. EXECUTIVE DASHBOARD & SUMMARY
    # -------------------------------------------------------------------------
    summary = setup_sheet("Summary")
    summary.cell(1, 1, "INSTITUTIONAL EXECUTIVE DASHBOARD").font = Font(bold=True, size=16, color="1F497D")
    
    summary_headers = ["Metric / Indicator", "Current Value", "Benchmark / Threshold", "Status"]
    for i, h in enumerate(summary_headers, 1):
        summary.cell(3, i, h)
    apply_header(summary, 3, 4)

    summary_rows = [
        ("Company Name", "='Data Sheet'!B1", "N/A", "N/A"),
        ("Current Price (CMP)", "='Data Sheet'!B2", "N/A", "N/A"),
        ("Market Capitalization (Cr)", "='Data Sheet'!B3", "N/A", "N/A"),
        ("Return on Equity (Latest %)", "=('Data Sheet'!B17/('Data Sheet'!B18+'Data Sheet'!B19))*100", ">= 15.0%", "=IF(B7>=15,\"✅ PASS\",\"❌ FAIL\")"),
        ("Debt to Equity (D/E)", "='Data Sheet'!B20/('Data Sheet'!B18+'Data Sheet'!B19)", "<= 0.50", "=IF(B8<=0.5,\"✅ PASS\",\"❌ FAIL\")"),
        ("Cash Realism (CFO / PAT)", "='Data Sheet'!B30/'Data Sheet'!B17", ">= 0.80", "=IF(B9>=0.8,\"✅ PASS\",\"❌ FAIL\")"),
        ("Piotroski F-Score", "='Piotroski & Financial Health'!C13", ">= 7", "=IF(B10>=7,\"✅ PASS\",\"❌ FAIL\")"),
        ("Beneish M-Score (Fraud Risk)", "='Piotroski & Financial Health'!C20", "< -1.78", "=IF(B11<-1.78,\"✅ SAFE\",\"⚠️ MANIPULATION RISK\")"),
        ("Intrinsic Value (DCF)", "='DCF Model'!B15", "Compare vs CMP", "=IF(B12>B5,\"🟢 UNDERVALUED\",\"🔴 OVERVALUED\")"),
    ]

    for row_idx, (m, f, b, s) in enumerate(summary_rows, 4):
        summary.cell(row_idx, 1, m).font = DARK_BOLD
        summary.cell(row_idx, 2, f).alignment = Alignment(horizontal="right")
        summary.cell(row_idx, 3, b).alignment = Alignment(horizontal="center")
        summary.cell(row_idx, 4, s).alignment = Alignment(horizontal="center")

    # -------------------------------------------------------------------------
    # 3. DUPONT ANALYSIS (5-STAGE HORIZONTAL 10-YEAR EXPANSION)
    # -------------------------------------------------------------------------
    dp = setup_sheet("DuPont Analysis")
    dp.cell(1, 1, "5-STAGE DUPONT ROE DECOMPOSITION (10-YEAR HISTORICAL)").font = Font(bold=True, size=14, color="1F497D")
    
    dp_headers = ["Metric / Component"] + years
    for i, h in enumerate(dp_headers, 1):
        dp.cell(3, i, h)
    apply_header(dp, 3, 11)

    dp_metrics = [
        ("1. Tax Burden (PAT / PBT)", "='Data Sheet'!{col}17/'Data Sheet'!{col}15"),
        ("2. Interest Burden (PBT / EBIT)", "='Data Sheet'!{col}15/'Data Sheet'!{col}11"),
        ("3. EBIT Margin (EBIT / Sales)", "='Data Sheet'!{col}11/'Data Sheet'!{col}6"),
        ("4. Asset Turnover (Sales / Assets)", "='Data Sheet'!{col}6/'Data Sheet'!{col}29"),
        ("5. Equity Multiplier (Assets / Equity)", "='Data Sheet'!{col}29/('Data Sheet'!{col}18+'Data Sheet'!{col}19)"),
        ("Calculated ROE (Product 1-5)", "=PRODUCT({col}4:{col}8)*100"),
        ("Direct ROE Check (%)", "=('Data Sheet'!{col}17/('Data Sheet'!{col}18+'Data Sheet'!{col}19))*100")
    ]

    for m_idx, (label, formula_template) in enumerate(dp_metrics, 4):
        dp.cell(m_idx, 1, label).font = DARK_BOLD if "ROE" in label else REGULAR_FONT
        for c_idx in range(2, 12):
            col_letter = get_column_letter(c_idx)
            cell_formula = formula_template.format(col=col_letter)
            cell = dp.cell(m_idx, c_idx, cell_formula)
            cell.alignment = Alignment(horizontal="right")

    # -------------------------------------------------------------------------
    # 4. FORENSICS & FINANCIAL HEALTH (PIOTROSKI & BENEISH M-SCORE)
    # -------------------------------------------------------------------------
    ph = setup_sheet("Piotroski & Financial Health")
    ph.cell(1, 1, "PIOTROSKI 9-POINT F-SCORE & BENEISH M-SCORE").font = Font(bold=True, size=14, color="1F497D")
    
    ph_headers = ["Piotroski Test", "Condition", "Score (1/0)"]
    for i, h in enumerate(ph_headers, 1):
        ph.cell(3, i, h)
    apply_header(ph, 3, 3)

    p_checks = [
        ("Positive Net Profit", "='Data Sheet'!B17 > 0"),
        ("Positive Operating Cash Flow", "='Data Sheet'!B30 > 0"),
        ("ROA Increasing", "=('Data Sheet'!B17/'Data Sheet'!B29) > ('Data Sheet'!C17/'Data Sheet'!C29)"),
        ("Cash Flow > Net Profit (Quality)", "='Data Sheet'!B30 > 'Data Sheet'!B17"),
        ("Long-Term Debt Decreasing", "='Data Sheet'!B20 < 'Data Sheet'!C20"),
        ("Current Ratio Increasing", "=('Data Sheet'!B26+'Data Sheet'!B27)/'Data Sheet'!B21 > ('Data Sheet'!C26+'Data Sheet'!C27)/'Data Sheet'!C21"),
        ("No Share Dilution", "='Data Sheet'!B18 <= 'Data Sheet'!C18"),
        ("Gross Margin Increasing", "=('Data Sheet'!B11/'Data Sheet'!B6) > ('Data Sheet'!C11/'Data Sheet'!C6)"),
        ("Asset Turnover Increasing", "=('Data Sheet'!B6/'Data Sheet'!B29) > ('Data Sheet'!C6/'Data Sheet'!C29)")
    ]

    for idx, (check_name, cond) in enumerate(p_checks, 4):
        ph.cell(idx, 1, check_name)
        ph.cell(idx, 2, f"={cond}")
        ph.cell(idx, 3, f"=IF({cond}, 1, 0)").alignment = Alignment(horizontal="center")

    ph.cell(13, 1, "TOTAL PIOTROSKI F-SCORE").font = DARK_BOLD
    ph.cell(13, 3, "=SUM(C4:C12)").font = DARK_BOLD

    # Beneish M-Score Section
    ph.cell(15, 1, "BENEISH M-SCORE EARNINGS MANIPULATION MODEL").font = Font(bold=True, size=12, color="1F497D")
    ph.cell(17, 1, "DSRI (Days Sales in Receivables Index)")
    ph.cell(17, 2, "=('Data Sheet'!B26/'Data Sheet'!B6)/('Data Sheet'!C26/'Data Sheet'!C6)")
    ph.cell(18, 1, "SGI (Sales Growth Index)")
    ph.cell(18, 2, "='Data Sheet'!B6/'Data Sheet'!C6")
    ph.cell(19, 1, "AQI (Asset Quality Index)")
    ph.cell(19, 2, "=(1-('Data Sheet'!B23+'Data Sheet'!B28)/'Data Sheet'!B29)/(1-('Data Sheet'!C23+'Data Sheet'!C28)/'Data Sheet'!C29)")
    
    ph.cell(20, 1, "Calculated Beneish M-Score").font = DARK_BOLD
    ph.cell(20, 2, "=-4.84 + (0.920*B17) + (0.528*B18) + (0.404*B19)").font = DARK_BOLD

    # -------------------------------------------------------------------------
    # 5. DCF VALUATION MODEL
    # -------------------------------------------------------------------------
    dcf = setup_sheet("DCF Model")
    dcf.cell(1, 1, "DISCOUNTED CASH FLOW (DCF) VALUATION ENGINE").font = Font(bold=True, size=14, color="1F497D")
    
    dcf_inputs = [
        ("Latest Free Cash Flow (Cr)", "='Data Sheet'!B30-'Data Sheet'!B34"),
        ("Risk-Free Rate (Rf)", 0.072),
        ("Equity Risk Premium (ERP)", 0.055),
        ("Beta", 1.0),
        ("Calculated WACC / Discount Rate", "=B4+(B5*B6)"),
        ("Stage 1 Growth Rate (Years 1-5)", 0.12),
        ("Stage 2 Growth Rate (Years 6-10)", 0.08),
        ("Terminal Growth Rate (g)", 0.04),
        ("Shares Outstanding (Cr)", "='Data Sheet'!B5")
    ]

    for idx, (label, val) in enumerate(dcf_inputs, 3):
        dcf.cell(idx, 1, label).font = DARK_BOLD if "WACC" in label else REGULAR_FONT
        dcf.cell(idx, 2, val)

    dcf_calc_headers = ["Year", "FCF Projection", "Discount Factor", "Present Value (PV)"]
    for i, h in enumerate(dcf_calc_headers, 1):
        dcf.cell(13, i, h)
    apply_header(dcf, 13, 4)

    for yr in range(1, 11):
        r = 13 + yr
        dcf.cell(r, 1, f"Year {yr}")
        if yr <= 5:
            dcf.cell(r, 2, f"=B{r-1}*(1+$B$8)" if yr > 1 else "=$B$3*(1+$B$8)")
        else:
            dcf.cell(r, 2, f"=B{r-1}*(1+$B$9)")
        
        dcf.cell(r, 3, f"=1/((1+$B$7)^{yr})")
        dcf.cell(r, 4, f"=B{r}*C{r}")

    dcf.cell(25, 1, "PV of 10-Year Cash Flows").font = DARK_BOLD
    dcf.cell(25, 2, "=SUM(D14:D23)")
    
    dcf.cell(26, 1, "Terminal Value").font = DARK_BOLD
    dcf.cell(26, 2, "=(B23*(1+B10))/(B7-B10)")
    
    dcf.cell(27, 1, "PV of Terminal Value").font = DARK_BOLD
    dcf.cell(27, 2, "=B26/((1+B7)^10)")
    
    dcf.cell(28, 1, "Total Enterprise Intrinsic Value").font = DARK_BOLD
    dcf.cell(28, 2, "=B25+B27")
    
    dcf.cell(29, 1, "Intrinsic Fair Value Per Share").font = DARK_BOLD
    dcf.cell(29, 2, "=B28/B11").font = Font(bold=True, size=12, color="1F497D")

    # -------------------------------------------------------------------------
    # 6. BEN GRAHAM & DHANDHO INTRINSIC VALUE
    # -------------------------------------------------------------------------
    bg = setup_sheet("Ben Graham Formula")
    bg.cell(1, 1, "BEN GRAHAM & DHANDHO INTRINSIC VALUE MODEL").font = Font(bold=True, size=14, color="1F497D")
    
    bg_inputs = [
        ("TTM Net Profit (Cr)", "='Data Sheet'!B17"),
        ("Shares Outstanding (Cr)", "='Data Sheet'!B5"),
        ("Earnings Per Share (EPS)", "=B3/B4"),
        ("Book Value Per Share (BVPS)", "=('Data Sheet'!B18+'Data Sheet'!B19)/B4"),
        ("Expected 5-Year Growth Rate (g)", 0.10),
        ("AAA Corporate Bond Yield (Y)", 0.075),
        ("Graham Number", "=SQRT(22.5 * B5 * B6)"),
        ("Revised Graham Intrinsic Value", "=(B5 * (8.5 + (2 * (B7*100))) * 4.4) / (B8*100)")
    ]

    for idx, (label, val) in enumerate(bg_inputs, 3):
        bg.cell(idx, 1, label).font = DARK_BOLD if "Intrinsic" in label or "Graham Number" in label else REGULAR_FONT
        bg.cell(idx, 2, val)

    # -------------------------------------------------------------------------
    # AUTO-FIT & BORDER FORMATTING ACROSS ALL WORKSHEETS
    # -------------------------------------------------------------------------
    for sheet in wb.worksheets:
        for col in sheet.columns:
            max_len = 0
            col_letter = col[0].column_letter
            for cell in col:
                val_str = str(cell.value or '')
                if val_str.startswith('='):
                    max_len = max(max_len, 12)
                else:
                    max_len = max(max_len, len(val_str))
            sheet.column_dimensions[col_letter].width = max(max_len + 3, 12)

        for row in sheet.iter_rows(min_row=1, max_row=sheet.max_row, min_col=1, max_col=sheet.max_column):
            for cell in row:
                if cell.value is not None:
                    cell.border = BORDER_STANDARD

    filename = "Screener_Custom_Template.xlsx"
    wb.save(filename)
    print(f"Successfully generated {filename}")

if __name__ == "__main__":
    create_screener_template()
