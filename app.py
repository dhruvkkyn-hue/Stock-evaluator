import json
import openpyxl
from openpyxl.styles import Alignment, Font
from openai import OpenAI

def find_value_by_label(sheet, label_query, offset_col=1):
    """
    Scans a sheet to find a label and returns the value in the adjacent cell.
    """
    for row in sheet.iter_rows():
        for cell in row:
            if cell.value and label_query.lower() in str(cell.value).lower():
                return sheet.cell(row=cell.row, column=cell.column + offset_col).value
    return "N/A"

def extract_workbook_metrics(file_path):
    wb = openpyxl.load_workbook(file_path, data_only=True)
    
    # 1. Access Sheets
    summary_ws = wb['Summary'] if 'Summary' in wb.sheetnames else None
    health_ws = wb['Piotroski & Financial Health'] if 'Piotroski & Financial Health' in wb.sheetnames else None
    trend_ws = wb['Directional Trend Analysis'] if 'Directional Trend Analysis' in wb.sheetnames else None
    intrinsic_ws = wb['Intrinsic Values'] if 'Intrinsic Values' in wb.sheetnames else summary_ws

    metrics = {
        "company_name": summary_ws['B1'].value if summary_ws else "Unknown",
        "market_data": {
            "cmp": find_value_by_label(summary_ws, "Current Price") if summary_ws else "N/A",
            "mcap": find_value_by_label(summary_ws, "Market Cap") if summary_ws else "N/A",
        },
        "financial_health": {
            "piotroski_f_score": find_value_by_label(health_ws or summary_ws, "Piotroski"),
            "altman_z_score": find_value_by_label(health_ws or summary_ws, "Altman Z"),
            "altman_zone": find_value_by_label(health_ws or summary_ws, "Zone"),
            "sloan_accrual": find_value_by_label(health_ws, "Sloan")
        },
        "valuation_models": {
            "dcf_fair_value": find_value_by_label(intrinsic_ws, "DCF"),
            "graham_number": find_value_by_label(intrinsic_ws, "Graham"),
            "dhandho_valuation": find_value_by_label(intrinsic_ws, "Dhandho"),
            "earnings_power_value": find_value_by_label(intrinsic_ws, "EPV")
        },
        "trends": {
            "revenue_trend": find_value_by_label(trend_ws, "Revenue Trend") if trend_ws else "N/A",
            "opm_trend": find_value_by_label(trend_ws, "Operating Margin") if trend_ws else "N/A",
            "roce_trend": find_value_by_label(trend_ws, "ROCE Trend") if trend_ws else "N/A"
        }
    }
    return wb, metrics

def get_llm_analysis(metrics_json, api_key):
    client = OpenAI(api_key=api_key)
    
    system_prompt = (
        "You are a Senior Equity Research Analyst. Analyze the provided company data JSON "
        "and generate a concise 3-bullet executive analysis. Use professional, objective language."
    )
    
    user_content = f"""
    DATA:
    {json.dumps(metrics_json, indent=2)}

    INSTRUCTIONS:
    Provide exactly 3 bullets:
    - Bullet 1: Valuation Gap (Compare CMP/MCap against the 4 intrinsic value models).
    - Bullet 2: Financial Health & Red Flags (Analyze Piotroski, Altman Zone, and Sloan ratio for accounting quality).
    - Bullet 3: Business Momentum (Synthesize the trends in Revenue, OPM, and ROCE).
    """

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content}
        ],
        temperature=0.2
    )
    return response.choices[0].message.content

def write_summary_to_excel(wb, analysis_text, output_path):
    ws = wb['Summary']
    
    # Header Styling
    target_cell = ws['A30']
    target_cell.value = "EXECUTIVE QUANTITATIVE SUMMARY"
    target_cell.font = Font(bold=True, size=12, color="0000FF")
    
    # Analysis Body
    summary_cell = ws['A31']
    summary_cell.value = analysis_text
    summary_cell.alignment = Alignment(wrap_text=True, vertical='top')
    
    # Merge cells for better reading
    ws.merge_cells('A31:H40')
    
    wb.save(output_path)
    print(f"Analysis successfully appended to {output_path}")

def run_equity_summary_engine(file_path, openai_api_key):
    print("Extracting metrics from workbook...")
    wb, metrics = extract_workbook_metrics(file_path)
    
    print("Generating LLM analysis...")
    analysis = get_llm_analysis(metrics, openai_api_key)
    
    print("Writing back to Excel...")
    write_summary_to_excel(wb, analysis, file_path)

# Example Usage:
# run_equity_summary_engine("Screener_Custom_Report.xlsx", "your-api-key-here")
