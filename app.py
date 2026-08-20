import streamlit as st
import pandas as pd
import numpy as np
import io
import zipfile
import plotly.express as px
import plotly.graph_objects as go
import traceback
from datetime import datetime
from scipy.signal import find_peaks

# ─────────────────────────────────────────────────────────────────────────────
# 1. UI/UX: INSTITUTIONAL ECHEM CSS INJECTION
# ─────────────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Electrochemical Quality Terminal", 
    layout="wide", 
    page_icon="⚡"
)

def inject_custom_css():
    st.markdown("""
    <style>
        :root {
            --bg-dark: #0e1117;
            --card-bg: #161b22;
            --border-color: #30363d;
            --text-main: #c9d1d9;
            --text-heading: #ffffff;
            --accent-emerald: #10b981;
            --accent-blue: #3b82f6;
            --accent-amber: #f59e0b;
            --accent-red: #ef4444;
        }
        .stApp { background-color: var(--bg-dark); color: var(--text-main); }
        
        div[data-testid="stMetric"] {
            background-color: var(--card-bg);
            border: 1px solid var(--border-color);
            padding: 18px;
            border-radius: 10px;
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.35);
        }
        
        h1, h2, h3, h4 { 
            color: var(--text-heading) !important; 
            font-family: 'Inter', system-ui, -apple-system, sans-serif;
            font-weight: 700;
        }
        .hero-title {
            font-size: 2.2rem;
            font-weight: 800;
            background: linear-gradient(90deg, #ffffff, #94a3b8);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            margin-bottom: 0.2rem;
        }
        .hero-subtitle { 
            color: #8b949e; 
            font-size: 1.05rem; 
            margin-bottom: 1.8rem; 
        }
        
        .stTabs [data-baseweb="tab-list"] { 
            gap: 10px; 
            border-bottom: 1px solid var(--border-color);
        }
        .stTabs [data-baseweb="tab"] {
            background-color: var(--card-bg);
            border: 1px solid var(--border-color);
            border-radius: 6px 6px 0px 0px;
            padding: 10px 24px;
            color: var(--text-main);
            font-weight: 600;
        }
        .stTabs [aria-selected="true"] {
            background-color: var(--accent-emerald) !important;
            color: #ffffff !important;
            border-color: var(--accent-emerald) !important;
        }
        
        .status-pass {
            background-color: rgba(16, 185, 129, 0.2);
            color: #10b981;
            padding: 4px 12px;
            border-radius: 6px;
            font-weight: 800;
            border: 1px solid #10b981;
            display: inline-block;
        }
        .status-fail {
            background-color: rgba(239, 68, 68, 0.2);
            color: #ef4444;
            padding: 4px 12px;
            border-radius: 6px;
            font-weight: 800;
            border: 1px solid #ef4444;
            display: inline-block;
        }
    </style>
    """, unsafe_allow_html=True)

inject_custom_css()

# ─────────────────────────────────────────────────────────────────────────────
# 2. ECHEM QUANT ENGINE: PARSING & SIGNAL ANALYTICS
# ─────────────────────────────────────────────────────────────────────────────

def detect_column(df, candidates):
    """Fuzzy column matcher for Potentiostat exports (Gamry, BioLogic, Autolab, etc.)."""
    for col in df.columns:
        clean = str(col).lower().replace("_", " ").replace("-", " ").strip()
        if any(c in clean for c in candidates):
            return col
    return None

