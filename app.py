import pandas as pd
import numpy as np
import re

class EliteResearchWorkstation:
    def __init__(self, file_path):
        self.file_path = file_path
        self.raw_data = None
        self.is_bank = False
        self.metrics = {}
        self.score_card = {"Moat": 0, "Cash": 0, "Debt": 0, "Forensic": 0, "Value": 0}
        
        # Plain English Translation Dictionary
        self.translations = {
            "roe": "How effectively management turns ₹100 of shareholder money into real profit.",
            "cfo_pat": "The truth-test checking if reported paper profits are turning into actual cash in the bank.",
            "sloan": "An accounting lie-detector checking whether earnings are real or stuck in uncollected bills.",
            "equity_multiplier": "Shows if returns are driven by business merit or artificially boosted by debt.",
            "graham_number": "The 'Fair Price' Benjamin Graham would pay based on earnings and book value.",
            "fcf": "The actual pocket money left for the business after paying for all maintenance and growth."
        }

    def load_and_sanitize(self):
        """Loads 'Data Sheet' and cleans non-numeric junk."""
        try:
            # Use openpyxl engine to read the raw strings
            df = pd.read_excel(self.file_path, sheet_name='Data Sheet', header=None)
            df = df.dropna(how='all', axis=0).dropna(how='all', axis=1)
            
            # Fuzzy match the label column
            df.iloc[:, 0] = df.iloc[:, 0].astype(str).str.lower().str.strip()
            self.raw_data = df
            
            # Industry Detection: Banks have 'Interest Earned' or 'Advances'
            labels = " ".join(df.iloc[:, 0].tolist())
            if "interest earned" in labels or "advances" in labels:
                self.is_bank = True
        except Exception as e:
            raise ValueError(f"CRITICAL: Failed to parse 'Data Sheet'. Ensure file is a Screener export. Error: {e}")

    def _get_row(self, keywords):
        """Dynamic Fuzzy Matching for Row Labels."""
        for kw in keywords:
            mask = self.raw_data.iloc[:, 0].str.contains(kw, na=False)
            if mask.any():
                # Extract numeric values, strip symbols, convert to float
                row = self.raw_data[mask].iloc[0, 1:]
                return np.array([self._clean_val(v) for v in row])
        return np.zeros(10) # Default to zero series if not found

    def _clean_val(self, val):
        if pd.isna(val) or val == "" or str(val).strip() in ["-", "—"]: return 0.0
        s = str(val).replace('₹', '').replace(',', '').replace('%', '').strip()
        try: return float(s)
        except: return 0.0

    def execute_pipeline(self):
        self.load_and_sanitize()
        
        # 1. Extraction (Keyword Arrays per directive)
        sales = self._get_row(["sales", "revenue", "interest earned", "total income"])
        pat = self._get_row(["net profit", "pat", "profit after tax"])
        ebit = self._get_row(["operating profit", "ebit", "operating income"])
        equity = self._get_row(["equity share capital", "reserves", "total equity"])
        debt = self._get_row(["borrowings", "total debt"])
        cfo = self._get_row(["cash from operating", "operating cash flow", "cfo"])
        capex = self._get_row(["capex", "capital expenditure", "purchase of fixed assets"])
        assets = self._get_row(["total assets"])
        pbt = self._get_row(["profit before tax", "pbt"])

        # Handle 0 division safety
        def safe_div(n, d): return np.divide(n, d, out=np.zeros_like(n), where=d!=0)

        # 2. Forensic & Cash Logic
        cfo_pat_ratio = safe_div(cfo, pat)
        sloan_ratio = safe_div((pat - cfo), assets)
        
        # 3. DuPont 5-Stage (Latest Year)
        tax_burden = pat[-1] / pbt[-1] if pbt[-1] != 0 else 0
        int_burden = pbt[-1] / ebit[-1] if ebit[-1] != 0 else 0
        ebit_margin = ebit[-1] / sales[-1] if sales[-1] != 0 else 0
        asset_turnover = sales[-1] / assets[-1] if assets[-1] != 0 else 0
        leverage = assets[-1] / equity[-1] if equity[-1] != 0 else 0
        roe = (pat[-1] / equity[-1]) * 100

        # 4. Valuation (Graham Number)
        graham_num = np.sqrt(max(0, 22.5 * pat[-1] * equity[-1])) # Simplified for aggregate Cr values

        # 5. Scoring Engine (100 Points)
        if roe >= 15: self.score_card["Moat"] = 25
        if cfo_pat_ratio[-1] >= 0.8: self.score_card["Cash"] = 20
        de_ratio = debt[-1] / equity[-1]
        if de_ratio <= 0.5: self.score_card["Debt"] = 20
        if abs(sloan_ratio[-1]) < 0.1: self.score_card["Forensic"] = 15
        
        total_score = sum(self.score_card.values())

        # 6. Output Narrative Generation
        self._print_report(total_score, roe, cfo_pat_ratio, de_ratio, sloan_ratio, graham_num)

    def _print_report(self, score, roe, cfo_pat, de, sloan, graham):
        stance = "🟢 STRONG BUY" if score >= 80 else "🟢 ACCUMULATE" if score >= 65 else "🟡 WATCHLIST" if score >= 50 else "🔴 AVOID"
        
        print(f"{'-'*78}")
        print(f"🏆 BUFFETT/MUNGER BUSINESS QUALITY SCORE: {score} / 100")
        print(f"ACTIONABLE STANCE: {stance}")
        print(f"{'-'*78}")
        print("\n📊 EXECUTIVE SUMMARY")
        print(f"- Industry Detected: {'Banking/NBFC' if self.is_bank else 'Manufacturing/Service'}")
        print(f"- Current ROE: {roe:.2f}% | Plain English: {self.translations['roe']}")
        print(f"- Cash Quality (CFO/PAT): {cfo_pat[-1]:.2f}x | Plain English: {self.translations['cfo_pat']}")
        
        print("\n🟢 CORE STRENGTHS")
        if roe >= 15: print(f"- Robust Capital Efficiency: Generating {roe:.2f}% on equity.")
        if cfo_pat[-1] >= 1: print("- High Earnings Quality: Company collects more cash than it reports as paper profit.")
        
        print("\n🔴 KEY RISKS & RED FLAGS")
        if de > 0.5: print(f"- High Leverage: Debt-to-Equity is {de:.2f}. Management is aggressive with borrowing.")
        if abs(sloan[-1]) > 0.1: print(f"- Accrual Warning: Sloan Ratio ({sloan[-1]:.2f}) suggests potential non-cash earnings inflation.")
        
        print("\n⚖️ VALUATION SUMMARY")
        print(f"- Graham Aggregate Valuation: ₹{graham:,.2f} Cr")
        print(f"- Plain English: {self.translations['graham_number']}")
        
        print("\n📋 RECOMMENDED EXECUTION STRATEGY")
        if stance.startswith("🟢"):
            print("- Staggered accumulation on market dips. Focus on holding for the full compounding cycle.")
        else:
            print("- Stay on the sidelines. Current risk-reward ratio does not favor the long-term investor.")
        print(f"{'-'*78}")

# Usage (Integration with your model/app)
# workstation = EliteResearchWorkstation("Stock_Export.xlsx")
# workstation.execute_pipeline()
