import streamlit as st
import pandas as pd
import numpy as np
import io
import plotly.graph_objects as go
from scipy.signal import find_peaks, savgol_filter
from datetime import datetime

# ─────────────────────────────────────────────────────────────────────────────
# 1. UI/UX: HIGH-DENSITY LABORATORY TERMINAL CSS
# ─────────────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="EChem Quality Terminal Pro", 
    layout="wide", 
    page_icon="⚡",
    initial_sidebar_state="expanded"
)

st.markdown("""
<style>
    :root {
        --bg-dark: #090d16;
        --card-bg: #111726;
        --border-color: #1f293d;
        --accent-emerald: #10b981;
        --accent-blue: #3b82f6;
        --accent-red: #ef4444;
        --accent-amber: #f59e0b;
    }
    .stApp { background-color: var(--bg-dark); color: #cbd5e1; }
    
    div[data-testid="stMetric"] {
        background-color: var(--card-bg);
        border: 1px solid var(--border-color);
        padding: 14px;
        border-radius: 8px;
    }
    .stTabs [data-baseweb="tab-list"] { gap: 8px; }
    .stTabs [data-baseweb="tab"] {
        background-color: var(--card-bg);
        border: 1px solid var(--border-color);
        padding: 8px 18px;
        border-radius: 6px 6px 0 0;
    }
    .stTabs [aria-selected="true"] {
        background-color: var(--accent-emerald) !important;
        color: #ffffff !important;
    }
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────────────
# 2. PHARMACOPOEIA BASELINE DATABASE
# ─────────────────────────────────────────────────────────────────────────────
PHARMA_DATABASE = {
    "Acetaminophen (Paracetamol)": {
        "E_target": 0.52,        # Target Oxidation Voltage (V)
        "E_tol": 0.10,           # Voltage tolerance window (+/- V)
        "slope_m": 1.25e-4,      # Calibration curve slope (A per mg/mL)
        "intercept_b": 1.50e-6,  # Calibration curve intercept (A)
        "default_label_conc": 10.0, # Nominal test conc (mg/mL)
        "usp_min_potency": 90.0  # USP pass threshold (%)
    },
    "Ascorbic Acid (Vitamin C)": {
        "E_target": 0.35,
        "E_tol": 0.08,
        "slope_m": 8.50e-5,
        "intercept_b": 1.10e-6,
        "default_label_conc": 5.0,
        "usp_min_potency": 90.0
    },
    "Dopamine Hydrochloride": {
        "E_target": 0.22,
        "E_tol": 0.05,
        "slope_m": 3.10e-4,
        "intercept_b": 5.00e-7,
        "default_label_conc": 2.0,
        "usp_min_potency": 95.0
    }
}

# ─────────────────────────────────────────────────────────────────────────────
# 3. PARSER, SIGNAL CLEANER & ANALYTICS ENGINE
# ─────────────────────────────────────────────────────────────────────────────
def strip_potentiostat_headers(file_bytes, filename):
    """Strips hardware header lines from BioLogic, Gamry, CHI, Metrohm Autolab."""
    text = file_bytes.decode('utf-8', errors='ignore')
    lines = text.splitlines()
    
    start_line = 0
    for idx, line in enumerate(lines[:100]):
        line_l = line.lower()
        if any(key in line_l for key in ['potential', 'ewe', 'voltage', 'zreal', 'z\'', 'current']):
            if not line_l.startswith('#') and not line_l.startswith(';') and not line_l.startswith('biologic'):
                start_line = idx
                break

    clean_csv_str = "\n".join(lines[start_line:])
    return pd.read_csv(io.StringIO(clean_csv_str))

def find_col(df, options):
    """Fuzzy column matcher."""
    for col in df.columns:
        c_clean = str(col).lower().replace("_", " ").replace("-", " ").strip()
        if any(o in c_clean for o in options):
            return col
    return None

@st.cache_data(show_spinner=False)
def process_echem_file(file_bytes, filename, settings, drug_profile, target_conc):
    try:
        if filename.endswith('.csv') or filename.endswith('.txt') or filename.endswith('.mpt'):
            df = strip_potentiostat_headers(file_bytes, filename)
        else:
            df = pd.read_excel(io.BytesIO(file_bytes))

        v_col = find_col(df, ['potential', 'ewe', 'voltage', 'v'])
        i_col = find_col(df, ['current', 'i', 'amp', 'ma', 'ua', 'a'])
        zr_col = find_col(df, ['zreal', "z'", 'z_real', 'real'])
        zi_col = find_col(df, ['zimag', "z''", '-z\'\'', 'z_imag', 'imag'])

        out = {
            "Filename": filename,
            "Type": "Unknown",
            "Status": "PASS",
            "Flags": [],
            "I_pa": 0.0, "I_pc": 0.0, "E_pa": 0.0, "E_pc": 0.0,
            "Delta_Ep": 0.0, "SNR": 0.0, "Rs": 0.0, "Rct": 0.0,
            "Potency_%": 0.0, "Measured_Conc": 0.0,
            "df": df
        }

        # Voltammetry Path (CV/LSV)
        if v_col and i_col:
            out["Type"] = "Voltammetry (CV/LSV)"
            out["v_col"], out["i_col"] = v_col, i_col

            df[v_col] = pd.to_numeric(df[v_col], errors='coerce')
            df[i_col] = pd.to_numeric(df[i_col], errors='coerce')
            df.dropna(subset=[v_col, i_col], inplace=True)

            raw_i = df[i_col].values
            v_vals = df[v_col].values

            # Signal Filtering
            if len(raw_i) > 15 and settings["smooth"]:
                win = min(15, len(raw_i) - (1 - len(raw_i) % 2))
                proc_i = savgol_filter(raw_i, window_length=max(5, win), polyorder=2)
            else:
                proc_i = raw_i

            df["I_Filtered"] = proc_i

            # Peak identification
            pos_p, _ = find_peaks(proc_i, prominence=settings["prominence"])
            neg_p, _ = find_peaks(-proc_i, prominence=settings["prominence"])

            ipa = proc_i[pos_p].max() if len(pos_p) > 0 else proc_i.max()
            ipc = proc_i[neg_p].min() if len(neg_p) > 0 else proc_i.min()

            epa = v_vals[np.where(proc_i == ipa)[0][0]] if len(v_vals) > 0 else 0.0
            epc = v_vals[np.where(proc_i == ipc)[0][0]] if len(v_vals) > 0 else 0.0

            delta_ep = abs(epa - epc)
            span_i = ipa - ipc

            # Signal-to-Noise Ratio
            residual = raw_i - proc_i
            noise = np.std(residual) if np.std(residual) > 0 else 1e-12
            snr = np.mean(np.abs(proc_i)) / noise

            # Expiration Quantification Engine
            spec = PHARMA_DATABASE[drug_profile]
            calc_conc = max(0.0, (ipa - spec["intercept_b"]) / spec["slope_m"])
            potency_pct = (calc_conc / target_conc) * 100.0

            out.update({
                "I_pa": ipa, "I_pc": ipc, "E_pa": epa, "E_pc": epc,
                "Delta_Ep": delta_ep, "Peak_Span": span_i, "SNR": snr,
                "Potency_%": potency_pct, "Measured_Conc": calc_conc
            })

            # Pass/Fail Assessment
            if potency_pct < spec["usp_min_potency"]:
                out["Status"] = "FAIL (EXPIRED / SUB-POTENT)"
                out["Flags"].append(f"Potency ({potency_pct:.1f}%) < USP standard ({spec['usp_min_potency']}%)")
            if span_i < settings["min_span"]:
                out["Status"] = "FAIL (LOW RESPONSE)"
                out["Flags"].append("Low Faradaic current response")
            if snr < settings["min_snr"]:
                out["Flags"].append("High signal noise")

        # EIS Path
        elif zr_col and zi_col:
            out["Type"] = "EIS (Impedance)"
            out["zr_col"], out["zi_col"] = zr_col, zi_col

            df[zr_col] = pd.to_numeric(df[zr_col], errors='coerce')
            df[zi_col] = pd.to_numeric(df[zi_col], errors='coerce')
            df.dropna(subset=[zr_col, zi_col], inplace=True)

            zr = df[zr_col].values
            zi = np.abs(df[zi_col].values)

            rs = zr.min()
            rct = zr.max() - rs
            out.update({"Rs": rs, "Rct": rct})

            if rct > settings["max_rct"]:
                out["Status"] = "FAIL (HIGH RESISTANCE)"
                out["Flags"].append("Charge transfer resistance exceeded limit")

        else:
            out["Status"] = "ERROR"
            out["Flags"].append("Column structure not recognized")

        return out

    except Exception as e:
        return {"Filename": filename, "Status": "ERROR", "Flags": [str(e)], "Type": "Unknown", "df": None}

# ─────────────────────────────────────────────────────────────────────────────
# 4. SIDEBAR CONTROLS
# ─────────────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("💊 Medicine Target Settings")
    drug_choice = st.selectbox("Target Drug Compound:", list(PHARMA_DATABASE.keys()))
    default_c = PHARMA_DATABASE[drug_choice]["default_label_conc"]
    label_conc = st.number_input("Labeled Concentration (mg/mL):", value=default_c, min_value=0.1)

    st.header("⚡ Hardware & Signal Settings")
    min_span = st.number_input("Min Peak Span (A)", value=1e-6, format="%.7f")
    max_dep = st.number_input("Max ΔEp Splitting (V)", value=0.150, step=0.010)
    min_snr = st.slider("Min Signal-to-Noise Ratio", 2.0, 100.0, 10.0)
    max_rct = st.number_input("Max EIS Rct (Ω)", value=500.0)
    smooth_sig = st.checkbox("Apply Noise Filter (S-G)", value=True)
    prominence = st.number_input("Peak Prominence", value=1e-7, format="%.8f")

    st.divider()
    uploads = st.file_uploader("Upload Potentiostat Sweeps", type=["csv", "txt", "mpt", "xlsx"], accept_multiple_files=True)

# ─────────────────────────────────────────────────────────────────────────────
# 5. DASHBOARD TERMINAL
# ─────────────────────────────────────────────────────────────────────────────
st.title("⚡ Electrochemical Medicine Quality & Expiration Terminal")
st.caption("Automated API Quantification, Potency Verification, and Signal Diagnostics")

settings = {
    "min_span": min_span, "max_dep": max_dep, "min_snr": min_snr,
    "max_rct": max_rct, "smooth": smooth_sig, "prominence": prominence
}

if uploads:
    runs = [process_echem_file(u.getvalue(), u.name, settings, drug_choice, label_conc) for u in uploads]

    summary_data = [{
        "Filename": r["Filename"],
        "Type": r["Type"],
        "Status": r["Status"],
        "Potency (%)": f"{r['Potency_%']:.1f}%" if r["Type"].startswith("Volt") else "N/A",
        "Active Conc (mg/mL)": f"{r['Measured_Conc']:.2f}" if r["Type"].startswith("Volt") else "N/A",
        "E_pa (V)": f"{r['E_pa']:.3f}" if r["Type"].startswith("Volt") else "N/A",
        "SNR": f"{r['SNR']:.1f}" if r["Type"].startswith("Volt") else "N/A",
        "Flags": ", ".join(r["Flags"]) if r["Flags"] else "None"
    } for r in runs]

    summary_df = pd.DataFrame(summary_data)

    # Top KPI Metrics
    total = len(runs)
    passed = sum(1 for r in runs if r["Status"] == "PASS")
    failed = total - passed

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Batches Tested", total)
    c2.metric("Valid / Potent Batches", passed)
    c3.metric("Expired / Failed", failed, delta_color="inverse")
    c4.metric("Batch Pass Rate", f"{(passed/total)*100:.1f}%")

    tab_summary, tab_overlay, tab_single, tab_export = st.tabs([
        "📋 QC Audit Table", "📈 Batch Overlay Plot", "🔍 Peak Diagnostics", "💾 Export Reports"
    ])

    with tab_summary:
        st.subheader("Pharmaceutical Audit Overview")
        st.dataframe(summary_df, use_container_width=True)

    with tab_overlay:
        st.subheader("Multi-Run Curve Overlay")
        fig_over = go.Figure()
        for r in runs:
            if r["df"] is not None and r["Type"].startswith("Volt"):
                y_p = r["df"]["I_Filtered"] if "I_Filtered" in r["df"].columns else r["df"][r["i_col"]]
                fig_over.add_trace(go.Scatter(x=r["df"][r["v_col"]], y=y_p, mode='lines', name=r["Filename"]))
        fig_over.update_layout(template="plotly_dark", xaxis_title="Potential (V)", yaxis_title="Current (A)", height=500)
        st.plotly_chart(fig_over, use_container_width=True)

    with tab_single:
        selected = st.selectbox("Select Sweep to Inspect:", [r["Filename"] for r in runs if r["df"] is not None])
        target = next(r for r in runs if r["Filename"] == selected)
        df_t = target["df"]

        fig_s = go.Figure()
        if target["Type"].startswith("Volt"):
            fig_s.add_trace(go.Scatter(x=df_t[target["v_col"]], y=df_t[target["i_col"]], mode='lines', name='Raw Signal', line=dict(color='#475569')))
            if "I_Filtered" in df_t.columns:
                fig_s.add_trace(go.Scatter(x=df_t[target["v_col"]], y=df_t["I_Filtered"], mode='lines', name='Filtered Signal', line=dict(color='#10b981', width=2)))
            fig_s.add_trace(go.Scatter(x=[target["E_pa"]], y=[target["I_pa"]], mode='markers+text',
                                       text=[f"Potency: {target['Potency_%']:.1f}%"], textposition="top center",
                                       marker=dict(color='#ef4444', size=12), name='Anodic Peak'))
            fig_s.update_layout(xaxis_title="Potential (V)", yaxis_title="Current (A)")

        fig_s.update_layout(template="plotly_dark", title=f"Diagnostics — {selected}")
        st.plotly_chart(fig_s, use_container_width=True)

    with tab_export:
        st.subheader("Export Results")
        csv_data = summary_df.to_csv(index=False).encode('utf-8')
        st.download_button("📥 Download Summary (CSV)", data=csv_data, file_name=f"Pharma_QC_{datetime.now().strftime('%Y%m%d')}.csv")
else:
    st.info("👈 Select a target compound from the sidebar and upload raw potentiostat files to run testing.")
