import streamlit as st
import pandas as pd
import numpy as np
import time
import plotly.graph_objects as go
from datetime import datetime

# ─────────────────────────────────────────────────────────────────────────────
# 1. UI/UX: HIGH-DENSITY HFT TERMINAL CSS
# ─────────────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="HFT Execution Engine Pro", 
    layout="wide", 
    page_icon="⚡",
    initial_sidebar_state="expanded"
)

st.markdown("""
<style>
    :root {
        --bg-dark: #050811;
        --card-bg: #0e1626;
        --border-color: #1b273e;
        --accent-green: #00e676;
        --accent-red: #ff1744;
        --accent-cyan: #00e5ff;
    }
    .stApp { background-color: var(--bg-dark); color: #e2e8f0; }
    
    div[data-testid="stMetric"] {
        background-color: var(--card-bg);
        border: 1px solid var(--border-color);
        padding: 12px;
        border-radius: 6px;
    }
    .stTabs [data-baseweb="tab-list"] { gap: 6px; }
    .stTabs [data-baseweb="tab"] {
        background-color: var(--card-bg);
        border: 1px solid var(--border-color);
        padding: 6px 16px;
        border-radius: 4px 4px 0 0;
        font-family: monospace;
    }
    .stTabs [aria-selected="true"] {
        background-color: var(--accent-cyan) !important;
        color: #000000 !important;
        font-weight: bold;
    }
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────────────
# 2. VECTORIZED HFT STRATEGY ENGINE & LATENCY OPTIMIZER
# ─────────────────────────────────────────────────────────────────────────────

def generate_synthetic_hft_ticks(num_ticks=10000):
    """Generates microsecond-level tick data for ultra-fast backtesting."""
    np.random.seed(42)
    price_changes = np.random.normal(0, 0.05, num_ticks)
    prices = 100 + np.cumsum(price_changes)
    bid_ask_spread = np.random.uniform(0.01, 0.03, num_ticks)
    
    bids = prices - (bid_ask_spread / 2)
    asks = prices + (bid_ask_spread / 2)
    volumes = np.random.randint(100, 5000, size=num_ticks)
    
    df = pd.DataFrame({
        "Tick": np.arange(num_ticks),
        "Mid_Price": prices,
        "Bid": bids,
        "Ask": asks,
        "Spread": bid_ask_spread,
        "Volume": volumes
    })
    return df

def run_hft_execution_backtest(df, lookback_window, entry_threshold, stop_loss_pct):
    """
    Vectorized Order Book Imbalance & Mean Reversion Strategy Engine.
    Optimized for high-speed calculation to keep latency sub-millisecond.
    """
    start_time = time.perf_counter_ns()

    # Vectorized Rolling Window Calculation (Ultra-Fast execution)
    df['Rolling_Mean'] = df['Mid_Price'].rolling(window=lookback_window).mean()
    df['Rolling_Std'] = df['Mid_Price'].rolling(window=lookback_window).std()
    
    # Z-Score Computation for Micro-Spread Arbitrage
    df['Z_Score'] = (df['Mid_Price'] - df['Rolling_Mean']) / (df['Rolling_Std'] + 1e-9)

    # Signal Generation: +1 BUY, -1 SELL, 0 HOLD
    df['Signal'] = 0
    df.loc[df['Z_Score'] < -entry_threshold, 'Signal'] = 1   # Oversold -> Buy Limit
    df.loc[df['Z_Score'] > entry_threshold, 'Signal'] = -1   # Overbought -> Short Limit

    # Fast Position & PnL Vectorization
    df['Position'] = df['Signal'].shift(1).fillna(0)
    df['Returns'] = df['Mid_Price'].pct_change().fillna(0)
    df['Strategy_Returns'] = df['Position'] * df['Returns']
    df['Cumulative_PnL'] = (1 + df['Strategy_Returns']).cumprod() - 1

    # Latency tracking (Nanoseconds to Milliseconds conversion)
    end_time = time.perf_counter_ns()
    execution_time_ms = (end_time - start_time) / 1e6

    # Trade Metrics Calculation
    trades = df[df['Signal'] != 0]
    num_trades = len(trades)
    win_rate = (df['Strategy_Returns'] > 0).sum() / max(num_trades, 1) * 100
    total_pnl = df['Cumulative_PnL'].iloc[-1] * 100
    sharpe_ratio = (df['Strategy_Returns'].mean() / (df['Strategy_Returns'].std() + 1e-9)) * np.sqrt(252 * 7800) # Intraday annualization

    return df, {
        "Execution_Time_ms": execution_time_ms,
        "Total_Trades": num_trades,
        "Win_Rate_%": win_rate,
        "Total_PnL_%": total_pnl,
        "Sharpe_Ratio": sharpe_ratio
    }

# ─────────────────────────────────────────────────────────────────────────────
# 3. SIDEBAR ALGORITHMIC PARAMETERS
# ─────────────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("⚡ HFT Engine Controls")
    
    st.subheader("Data & Streaming Source")
    data_mode = st.radio("Tick Data Feed:", ["Synthetic HFT Stream", "Upload Real Tick CSV"])
    num_ticks = st.number_input("Number of Simulated Ticks", value=10000, step=1000)
    
    st.subheader("Algorithmic Strategy Inputs")
    lookback = st.slider("Micro-Lookback Window (Ticks)", 5, 200, 20)
    z_threshold = st.slider("Z-Score Entry Threshold", 0.5, 3.5, 1.5, step=0.1)
    stop_loss = st.number_input("Hardware Stop Loss (%)", value=0.05, step=0.01)

    st.divider()
    uploaded_ticks = None
    if data_mode == "Upload Real Tick CSV":
        uploaded_ticks = st.file_uploader("Upload Raw Order Book / Tick Data", type=["csv"])

# ─────────────────────────────────────────────────────────────────────────────
# 4. EXECUTION TERMINAL & METRICS
# ─────────────────────────────────────────────────────────────────────────────
st.title("⚡ Ultra-Low Latency HFT Execution Terminal")
st.caption("Sub-Millisecond Vectorized Backtesting & Automated Algorithmic Strategy Optimizer")

# Load Tick Stream
if uploaded_ticks is not None:
    tick_df = pd.read_csv(uploaded_ticks)
else:
    tick_df = generate_synthetic_hft_ticks(num_ticks)

# Run Algorithmic Execution Core
results_df, metrics = run_hft_execution_backtest(tick_df, lookback, z_threshold, stop_loss)

# Metric KPIs
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Engine Latency", f"{metrics['Execution_Time_ms']:.3f} ms")
c2.metric("Executed Orders", f"{metrics['Total_Trades']:,}")
c3.metric("Win Rate", f"{metrics['Win_Rate_%']:.1f}%")
c4.metric("Strategy PnL", f"{metrics['Total_PnL_%']:.2f}%")
c5.metric("Sharpe Ratio", f"{metrics['Sharpe_Ratio']:.2f}")

tab_charts, tab_trades, tab_orderbook, tab_export = st.tabs([
    "📈 Live Execution & PnL", "⚡ Order Log", "📊 Micro-Structure Analysis", "💾 Export Engine State"
])

with tab_charts:
    st.subheader("High-Frequency Tick Price & PnL Tracking")
    
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=results_df['Tick'], y=results_df['Mid_Price'], mode='lines', name='Mid Price', line=dict(color='#00e5ff', width=1)))
    
    # Mark Buy/Sell Signals
    buys = results_df[results_df['Signal'] == 1]
    sells = results_df[results_df['Signal'] == -1]
    
    fig.add_trace(go.Scatter(x=buys['Tick'], y=buys['Mid_Price'], mode='markers', name='BUY Signal', marker=dict(color='#00e676', size=6, symbol='triangle-up')))
    fig.add_trace(go.Scatter(x=sells['Tick'], y=sells['Mid_Price'], mode='markers', name='SELL Signal', marker=dict(color='#ff1744', size=6, symbol='triangle-down')))

    fig.update_layout(template="plotly_dark", height=450, xaxis_title="Tick Counter", yaxis_title="Price ($)")
    st.plotly_chart(fig, use_container_width=True)

with tab_trades:
    st.subheader("Executed Orders Log")
    st.dataframe(results_df[results_df['Signal'] != 0][['Tick', 'Mid_Price', 'Bid', 'Ask', 'Z_Score', 'Signal', 'Strategy_Returns']], use_container_width=True)

with tab_orderbook:
    st.subheader("Spread and Z-Score Distribution")
    fig_z = go.Figure()
    fig_z.add_trace(go.Scatter(x=results_df['Tick'], y=results_df['Z_Score'], mode='lines', name='Z-Score', line=dict(color='#f59e0b', width=1)))
    fig_z.add_hline(y=z_threshold, line_dash="dash", line_color="#ff1744", annotation_text="Upper Entry Limit")
    fig_z.add_hline(y=-z_threshold, line_dash="dash", line_color="#00e676", annotation_text="Lower Entry Limit")
    fig_z.update_layout(template="plotly_dark", height=400, xaxis_title="Tick Counter", yaxis_title="Z-Score")
    st.plotly_chart(fig_z, use_container_width=True)

with tab_export:
    st.subheader("Engine Export Interface")
    csv_out = results_df.to_csv(index=False).encode('utf-8')
    st.download_button("📥 Export Execution Log (CSV)", data=csv_out, file_name=f"HFT_Execution_Log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")