@st.cache_data(show_spinner=False)
def parse_and_analyze_echem(file_bytes, filename, tolerance_settings):
    """
    Parses CV / EIS / LSV datasets, detects redox peaks, calculates 
    $\Delta E_p$, signal noise, and returns QC pass/fail status.
    """
    try:
        if filename.endswith(".csv"):
            df = pd.read_csv(io.BytesIO(file_bytes))
        else:
            df = pd.read_excel(io.BytesIO(file_bytes))

        v_col = detect_column(df, ["potential", "voltage", "ewe", "v"])
        i_col = detect_column(df, ["current", "i", "amp", "ma", "ua"])
        z_real_col = detect_column(df, ["zreal", "z'"])
        z_imag_col = detect_column(df, ["zimag", "-z''", "z''"])

        res = {
            "Filename": filename,
            "Type": "CV/Voltammetry" if (v_col and i_col) else ("EIS" if (z_real_col and z_imag_col) else "Unknown"),
            "Status": "PASS",
            "Flags": [],
            "Peak_Anodic_I": 0.0,
            "Peak_Cathodic_I": 0.0,
            "E_pa": 0.0,
            "E_pc": 0.0,
            "Delta_Ep": 0.0,
            "SNR": 0.0,
            "R_ct_Approx": 0.0
        }

        if v_col and i_col:
            df[v_col] = pd.to_numeric(df[v_col], errors='coerce')
            df[i_col] = pd.to_numeric(df[i_col], errors='coerce')
            df.dropna(subset=[v_col, i_col], inplace=True)

            i_vals = df[i_col].values
            v_vals = df[v_col].values

            # Anodic & Cathodic Peak Search
            pos_peaks, _ = find_peaks(i_vals, prominence=tolerance_settings["prominence"])
            neg_peaks, _ = find_peaks(-i_vals, prominence=tolerance_settings["prominence"])

            ipa = i_vals[pos_peaks].max() if len(pos_peaks) > 0 else i_vals.max()
            ipc = i_vals[neg_peaks].min() if len(neg_peaks) > 0 else i_vals.min()

            epa = v_vals[np.where(i_vals == ipa)[0][0]] if len(v_vals) > 0 else 0.0
            epc = v_vals[np.where(i_vals == ipc)[0][0]] if len(v_vals) > 0 else 0.0

            delta_ep = abs(epa - epc)
            peak_diff = ipa - ipc
            
            # Noise estimation via signal variance
            signal_mean = np.mean(np.abs(i_vals))
            noise = np.std(np.diff(i_vals))
            snr = safe_div(signal_mean, noise)

            res.update({
                "Peak_Anodic_I": ipa,
                "Peak_Cathodic_I": ipc,
                "Peak_to_Peak_I": peak_diff,
                "E_pa": epa,
                "E_pc": epc,
                "Delta_Ep": delta_ep,
                "SNR": snr,
                "V_col": v_col,
                "I_col": i_col
            })

            # Automated Quality Gates
            if peak_diff < tolerance_settings["min_peak_diff"]:
                res["Status"] = "FAIL"
                res["Flags"].append("Low Response Threshold")
            if delta_ep > tolerance_settings["max_delta_ep"]:
                res["Status"] = "FAIL"
                res["Flags"].append("Excessive Peak Splitting (Reversibility Drop)")
            if snr < tolerance_settings["min_snr"]:
                res["Status"] = "FAIL"
                res["Flags"].append("Low SNR / Signal Noise")

        elif z_real_col and z_imag_col:
            df[z_real_col] = pd.to_numeric(df[z_real_col], errors='coerce')
            df[z_imag_col] = pd.to_numeric(df[z_imag_col], errors='coerce')
            df.dropna(subset=[z_real_col, z_imag_col], inplace=True)
            
            r_ct = df[z_real_col].max() - df[z_real_col].min()
            res.update({
                "R_ct_Approx": r_ct,
                "Z_real_col": z_real_col,
                "Z_imag_col": z_imag_col
            })

            if r_ct > tolerance_settings["max_rct"]:
                res["Status"] = "FAIL"
                res["Flags"].append("High Charge Transfer Resistance (Rct)")

        else:
            res["Status"] = "FAIL"
            res["Flags"].append("Unrecognized Data Scheme")

        return res, df

    except Exception as e:
        return {
            "Filename": filename, "Status": "ERROR", "Flags": [str(e)],
            "Type": "Unknown", "Peak_Anodic_I": 0, "Peak_Cathodic_I": 0,
            "Delta_Ep": 0, "SNR": 0, "R_ct_Approx": 0
        }, None

def safe_div(n, d, default=0.0):
    try:
        return n / d if d != 0 else default
    except:
        return default

# ─────────────────────────────────────────────────────────────────────────────
# 3. INTERPRETATION & EXPORT ENGINE
# ─────────────────────────────────────────────────────────────────────────────

