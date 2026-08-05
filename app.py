import streamlit as st
import pandas as pd
import openpyxl
import io
import zipfile
import re
import plotly.express as px

# ─────────────────────────────────────────────────────────────────────────────
# 1. CORE CONFIGURATION & SAFE MATH
# ─────────────────────────────────────────────────────────────────────────────
st.set_page_config(page_title="Institutional Equity Research Terminal", layout="wide", page_icon="⚖️")

def safe_float(val, default=0.0):
    if val is None: return default
    try:
        if isinstance(val, (int, float)): return float(val)
        s = str(val).replace(',', '').replace('₹', '').replace('Rs.', '').strip()
        if s.startswith('(') and s.endswith(')'): s = "-" + s[1:-1]
        return float(s)
    except: return default

def safe_div(n, d, default=0.0):
    try:
        n_f, d_f = float(n or 0), float(d or 0)
        return n_f / d_f if d_f != 0 else default
    except: return default

# ─────────────────────────────────────────────────────────────────────────────
# 2. HEURISTIC EXTRACTION ENGINE (CRASH-PROOF)
# ─────────────────────────────────────────────────────────────────────────────

def find_row_series(ws, keywords):
    kw_lower = [k.lower() for k in keywords]
    for row in ws.iter_rows(min_row=1, max_row=ws.max_row, min_col=1, max_col=2):
        label_a = str(row[0].value or "").strip().lower()
        label_b = str(row[1].value or "").strip().lower()
        combined = f"{label_a} {label_b}"
        if any(k in combined for k in kw_lower):
            row_idx = row[0].row
            vals = []
            for col_idx in range(2, ws.max_column + 1):
                val = safe_float(ws.cell(row=row_idx, column=col_idx).value, None)
                if val is not None: vals.append(val)
            return vals
    return []

