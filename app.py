import streamlit as st
import pandas as pd
import numpy as np
import io
import zipfile
import plotly.express as px
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
    .status-pass {
        background-color: rgba(16, 185, 129, 0.15);
        color: #10b981;
        padding: 4px 10px;
        border-radius: 4px;
        font-weight: 700;
        border: 1px solid #10b981;
    }
    .status-fail {
        background-color: rgba(239, 68, 68, 0.15);
        color: #ef4444;
        padding: 4px 10px;
        border-radius: 4px;
        font-weight: 700;
        border: 1px solid #ef4444;
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
# 2. HARDWARE-AWARE FILE PARSER & SIGNAL CLEANER
# ─────────────────────────────────────────────────────────────────────────────

def strip_potentiostat_headers(file_bytes, filename):
    """Detects and strips equipment metadata lines (BioLogic, Gamry, CHI, Autolab)."""
    text = file_bytes.decode('utf-8', errors='ignore')
    lines = text.splitlines()
    
    start_line = 0
    for idx, line in enumerate(lines[:100]): # Scan first 100 lines for header end
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
def process_echem_file(file_bytes, filename, settings):
    """Core electrochemistry engine: Peak finding, smoothing, Randles & noise analysis."""
    try:
        if filename.endswith('.csv') or filename.endswith('.txt') or filename.endswith('.mpt'):
            df = strip_potentiostat_headers(file_bytes, filename)
        else:
            df = pd.read_excel(io.BytesIO(file_bytes))

        # Column identification
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
            "df": df
        }

        # Voltammetry Path (CV/LSV)
        if v_col and i_col:
            out["Type"] = "Voltammetry (CV/LSV)"
            out["v_col"] = v_col
            out["i_col"] = i_col

            df[v_col] = pd.to_numeric(df[v_col], errors='coerce')
            df[i_col] = pd.to_numeric(df[i_col], errors='coerce')
            df.dropna(subset=[v_col, i_col], inplace=True)

            raw_i = df[i_col].values
            v_vals = df[v_col].values

            # Signal Smoothing (Savitzky-Golay)
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

            # Noise / Signal Integrity
            residual = raw_i - proc_i
            noise = np.std(residual) if np.std(residual) > 0 else 1e-12
            snr = np.mean(np.abs(proc_i)) / noise

            out.update({
                "I_pa": ipa, "I_pc": ipc, "E_pa": epa, "E_pc": epc,
                "Delta_Ep": delta_ep, "Peak_Span": span_i, "SNR": snr
            })

            # Pass/Fail Verification Logic
            if span_i < settings["min_span"]:
                out["Status"] = "FAIL"
                out["Flags"].append("Low Faradaic Current Response")
            if delta_ep > settings["max_dep"]:
                out["Status"] = "FAIL"
                out["Flags"].append("Sluggish Kinetics (High ΔEp)")
            if snr < settings["min_snr"]:
                out["Status"] = "FAIL"
                out["Flags"].append("Excessive Instrumentation Noise")

        # Impedance Spectroscopy Path (EIS)
        elif zr_col and zi_col:
            out["Type"] = "EIS (Impedance)"
            out["zr_col"] = zr_col
            out["zi_col"] = zi_col

            df[zr_col] = pd.to_numeric(df[zr_col], errors='coerce')
            df[zi_col] = pd.to_numeric(df[zi_col], errors='coerce')
            df.dropna(subset=[zr_col, zi_col], inplace=True)

            zr = df[zr_col].values
            zi = np.abs(df[zi_col].values) # -Z'' normalized to positive

            rs = zr.min() # Solution Resistance approx at high freq
            rct = zr.max() - rs # Charge Transfer Resistance footprint

            out.update({"Rs": rs, "Rct": rct})

            if rct > settings["max_rct"]:
                out["Status"] = "FAIL"
                out["Flags"].append("High Charge Transfer Resistance (Rct)")

        else:
            out["Status"] = "FAIL"
            out["Flags"].append("Column Mapping Error (Potential/Current/Z not found)")

        return out

    except Exception as e:
        return {"Filename": filename, "Status": "ERROR", "Flags": [str(e)], "Type": "Unknown", "df": None}

# ─────────────────────────────────────────────────────────────────────────────
# 3. INTERACTIVE CONTROL SIDEBAR
# ─────────────────────────────────────────────────────────────────────────────

with st.sidebar:
    st.header("⚡ Hardware & Threshold Controls")
    
    st.subheader("Voltammetry Tolerances")
    min_span = st.number_input("Min Peak-to-Peak Current Span (A)", value=1e-5, format="%.6f")
    max_dep = st.number_input("Max Peak Splitting ΔEp (V)", value=0.150, step=0.010)
    min_snr = st.slider("Minimum Signal-to-Noise (SNR)", 2.0, 100.0, 10.0)
    
    st.subheader("EIS Tolerances")
    max_rct = st.number_input("Max Permissible Rct (Ω)", value=500.0, step=50.0)

    st.subheader("Signal Preprocessing")
    smooth_sig = st.checkbox("Apply Savitzky-Golay Filtering", value=True)
    prominence = st.number_input("Peak Sensitivity Prominence", value=1e-6, format="%.7f")

    st.divider()
    uploads = st.file_uploader("Upload Electrochemical Sweeps", type=["csv", "txt", "mpt", "xlsx"], accept_multiple_files=True)

st.title("⚡ Electrochemical Quality Terminal")
st.caption("Automated Batch Diagnostics for Cyclic Voltammetry, LSV, and Impedance Spectroscopy")

settings = {
    "min_span": min_span, "max_dep": max_dep, "min_snr": min_snr,
    "max_rct": max_rct, "smooth": smooth_sig, "prominence": prominence
}

