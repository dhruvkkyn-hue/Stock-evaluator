import pandas as pd
import numpy as np
import re

class InstitutionalStockEvaluator:
    def __init__(self, excel_path):
        self.path = excel_path
        self.data_sheet = pd.read_excel(excel_path, sheet_name='Data Sheet', header=None)
        self.is_financial_service = self._detect_business_model()
        self.metrics = {}
        self.results = {}
        
        # Plain English Translation Map
        self.translations = {
            "roe": "How efficiently management turns ₹100 of shareholder money into real profit.",
            "cfo_pat": "The 'Truth Test' checking if reported paper profits are turning into actual bank cash.",
            "de": "How heavily the business relies on borrowed loans versus its own money.",
            "equity_multiplier": "Whether return on equity is real performance or artificially boosted by debt.",
            "beneish": "An automated financial lie-detector scanning for suspicious accounting changes.",
            "margin_safety": "The discount price tag buffer protecting you against unexpected bad news."
        }

    def _safe_num(self, val):
        if pd.isna(val) or val == "" or val == "-": return 0.0
        if isinstance(val, (int, float)): return float(val)
        cleaned = re.sub(r'[^\d\.\-]', '', str(val))
        try: return float(cleaned)
        except: return 0.0

    def _fuzzy_get_row(self, keywords):
        """Searches Data Sheet for row labels using keyword arrays."""
        for pattern in keywords:
            mask = self.data_sheet.iloc[:, 0].str.contains(pattern, case=False, na=False, regex=True)
            if mask.any():
                row_data = self.data_sheet[mask].iloc[0, 1:]
                return np.array([self._safe_num(x) for x in row_data])
        return np.zeros(12) # Default empty series

    def _detect_business_model(self):
        labels = self.data_sheet.iloc[:, 0].astype(str).str.lower().values
        banking_keywords = ["interest earned", "advances", "deposits", "npa"]
        return any(any(k in label for k in banking_keywords) for label in labels)

    def ingest_raw_data(self):
        # Maps metric keys to fuzzy keyword search terms
        mapping = {
            "sales": [r"sales", r"revenue", r"interest earned", r"total income"],
            "ebit": [r"operating profit", r"ebit", r"operating income"],
            "pat": [r"net profit", r"pat", r"profit after tax"],
            "equity": [r"share capital", r"reserves", r"total equity"],
            "debt": [r"borrowings", r"total debt"],
            "cfo": [r"cash from operating", r"cfo"],
            "capex": [r"fixed assets purchased", r"capital expenditure"],
            "assets": [r"total assets"],
            "pbt": [r"profit before tax", r"pbt"],
            "depreciation": [r"depreciation"],
            "interest_exp": [r"interest", r"finance cost"]
        }
        for key, keywords in mapping.items():
            self.metrics[key] = self._fuzzy_get_row(keywords)

    def calculate_valuation_array(self):
        m = self.metrics
        latest_pat = m['pat'][-1]
        avg_g = 0.05 # Conservative growth assumption for DCF
        wacc = 0.12  # Standard WACC for Indian Midcaps
        
        # Graham Revised: V = [EPS * (8.5 + 2g) * 4.4] / Y (Yield assumed 7%)
        eps = latest_pat / 1.0 # Simplified for demo; ideally PAT/Shares
        self.results['graham_val'] = (eps * (8.5 + 2 * 5) * 4.4) / 7.0
        
        # CFO Reality Check
        self.results['cfo_pat_ratio'] = np.mean(m['cfo'][-3:]) / np.mean(m['pat'][-3:])
        
        # 5-Stage DuPont (Latest Year)
        pbt = m['pbt'][-1]
        ebit = m['ebit'][-1]
        equity = m['equity'][-1]
        sales = m['sales'][-1]
        assets = m['assets'][-1]
        
        self.results['dupont'] = {
            "tax_burden": m['pat'][-1] / pbt if pbt != 0 else 0,
            "int_burden": pbt / ebit if ebit != 0 else 0,
            "margin": ebit / sales if sales != 0 else 0,
            "turnover": sales / assets if assets != 0 else 0,
            "leverage": assets / equity if equity != 0 else 0
        }

    def generate_executive_summary(self):
        score = 0
        roe_latest = (self.metrics['pat'][-1] / self.metrics['equity'][-1]) * 100
        cfo_pat = self.results['cfo_pat_ratio']
        de = self.metrics['debt'][-1] / self.metrics['equity'][-1]
        
        if roe_latest >= 15: score += 25
        if cfo_pat >= 0.8: score += 20
        if de <= 0.5: score += 20
        
        print(f"🏆 BUFFETT/MUNGER QUALITY SCORE: {score}/100")
        print(f"ROE Insight: {self.translations['roe']}")
        print(f"Cash Insight: {self.translations['cfo_pat']}")
        # Additional logic for stance output...