def process_workbook(file_bytes, filename):
    try:
        wb = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True)
        ds_name = next((s for s in wb.sheetnames if "data sheet" in s.lower()), None)
        if not ds_name: return None, None
        ws = wb[ds_name]

        data_map = {
            "mcap": ["Market Capitalization", "Market Cap", "Mar Cap", "Current Market", "CMP"],
            "sales": ["Sales", "Revenue", "Total Revenue", "Interest Earned", "Income"],
            "op": ["Operating Profit", "EBITDA", "EBIT", "Operating Loss", "Financing Profit"],
            "pat": ["Net Profit", "Profit after tax", "PAT", "PAT for the year"],
            "debt": ["Borrowings", "Total Debt", "Long term borrowings", "Short term borrowings"],
            "liab": ["Other Liabilities", "Current Liabilities", "Total Liabilities"],
            "reserves": ["Reserves", "Retained Earnings", "Other Equity"],
            "equity": ["Equity Share Capital", "Share Capital", "Equity Capital"],
            "cfo": ["Cash from Operating", "Operating Cash Flow", "CFO", "Cash flow from operations"],
            "receivables": ["Receivables", "Trade Receivables", "Sundry Debtors"],
            "inventory": ["Inventory", "Stock", "Inventories"],
            "cash": ["Cash & Bank", "Cash Equivalents", "Bank Balance"],
            "interest": ["Interest", "Finance Costs", "Interest Expensed"]
        }

        # Extract latest year data
        cur = {k: find_row_series(ws, v)[-1] if find_row_series(ws, v) else 0.0 for k, v in data_map.items()}
        # Extract series for momentum
        series_map = {k: find_row_series(ws, v) for k, v in data_map.items()}

        total_eq = cur['equity'] + cur['reserves']
        total_assets = total_eq + cur['debt'] + cur['liab']
        
        res = {"Company": str(ws.cell(row=1, column=2).value).strip()}
        res["Market Cap"] = cur['mcap']
        res["Sales"] = cur['sales']
        res["Net Profit"] = cur['pat']
        res["CFO"] = cur['cfo']
        res["OPM %"] = safe_div(cur['op'], cur['sales']) * 100
        res["PE"] = safe_div(cur['mcap'], cur['pat'])
        res["D/E"] = safe_div(cur['debt'], total_eq)
        res["Sloan %"] = safe_div(cur['pat'] - cur['cfo'], total_assets) * 100
        res["EV/EBITDA"] = safe_div(cur['mcap'] + cur['debt'] - cur['cash'], cur['op'])
        
        # Altman Z-Score
        x1 = safe_div((cur['receivables'] + cur['inventory'] + cur['cash']) - cur['liab'], total_assets)
        x2 = safe_div(cur['reserves'], total_assets)
        x3 = safe_div(cur['op'], total_assets)
        x4 = safe_div(cur['mcap'], cur['debt'] + cur['liab'])
        x5 = safe_div(cur['sales'], total_assets)
        res["Altman Z"] = (1.2 * x1) + (1.4 * x2) + (3.3 * x3) + (0.6 * x4) + (0.99 * x5)
        res["Zone"] = "Safe" if res["Altman Z"] > 2.99 else "Grey" if res["Altman Z"] >= 1.81 else "Distress"

        # Piotroski F-Score (8-Point)
        f = 0
        if cur['pat'] > 0: f += 1
        if cur['cfo'] > 0: f += 1
        if cur['cfo'] > cur['pat']: f += 1
        if len(series_map['pat']) > 1 and safe_div(cur['pat'], total_assets) > safe_div(series_map['pat'][-2], total_assets): f += 1
        if cur['debt'] <= (series_map['debt'][-2] if len(series_map['debt']) > 1 else cur['debt']): f += 1
        if safe_div(cur['op'], cur['sales']) > safe_div(series_map['op'][-2] if len(series_map['op']) > 1 else 0, series_map['sales'][-2] if len(series_map['sales']) > 1 else 1): f += 1
        if len(series_map['sales']) > 1 and cur['sales'] > series_map['sales'][-2]: f += 1
        if total_assets > 0: f += 1
        res["Piotroski"] = f

        return res, file_bytes
    except Exception as e:
        st.error(f"Error parsing {filename}: {str(e)}")
        return None, None

# ─────────────────────────────────────────────────────────────────────────────
# 3. UI DASHBOARD & COMPARISON
# ─────────────────────────────────────────────────────────────────────────────

st.title("🏛️ Institutional Equity Terminal")
st.sidebar.header("Batch Processing")
up_files = st.sidebar.file_uploader("Upload Screener Excels", type="xlsx", accept_multiple_files=True)

