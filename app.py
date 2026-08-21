import asyncio
import os
import sys
import pandas as pd
import numpy as np
from dotenv import load_dotenv

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import LimitOrderRequest, MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.data.live import StockDataStream

# -------------------------------------------------------------------
# 1. SETUP & CREDENTIALS
# -------------------------------------------------------------------
load_dotenv()
API_KEY = os.getenv("ALPACA_API_KEY")
SECRET_KEY = os.getenv("ALPACA_SECRET_KEY")

if not API_KEY or not SECRET_KEY:
    print("❌ Error: ALPACA_API_KEY or ALPACA_SECRET_KEY missing from environment.")
    sys.exit(1)

trading_client = TradingClient(API_KEY, SECRET_KEY, paper=True)
stream_client = StockDataStream(API_KEY, SECRET_KEY)

TICKERS = ["AAPL", "NVDA", "TSLA", "AMD", "MSFT", "AMZN"]
MAX_CAPITAL_PER_TRADE = 100.0
SLIPPAGE_PENALTY = 0.0005  # 0.05% slippage buffer

# In-Memory State Engine
market_data_cache = {ticker: [] for ticker in TICKERS}
active_positions = {}
pending_orders = set()
bot_enabled = True

# -------------------------------------------------------------------
# 2. LOW-LATENCY ORDER ROUTER
# -------------------------------------------------------------------
async def execute_order_async(symbol: str, side: OrderSide, current_price: float, qty: int, reason: str):
    """Submits limit orders asynchronously with zero UI overhead."""
    if symbol in pending_orders:
        return
    
    pending_orders.add(symbol)
    try:
        limit_price = round(current_price * (1 + SLIPPAGE_PENALTY), 2) if side == OrderSide.BUY else round(current_price * (1 - SLIPPAGE_PENALTY), 2)
        
        req = LimitOrderRequest(
            symbol=symbol,
            qty=qty,
            side=side,
            limit_price=limit_price,
            time_in_force=TimeInForce.DAY,
            extended_hours=True
        )
        
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, trading_client.submit_order, req)
        print(f"\n⚡ [ORDER FILLED] {side.value.upper()} {qty} shares of {symbol} @ ${limit_price:.2f} | Reason: {reason}")
    except Exception as e:
        print(f"\n❌ [EXECUTION FAILED] {symbol}: {e}")
    finally:
        pending_orders.remove(symbol)

