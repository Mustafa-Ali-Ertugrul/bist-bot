import config
from contracts import NotifierProtocol
from indicators import TechnicalIndicators


def check_signals(ticker, df):
    if df is None or len(df) < 30:
        return None, []

    ti = TechnicalIndicators()
    df = ti.add_all(df)
    last = df.iloc[-1]

    conditions = []

    rsi = last.get("rsi")
    if rsi and rsi < 45:
        conditions.append(f"RSI: {rsi:.0f}")

    vol_ratio = last.get("volume_ratio", 1.0)
    if vol_ratio and vol_ratio > 1.0:
        conditions.append(f"Hacim: {vol_ratio:.1f}x")

    macd_cross = last.get("macd_cross")
    if macd_cross == "BULLISH":
        conditions.append("MACD: BULLISH")

    sma_cross = last.get("sma_cross")
    if sma_cross == "GOLDEN_CROSS":
        conditions.append("SMA: GOLDEN_CROSS")

    count = len(conditions)

    if count >= 3:
        return "AL", conditions
    elif count == 2:
        return "SAT", conditions
    else:
        return None, conditions


def send_signal_notification(
    ticker,
    signal_type,
    conditions,
    notifier: NotifierProtocol,
):
    name = config.TICKER_NAMES.get(ticker, ticker)
    conditions_text = "\n".join([f"  • {c}" for c in conditions])

    if signal_type == "AL":
        emoji = "🚀💰"
        title = "AL"
    else:
        emoji = "🔴📉"
        title = "SAT"

    message = f"""
{emoji} <b>{title}!</b> - {name}
━━━━━━━━━━━━━━━━
Koşullar ({len(conditions)}/4):
{conditions_text}
━━━━━━━━━━━━━━━━
⚠️ <i>Yatırım tavsiyesi değildir!</i>
"""
    notifier.send_message(message.strip())
