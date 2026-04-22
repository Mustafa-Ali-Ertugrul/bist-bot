from bist_bot.contracts import NotifierProtocol
from bist_bot.strategy.signal_models import Signal, SignalType
from bist_bot.strategy import StrategyEngine


def check_signals(ticker, df, engine: StrategyEngine | None = None):
    if df is None:
        return None
    runtime_engine = engine or StrategyEngine()
    return runtime_engine.analyze(ticker, df, enforce_sector_limit=False)


def send_signal_notification(
    signal: Signal,
    notifier: NotifierProtocol,
):
    if signal.signal_type == SignalType.HOLD:
        return False
    return notifier.send_signal(signal)