def dataframe_to_markdown_table(df_sub):
    headers = list(df_sub.columns)
    header_row = "| " + " | ".join(headers) + " |"
    sep_row = "| " + " | ".join(["---"] * len(headers)) + " |"
    data_rows = []
    for _, row in df_sub.iterrows():
        r_str = [str(val) for val in row.values]
        data_rows.append("| " + " | ".join(r_str) + " |")
    return "\n".join([header_row, sep_row] + data_rows)

def generate_echem_thesis(res, tier):
    st.subheader(f"⚡ Technical Diagnostic — {res['Filename']}")
    
    if res["Status"] == "PASS":
        st.markdown("<div class='status-pass'>🟢 QUALIFIED: Meets Electroanalytical Specs</div>", unsafe_allow_html=True)
    else:
        st.markdown("<div class='status-fail'>🔴 REJECTED: Out of Specification</div>", unsafe_allow_html=True)
        
    st.write("")
    c1, c2, c3 = st.columns(3)
    c1.metric("Anodic Peak Current ($I_{pa}$)", f"{res['Peak_Anodic_I']:.4e}")
    c2.metric("Peak Splitting ($\Delta E_p$)", f"{res['Delta_Ep']:.3f} V")
    c3.metric("Signal-to-Noise Ratio", f"{res['SNR']:.1f}")

    st.markdown("**🔍 Diagnostic Breakdown:**")
    if tier == "🌱 Operator":
        st.write(f"- **Current Peak:** The curve reached a top response of `{res['Peak_Anodic_I']:.2e}`.")
        st.write(f"- **Noise Quality:** Signal-to-noise is at `{res['SNR']:.1f}`.")
    elif tier == "📈 Lab Technologist":
        st.write(f"- **Reversibility Check:** Peak separation is $\Delta E_p = {res['Delta_Ep']:.3f}\text{{ V}}$. Lower value indicates faster electron transfer kinetics.")
        st.write(f"- **Identified Flags:** {', '.join(res['Flags']) if res['Flags'] else 'None'}")
    else:
        st.write(f"- **Kinetic Analysis:** Nernstian ideal behavior targets $\Delta E_p \sim 59/n\text{{ mV}}$. Observed splitting indicates transfer limits or uncompensated resistance ($R_u$).")
        st.write(f"- **R_ct Estimation:** Implied impedance footprint: `{res['R_ct_Approx']:.2f} \Omega`.")

# ─────────────────────────────────────────────────────────────────────────────
# 4. MAIN UI LAYOUT
# ─────────────────────────────────────────────────────────────────────────────

with st.sidebar:
    st.header("📂 Batch File Ingestion")
    uploads = st.file_uploader("Upload Potentiostat Runs (CSV/XLSX)", accept_multiple_files=True)
    st.divider()
    
    st.header("⚙️ Quality Control Thresholds")
    min_peak_diff = st.number_input("Min Peak-to-Peak Current Span", value=1e-5, format="%.6f")
    max_delta_ep = st.number_input("Max Peak Splitting ΔEp (V)", value=0.200, step=0.01)
    min_snr = st.slider("Minimum Acceptable SNR", 2.0, 100.0, 10.0)
    prominence = st.number_input("Peak Detection Prominence", value=1e-6, format="%.7f")
    max_rct = st.number_input("Max Charge Transfer Res Rct (Ω)", value=1000.0, step=50.0)
    
    st.divider()
    complexity = st.radio("Analytics Detail Level:", ["🌱 Operator", "📈 Lab Technologist", "🏛️ Electrochemical Scientist"])

st.markdown("<h1 class='hero-title'>⚡ Electrochemical Quality Terminal</h1>", unsafe_allow_html=True)
st.markdown(f"<p class='hero-subtitle'>Batch Voltammetry & Impedance Auditor — Mode: <b>{complexity}</b></p>", unsafe_allow_html=True)

tolerance_settings = {
    "min_peak_diff": min_peak_diff,
    "max_delta_ep": max_delta_ep,
    "min_snr": min_snr,
    "prominence": prominence,
    "max_rct": max_rct
}