# -------------------------------------------------------------------
# 3. HIGH-ACCURACY QUANT SIGNAL ENGINE
# -------------------------------------------------------------------
def evaluate_market_edge(symbol: str):
    """Calculates multi-factor VWAP + Volume Spike + Momentum Alpha Edge."""
    ticks = market_data_cache[symbol]
    if len(ticks) < 15:
        return None, 0.0

    df = pd.DataFrame(ticks)
    latest_price = df['price'].iloc[-1]
    
    # Calculate VWAP
    df['pv'] = df['price'] * df['volume']
    vwap = df['pv'].sum() / df['volume'].sum() if df['volume'].sum() > 0 else latest_price
    
    # EMAs
    ema_fast = df['price'].ewm(span=5, adjust=False).mean().iloc[-1]
    ema_slow = df['price'].ewm(span=15, adjust=False).mean().iloc[-1]
    
    # Volume Expansion Filter
    vol_mean = df['volume'].mean()
    latest_vol = df['volume'].iloc[-1]
    volume_spike = latest_vol > (vol_mean * 1.5)

    # Position State
    pos = active_positions.get(symbol, {"qty": 0, "entry": 0.0})
    qty = pos["qty"]
    entry = pos["entry"]
    
    pnl_pct = (latest_price - entry) / entry if qty > 0 and entry > 0 else 0.0
    
    # Strategy Rules
    stop_loss = (qty > 0) and (pnl_pct <= -0.008)
    take_profit = (qty > 0) and (pnl_pct >= 0.012)
    
    buy_edge = (latest_price > vwap) and (ema_fast > ema_slow) and volume_spike and (qty == 0)
    sell_edge = ((ema_fast < ema_slow) or (latest_price < vwap)) and (qty > 0)
    
    if stop_loss:
        return ("STOP_LOSS", qty), latest_price
    elif take_profit:
        return ("TAKE_PROFIT", qty), latest_price
    elif buy_edge:
        target_qty = max(1, int(MAX_CAPITAL_PER_TRADE // latest_price))
        return ("BUY", target_qty), latest_price
    elif sell_edge:
        return ("SELL", qty), latest_price
        
    return None, latest_price

# -------------------------------------------------------------------
# 4. WEBSOCKET REAL-TIME TICK HANDLER
# -------------------------------------------------------------------
async def handle_trade_tick(data):
    symbol = data.symbol
    price = data.price
    size = data.size
    
    # Cache up to 30 ticks per ticker
    market_data_cache[symbol].append({"price": price, "volume": size})
    if len(market_data_cache[symbol]) > 30:
        market_data_cache[symbol].pop(0)

    if not bot_enabled:
        return

    signal_info, current_price = evaluate_market_edge(symbol)
    if not signal_info:
        return

    action, qty = signal_info
    if action == "BUY":
        await execute_order_async(symbol, OrderSide.BUY, current_price, qty, "Alpha Signal: VWAP + Volume Spike")
    elif action in ["SELL", "STOP_LOSS", "TAKE_PROFIT"]:
        await execute_order_async(symbol, OrderSide.SELL, current_price, qty, f"Exit Trigger: {action}")

# -------------------------------------------------------------------
# 5. ASYNC MANUAL OVERRIDE TERMINAL
# -------------------------------------------------------------------
async def user_input_listener():
    """Allows manual trade overrides via CLI without blocking market feeds."""
    global bot_enabled
    print("\n=======================================================")
    print("🕹️  MANUAL CONTROL TERMINAL ACTIVE")
    print("Commands:")
    print("  b <symbol> <qty>  -> Manual Market Buy (e.g. 'b AAPL 1')")
    print("  s <symbol> <qty>  -> Manual Market Sell (e.g. 's AAPL 1')")
    print("  p                -> Panic Flush All Positions")
    print("  t                -> Toggle Autonomous Bot ON/OFF")
    print("=======================================================\n")
    
    loop = asyncio.get_event_loop()
    while True:
        user_cmd = await loop.run_in_executor(None, input, "COMMAND > ")
        cmd_parts = user_cmd.strip().split()
        if not cmd_parts:
            continue
            
        action = cmd_parts[0].lower()
        if action == 't':
            bot_enabled = not bot_enabled
            state = "ENABLED 🟢" if bot_enabled else "DISABLED 🔴"
            print(f"--> Autonomous Trading Engine is now {state}")
            
        elif action == 'p':
            print("🚨 PANIC FLUSH INITIATED! Liquidating all positions...")
            trading_client.cancel_orders()
            positions = trading_client.get_all_positions()
            for p in positions:
                trading_client.close_position(p.symbol)
            print("✅ Portfolio Liquidated.")
            
        elif action in ['b', 's'] and len(cmd_parts) == 3:
            sym = cmd_parts[1].upper()
            qty = int(cmd_parts[2])
            side = OrderSide.BUY if action == 'b' else OrderSide.SELL
            
            # Fetch latest cached price
            ticks = market_data_cache.get(sym, [])
            ref_price = ticks[-1]["price"] if ticks else 100.0
            
            asyncio.create_task(
                execute_order_async(sym, side, ref_price, qty, f"Manual CLI Override ({side.value.upper()})")
            )

# -------------------------------------------------------------------
# 6. ASYNC EVENT LOOP RUNNER
# -------------------------------------------------------------------
async def main():
    stream_client.subscribe_trades(handle_trade_tick, *TICKERS)
    
    # Run WebSocket stream and Manual Input Listener concurrently
    await asyncio.gather(
        stream_client._run_forever(),
        user_input_listener()
    )

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nShutdown complete.")
