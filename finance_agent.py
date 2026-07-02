import math
import random
import warnings

try:
    import yfinance as yf
    YF_ONLINE = True
    warnings.filterwarnings("ignore", category=FutureWarning, module="yfinance")
except ImportError:
    YF_ONLINE = False

def get_stock_data(ticker):
    ticker = ticker.upper()
    if YF_ONLINE:
        try:
            stock = yf.Ticker(ticker)
            hist = stock.history(period="1mo", interval="1h")
            if len(hist) > 10:
                prices = [round(float(p), 2) for p in hist['Close'].tolist()]
                return prices[-50:] 
        except Exception:
            pass 

    random.seed(ticker)
    base_price = random.randint(10, 350)
    prices = []
    current_price = base_price
    for _ in range(50): 
        change = current_price * 0.005 * random.uniform(-1.0, 1.1)
        current_price = max(1.0, current_price + change)
        prices.append(round(current_price, 2))
    return prices

def get_fundamentals(ticker):
    if not YF_ONLINE:
        return {"sector": "N/A (Sim)", "market_cap": "N/A", "pe_ratio": "N/A", "high_52": "N/A", "low_52": "N/A", "summary": "Live data offline."}
    try:
        stock = yf.Ticker(ticker.upper())
        info = stock.info
        mcap = info.get('marketCap', 0)
        if mcap > 1e12: mcap_str = f"${mcap/1e12:.2f} Trillion"
        elif mcap > 1e9: mcap_str = f"${mcap/1e9:.2f} Billion"
        else: mcap_str = f"${mcap:,}"
        
        summary = info.get('longBusinessSummary', 'No summary available.')
        short_summary = summary[:150] + "..." if len(summary) > 150 else summary
        
        return {
            "sector": info.get('sector', 'Unknown'),
            "market_cap": mcap_str,
            "pe_ratio": info.get('trailingPE', 'N/A'),
            "high_52": info.get('fiftyTwoWeekHigh', 'N/A'),
            "low_52": info.get('fiftyTwoWeekLow', 'N/A'),
            "summary": short_summary
        }
    except Exception:
        return {"sector": "Data Err", "market_cap": "Data Err", "pe_ratio": "Err", "high_52": "Err", "low_52": "Err", "summary": "Could not pull company profile."}

def calculate_sma(prices, period=10):
    if len(prices) < period: return sum(prices) / len(prices)
    return round(sum(prices[-period:]) / period, 2)

def calculate_rsi(prices, period=14):
    if len(prices) < 2: return 50.0
    gains = 0; losses = 0
    for i in range(1, len(prices)):
        change = prices[i] - prices[i-1]
        if change > 0: gains += change
        else: losses += abs(change)
    if losses == 0: return 100.0
    rs = gains / losses
    rsi = 100 - (100 / (1 + rs))
    return round(rsi, 2)

# --- CAUSAL REASONING UPGRADE: MACD MOMENTUM ---
def calculate_macd(prices):
    if len(prices) < 26: return 0.0
    def ema(data, period):
        k = 2 / (period + 1)
        ema_val = sum(data[:period]) / period
        for price in data[period:]:
            ema_val = price * k + ema_val * (1 - k)
        return ema_val
    ema_12 = ema(prices, 12)
    ema_26 = ema(prices, 26)
    return round(ema_12 - ema_26, 3)

def analyze_stock(ticker):
    ticker = ticker.strip().upper()
    prices = get_stock_data(ticker)
    fundamentals = get_fundamentals(ticker)
    
    current = prices[-1]
    sma_10 = calculate_sma(prices, 10)
    rsi_14 = calculate_rsi(prices, 14)
    macd_val = calculate_macd(prices)
    
    # Advanced logic combining RSI and MACD (Cause and Effect)
    if rsi_14 > 70 and macd_val < 0: signal = "STRONG SELL (Momentum Reversing)"
    elif rsi_14 > 70: signal = "OVERBOUGHT (Potential Pullback)"
    elif rsi_14 < 30 and macd_val > 0: signal = "STRONG BUY (Momentum Building)"
    elif rsi_14 < 30: signal = "OVERSOLD (Potential Rebound)"
    elif macd_val > 0.5: signal = "BULLISH (Positive Momentum)"
    elif macd_val < -0.5: signal = "BEARISH (Negative Momentum)"
    else: signal = "NEUTRAL (Stable Trend)"
        
    return {
        "ticker": ticker, "current_price": current, "prev_close": prices[-2],
        "sma_10": sma_10, "rsi_14": rsi_14, "macd": macd_val, "signal": signal, 
        "history": prices, "fundamentals": fundamentals
    }