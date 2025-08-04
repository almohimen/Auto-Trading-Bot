import ccxt
import requests
import time
import json
import pandas as pd
import ta
import os
import logging

# Logging setup
logging.basicConfig(filename='trading.log', level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')

# Load API keys
API_KEY = os.getenv("API_KEY")
API_SECRET = os.getenv("API_SECRET")

exchange = ccxt.binance({
    'apiKey': API_KEY,
    'secret': API_SECRET,
    'enableRateLimit': True
})

symbol_suffix = "/USDT"
max_positions = 3
capital_fraction = 1.0  # Use 100% of balance
rsi_threshold = 35
take_profit = 1.04
stop_loss = 0.96
positions_file = "positions.json"

def load_positions():
    try:
        with open(positions_file, "r") as f:
            return json.load(f)
    except:
        return {}

def save_positions(positions):
    with open(positions_file, "w") as f:
        json.dump(positions, f, indent=4)

def get_top_symbols(limit=20):
    url = f"https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&order=volume_desc&per_page={limit}&page=1"
    response = requests.get(url)
    data = response.json()
    available = exchange.load_markets()
    return [coin['symbol'].upper() + symbol_suffix for coin in data if coin['symbol'].upper() + symbol_suffix in available]

def get_indicators(symbol):
    bars = exchange.fetch_ohlcv(symbol, timeframe='1h', limit=100)
    df = pd.DataFrame(bars, columns=["time", "open", "high", "low", "close", "volume"])

    df["rsi"] = ta.momentum.RSIIndicator(df["close"]).rsi()
    macd = ta.trend.MACD(df["close"])
    df["macd_diff"] = macd.macd_diff()
    bb = ta.volatility.BollingerBands(df["close"])
    df["bb_lower"] = bb.bollinger_lband()
    df["bb_upper"] = bb.bollinger_hband()

    latest = df.iloc[-1]
    return latest["rsi"], latest["macd_diff"], latest["bb_lower"], latest["bb_upper"], latest["close"]

def run_bot():
    positions = load_positions()
    balance = exchange.fetch_balance()
    usdt_balance = balance['free']['USDT']
    trade_amount = usdt_balance * capital_fraction

    logging.info(f"Balance: {usdt_balance:.2f} USDT | Trade Amount: {trade_amount:.2f}")
    top_symbols = get_top_symbols()

    for symbol in top_symbols:
        if symbol in positions or len(positions) >= max_positions:
            continue

        try:
            rsi, macd_diff, bb_lower, bb_upper, price = get_indicators(symbol)
            logging.info(f"{symbol} | RSI: {rsi:.2f} | MACD: {macd_diff:.4f} | Price: {price:.2f} | BB: [{bb_lower:.2f}, {bb_upper:.2f}]")

            if rsi < rsi_threshold and macd_diff > 0 and price <= bb_lower:
                amount = trade_amount / price
                order = exchange.create_market_buy_order(symbol, amount)
                positions[symbol] = {
                    "buy_price": price,
                    "amount": amount
                }
                save_positions(positions)
                logging.info(f"✅ BUY: {symbol} at {price:.4f}")
        except Exception as e:
            logging.error(f"Error with {symbol}: {str(e)}")

    # Check for selling
    for symbol in list(positions.keys()):
        try:
            ticker = exchange.fetch_ticker(symbol)
            current_price = ticker['last']
            buy_price = positions[symbol]["buy_price"]
            amount = positions[symbol]["amount"]

            if current_price >= buy_price * take_profit or current_price <= buy_price * stop_loss:
                exchange.create_market_sell_order(symbol, amount)
                del positions[symbol]
                save_positions(positions)
                logging.info(f"💰 SELL: {symbol} at {current_price:.4f} (Buy: {buy_price:.4f})")
        except Exception as e:
            logging.error(f"Error checking sell for {symbol}: {str(e)}")

# Loop every 5 mins
while True:
    try:
        logging.info("🔁 Starting cycle")
        run_bot()
        logging.info("⏳ Waiting 5 minutes\n")
        time.sleep(300)
    except Exception as e:
        logging.error(f"Fatal error: {str(e)}")
        time.sleep(60)