if uploads:
    results = []
    raw_files = []
    
    for up in uploads:
        content = up.getvalue()
        res, parsed_df = parse_and_analyze_echem(content, up.name, tolerance_settings)
        if res:
            results.append((res, parsed_df))
            raw_files.append((up.name, content))

    if results:
        res_list = [r[0] for r in results]
        df_summary = pd.DataFrame(res_list)

        tab_matrix, tab_deep, tab_risk, tab_visual, tab_export = st.tabs([
            "📊 Quality Matrix", "🔍 Curve Deep-Dive", "🛡️ Kinetic / Signal Risk", "📈 Voltammetric Visuals", "📄 Export"
        ])

        with tab_matrix:
            st.subheader("Batch Inspection Output")
            display_cols = ["Filename", "Type", "Status", "Peak_Anodic_I", "Peak_Cathodic_I", "Delta_Ep", "SNR", "R_ct_Approx"]
            st.dataframe(
                df_summary[display_cols].style.map(
                    lambda v: 'color: #10b981; font-weight: bold;' if v == 'PASS' else ('color: #ef4444; font-weight: bold;' if v == 'FAIL' else ''),
                    subset=['Status']
                ), use_container_width=True
            )

        with tab_deep:
            selection = st.selectbox("Select Run for Deep-Dive:", df_summary["Filename"].unique())
            sel_tuple = next(r for r in results if r[0]["Filename"] == selection)
            generate_echem_thesis(sel_tuple[0], complexity)

        with tab_risk:
            st.subheader("🚨 Automated Failure Mode Flags")
            for r in res_list:
                with st.expander(f"Run: {r['Filename']} — Status: {r['Status']}"):
                    if r["Flags"]:
                        for flag in r["Flags"]:
                            st.error(f"Flagged: {flag}")
                    else:
                        st.success("Clean response signal — All parameters fall within established tolerances.")

        with tab_visual:
            c1, c2 = st.columns(2)
            with c1:
                selected_file = st.selectbox("Select Curve to Plot:", df_summary["Filename"].unique(), key="plot_select")
                target_tuple = next(r for r in results if r[0]["Filename"] == selected_file)
                meta, df_curve = target_tuple
                
                fig = go.Figure()
                if meta["Type"] == "CV/Voltammetry" and df_curve is not None:
                    fig.add_trace(go.Scatter(x=df_curve[meta["V_col"]], y=df_curve[meta["I_col"]], mode='lines', name='Voltammogram', line=dict(color='#10b981')))
                    fig.update_layout(title=f"Cyclic Voltammogram — {selected_file}", xaxis_title="Potential (V)", yaxis_title="Current (A)", template="plotly_dark")
                elif meta["Type"] == "EIS" and df_curve is not None:
                    fig.add_trace(go.Scatter(x=df_curve[meta["Z_real_col"]], y=-df_curve[meta["Z_imag_col"]], mode='lines+markers', name='Nyquist Plot', line=dict(color='#3b82f6')))
                    fig.update_layout(title=f"Nyquist Plot — {selected_file}", xaxis_title="Z' (Ω)", yaxis_title="-Z'' (Ω)", template="plotly_dark")
                
                st.plotly_chart(fig, use_container_width=True)

            with c2:
                fig2 = px.scatter(
                    df_summary, x="Delta_Ep", y="SNR", color="Status", 
                    size=np.abs(df_summary["Peak_Anodic_I"]) + 1e-9, 
                    hover_name="Filename", title="Signal Fidelity vs. Peak Splitting"
                )
                fig2.update_layout(template="plotly_dark")
                st.plotly_chart(fig2, use_container_width=True)

        with tab_export:
            st.subheader("📄 Generate Batch Quality Report")
            report_md = f"# ELECTROCHEMICAL BATCH QC REPORT\nMode: {complexity}\nGenerated: {datetime.now()}\n\n"
            report_md += dataframe_to_markdown_table(df_summary[["Filename", "Type", "Status", "Delta_Ep", "SNR"]])
            
            st.download_button("📥 Download Report (.md)", data=report_md, file_name=f"Echem_QC_Report_{datetime.now().strftime('%Y%m%d')}.md")
            
            zip_io = io.BytesIO()
            with zipfile.ZipFile(zip_io, 'w') as zf:
                for fname, content in raw_files: 
                    zf.writestr(f"Audited_{fname}", content)
            st.download_button("📥 Download Data Package (.zip)", data=zip_io.getvalue(), file_name="Echem_Batch_Data.zip")

else:
    st.info("👋 Upload potentiostat data files (CSV or Excel) to run batch automated screening.")