# ─────────────────────────────────────────────────────────────────────────────
# 4. PROCESSING AND MULTI-VIEW DASHBOARD
# ─────────────────────────────────────────────────────────────────────────────

if uploads:
    runs = []
    zip_bytes = io.BytesIO()

    for up in uploads:
        res = process_echem_file(up.getvalue(), up.name, settings)
        runs.append(res)

    summary_data = []
    for r in runs:
        summary_data.append({
            "Filename": r["Filename"],
            "Type": r["Type"],
            "Status": r["Status"],
            "I_pa (A)": f"{r['I_pa']:.3e}" if r['Type'].startswith("Volt") else "N/A",
            "ΔEp (V)": f"{r['Delta_Ep']:.3f}" if r['Type'].startswith("Volt") else "N/A",
            "SNR": f"{r['SNR']:.1f}" if r['Type'].startswith("Volt") else "N/A",
            "Rct (Ω)": f"{r['Rct']:.2f}" if r['Type'].startswith("EIS") else "N/A",
            "Anomalies": ", ".join(r["Flags"]) if r["Flags"] else "None"
        })

    summary_df = pd.DataFrame(summary_data)

    # Top KPI Row
    total_runs = len(runs)
    passed_runs = sum(1 for r in runs if r["Status"] == "PASS")
    failed_runs = sum(1 for r in runs if r["Status"] == "FAIL")

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Batch Count", total_runs)
    col2.metric("Passed Spec", passed_runs)
    col3.metric("Failed Spec", failed_runs, delta_color="inverse")
    col4.metric("Yield Rate", f"{(passed_runs/total_runs)*100:.1f}%")

    tab_summary, tab_overlay, tab_single, tab_export = st.tabs([
        "📋 QC Inspection Table", "📈 Multi-Curve Overlay", "🔍 Single-Curve Diagnostics", "💾 Export & Reports"
    ])

    with tab_summary:
        st.subheader("Batch Quality Overview")
        st.dataframe(
            summary_df.style.map(
                lambda v: 'background-color: rgba(16, 185, 129, 0.2); color: #10b981; font-weight: bold;' if v == 'PASS' 
                else ('background-color: rgba(239, 68, 68, 0.2); color: #ef4444; font-weight: bold;' if v == 'FAIL' else ''),
                subset=['Status']
            ), use_container_width=True
        )

    with tab_overlay:
        st.subheader("Multi-Run Visual Comparison")
        fig_over = go.Figure()

        for r in runs:
            if r["df"] is not None:
                df_curr = r["df"]
                if r["Type"].startswith("Volt"):
                    y_plot = df_curr["I_Filtered"] if "I_Filtered" in df_curr.columns else df_curr[r["i_col"]]
                    fig_over.add_trace(go.Scatter(x=df_curr[r["v_col"]], y=y_plot, mode='lines', name=r["Filename"]))
                    fig_over.update_layout(xaxis_title="Potential (V)", yaxis_title="Current (A)")
                elif r["Type"].startswith("EIS"):
                    fig_over.add_trace(go.Scatter(x=df_curr[r["zr_col"]], y=-df_curr[r["zi_col"]], mode='lines+markers', name=r["Filename"]))
                    fig_over.update_layout(xaxis_title="Z' (Ω)", yaxis_title="-Z'' (Ω)")

        fig_over.update_layout(template="plotly_dark", height=500)
        st.plotly_chart(fig_over, use_container_width=True)

    with tab_single:
        selected_file = st.selectbox("Select Curve for Deep Analysis:", [r["Filename"] for r in runs if r["df"] is not None])
        target = next(r for r in runs if r["Filename"] == selected_file)
        
        df_t = target["df"]
        fig_single = go.Figure()

        if target["Type"].startswith("Volt"):
            fig_single.add_trace(go.Scatter(x=df_t[target["v_col"]], y=df_t[target["i_col"]], mode='lines', name='Raw Signal', line=dict(color='#475569', width=1)))
            if "I_Filtered" in df_t.columns:
                fig_single.add_trace(go.Scatter(x=df_t[target["v_col"]], y=df_t["I_Filtered"], mode='lines', name='Filtered Signal (S-G)', line=dict(color='#10b981', width=2)))

            # Mark Anodic and Cathodic Peaks
            fig_single.add_trace(go.Scatter(x=[target["E_pa"]], y=[target["I_pa"]], mode='markers', marker=dict(color='#f59e0b', size=12), name='Epa (Anodic)'))
            fig_single.add_trace(go.Scatter(x=[target["E_pc"]], y=[target["I_pc"]], mode='markers', marker=dict(color='#ef4444', size=12), name='Epc (Cathodic)'))
            fig_single.update_layout(xaxis_title="Potential (V)", yaxis_title="Current (A)")

        elif target["Type"].startswith("EIS"):
            fig_single.add_trace(go.Scatter(x=df_t[target["zr_col"]], y=-df_t[target["zi_col"]], mode='lines+markers', name='Nyquist Arc', line=dict(color='#3b82f6')))
            fig_single.update_layout(xaxis_title="Z' (Ω)", yaxis_title="-Z'' (Ω)")

        fig_single.update_layout(template="plotly_dark", title=f"Run Analysis — {selected_file}")
        st.plotly_chart(fig_single, use_container_width=True)

    with tab_export:
        st.subheader("Generate Audit Documents")
        csv_rep = summary_df.to_csv(index=False).encode('utf-8')
        st.download_button("📥 Download Quality Summary (CSV)", data=csv_rep, file_name=f"Echem_QC_{datetime.now().strftime('%Y%m%d')}.csv")

else:
    st.info("👋 Upload CSV, TXT (BioLogic/Gamry exports), or Excel files to run automated quality checks.")