if up_files:
    results = []
    zip_bytes = io.BytesIO()
    with zipfile.ZipFile(zip_bytes, 'w') as zf:
        for f in up_files:
            data, b_content = process_workbook(f.getvalue(), f.name)
            if data:
                results.append(data)
                zf.writestr(f"Processed_{f.name}", b_content)

    if results:
        df = pd.DataFrame(results)
        st.subheader("📋 Master Quantitative Matrix")
        st.dataframe(df.style.format({
            "Market Cap": "₹{:,.0f}", "Sales": "₹{:,.0f}", "Net Profit": "₹{:,.0f}",
            "PE": "{:.1f}x", "D/E": "{:.2f}", "Sloan %": "{:.2f}%", "Altman Z": "{:.2f}", "OPM %": "{:.1f}%"
        }).background_gradient(subset=["Piotroski"], cmap="RdYlGn"))

        # ─────────────────────────────────────────────────────────────────────
        # 4. STRATEGIC DEEP-DIVE (2 TO 5 COMPANIES)
        # ─────────────────────────────────────────────────────────────────────
        st.divider()
        st.header("🕵️ Strategic Multi-Company Deep-Dive")
        
        selected_companies = st.multiselect(
            "Select Companies for Deep-Dive (Choose 2 to 5):",
            options=df["Company"].unique(),
            default=df["Company"].unique()[:min(5, len(df))]
        )

        if len(selected_companies) < 2:
            st.info("Please select at least 2 companies to enable side-by-side comparative narrative.")
        elif len(selected_companies) > 5:
            st.warning("Deep-Dive analysis is optimized for a maximum of 5 companies. Please reduce selection.")
        else:
            comp_data = [df[df["Company"] == name].iloc[0] for name in selected_companies]
            
            # --- Paragraph Analysis Engine ---
            st.subheader("📊 Institutional Metric Interpretations")

            # 1. Market Cap
            mcap_text = "The selected cohort represents a diverse spectrum of market presence. "
            for c in comp_data:
                size = "Large-Cap (Institutional safe-haven)" if c['Market Cap'] > 20000 else "Mid-Cap (Growth-focused)" if c['Market Cap'] > 5000 else "Small-Cap (High-risk/High-reward)"
                mcap_text += f"**{c['Company']}** operates as a {size} with a capitalization of ₹{c['Market Cap']:,.0f} Cr. "
            mcap_text += "Larger caps in this group offer superior liquidity and defensive moats, whereas the smaller entities present potential for high-growth runaway performance but require closer scrutiny of their volatility profiles."
            st.markdown(f"**Market Scale & Institutional Reach:** {mcap_text}")

            # 2. Valuation
            val_text = "Valuation dispersion across the group suggests varying market expectations. "
            for c in comp_data:
                val_text += f"**{c['Company']}** is currently priced at a P/E of {c['PE']:.1f}x and EV/EBITDA of {c['EV/EBITDA']:.1f}x. "
            val_text += "A high multiple generally signals that investors are pricing in aggressive future growth or dominant quality, while lower multiples may either represent a significant 'Margin of Safety' or a potential 'Value Trap' where fundamental deterioration is already being anticipated by the market."
            st.markdown(f"**Valuation & Market Expectations:** {val_text}")

            # 3. OPM
            opm_text = "Operating margins provide a window into the core pricing power and structural efficiencies of these businesses. "
            for c in comp_data:
                opm_text += f"**{c['Company']}** maintains an OPM of {c['OPM %']:.1f}%. "
            opm_text += "Companies with higher margins in this cohort demonstrate superior cost-structure resilience and pricing power, allowing them to better absorb inflationary pressures in raw materials without sacrificing bottom-line integrity."
            st.markdown(f"**Pricing Power & Cost Resilience:** {opm_text}")

            # 4. Sloan Ratio
            sloan_text = "Earnings quality is scrutinized through the Sloan Accrual Ratio, distinguishing between 'Accounting Profits' and 'Cash Profits.' "
            for c in comp_data:
                quality = "High-quality cash conversion" if abs(c['Sloan %']) < 10 else "Aggressive non-cash accruals"
                sloan_text += f"**{c['Company']}** reports a Sloan Ratio of {c['Sloan %']:.2f}%, indicating {quality}. "
            sloan_text += "Ratios exceeding the 10% threshold flag a potential mismatch between reported PAT and actual Operating Cash Flow, often driven by inventory buildup or uncollected receivables."
            st.markdown(f"**Earnings Quality & Cash Realism:** {sloan_text}")

            # 5. Altman Z
            alt_text = "Solvency analysis via the Altman Z-Score evaluates the balance sheet's ability to withstand stressed market environments. "
            for c in comp_data:
                alt_text += f"**{c['Company']}** is categorized in the **{c['Zone']} Zone** (Score: {c['Altman Z']:.2f}). "
            alt_text += "Entities in the 'Safe' zone exhibit robust durability against bankruptcy, while those in 'Distress' or 'Grey' zones should be monitored for credit-side volatility and liquidity constraints."
            st.markdown(f"**Solvency & Balance Sheet Durability:** {alt_text}")

            # 6. Piotroski
            pio_text = "Operational momentum is measured by the Piotroski F-Score, which evaluates year-over-year trending in profitability and liquidity. "
            for c in comp_data:
                status = "Exceptional momentum" if c['Piotroski'] >= 7 else "Average stability" if c['Piotroski'] >= 4 else "Declining fundamental strength"
                pio_text += f"**{c['Company']}** scores {c['Piotroski']}/8, signaling {status}. "
            pio_text += "High scores indicate that the business is improving its internal efficiencies and reducing financial risk simultaneously."
            st.markdown(f"**Internal Operational Momentum:** {pio_text}")

            # 7. Debt/Equity
            debt_text = "The capital structure determines how these companies will navigate interest rate cycles. "
            for c in comp_data:
                risk = "highly conservative" if c['D/E'] < 0.3 else "moderately geared" if c['D/E'] < 1.0 else "aggressive financial leverage"
                debt_text += f"**{c['Company']}** maintains a D/E of {c['D/E']:.2f}, representing a {risk} structure. "
            debt_text += "In a rising interest rate environment, companies with low D/E ratios are best positioned to maintain net margins, while those with high leverage face increased pressure on earnings power."
            st.markdown(f"**Capital Structure & Interest Rate Sensitivity:** {debt_text}")

            # ─────────────────────────────────────────────────────────────────────
            # 5. INDIVIDUAL PROS & CONS
            # ─────────────────────────────────────────────────────────────────────
            st.divider()
            st.subheader("🚦 Individual Strategic Health-Check")
            pc_cols = st.columns(len(comp_data))
            for i, c in enumerate(comp_data):
                with pc_cols[i]:
                    st.markdown(f"#### {c['Company']}")
                    # Pros
                    st.markdown("**🟢 Strengths**")
                    if c['Piotroski'] >= 7: st.write("- Elite operational momentum.")
                    if c['Altman Z'] > 2.99: st.write("- Fortress balance sheet safety.")
                    if c['D/E'] < 0.4: st.write("- Low financial gearing risk.")
                    if c['OPM %'] > 20: st.write("- Dominant pricing power.")
                    if abs(c['Sloan %']) < 5: st.write("- Highly conservative accounting.")
                    
                    # Cons
                    st.markdown("**🔴 Drawbacks**")
                    if c['PE'] > 60: st.write("- Stretched valuation; zero safety.")
                    if c['D/E'] > 1.5: st.write("- Elevated interest rate sensitivity.")
                    if c['Zone'] == "Distress": st.write("- Serious insolvency risk signals.")
                    if c['OPM %'] < 10: st.write("- Thin margins; low cushion.")
                    if c['Sloan %'] > 15: st.write("- High non-cash accrual risk.")

            # ─────────────────────────────────────────────────────────────────────
            # 6. ALLOCATION MATRIX
            # ─────────────────────────────────────────────────────────────────────
            st.divider()
            st.subheader("⚖️ Scenario-Based Allocation Matrix")
            m1, m2 = st.columns(2)
            with m1:
                st.markdown("#### 🛡️ Bear Market / Rate Hike Scenario")
                safe_lead = sorted(comp_data, key=lambda x: (-x['Altman Z'], x['D/E']))[0]
                st.write(f"In this environment, **{safe_lead['Company']}** is the preferred allocation. Its high Altman Z-Score and low D/E ratio provide the strongest defensive shield against credit contraction and rising borrowing costs.")
            with m2:
                st.markdown("#### 🚀 Bull Market / Growth Expansion Scenario")
                momentum_lead = sorted(comp_data, key=lambda x: (-x['Piotroski'], x['PE']))[0]
                st.write(f"In a high-growth environment, **{momentum_lead['Company']}** is positioned for maximum capture. Its superior Piotroski score reflects internal efficiency gains that typically translate into aggressive EPS expansion during market upswings.")

else:
    st.info("👋 Welcome. Please upload Screener.in Excel files in the sidebar to generate the institutional deep-dive.")
