from flask import Flask, render_template, jsonify, request
from datetime import datetime
import json
import logging
import time
import pandas as pd

import config
from data_fetcher import BISTDataFetcher
from indicators import TechnicalIndicators
from strategy import StrategyEngine, SignalType
from database import SignalDatabase

logger = logging.getLogger(__name__)

app = Flask(__name__)
fetcher = BISTDataFetcher()
engine = StrategyEngine()
db = SignalDatabase()


@app.route("/health")
def health():
    return jsonify({
        "status": "ok",
        "timestamp": datetime.now().isoformat(),
    })


@app.route("/")
def index():
    return render_template("dashboard.html")


@app.route("/api/scan", methods=["POST"])
def api_scan():
    start_time = time.time()
    try:
        fetcher.clear_cache()
        all_data = fetcher.fetch_all()
        signals = engine.scan_all(all_data)

        actionable = engine.get_actionable_signals(signals)
        for s in actionable:
            db.save_signal(s)

        buys = [s for s in signals if s.score > 0]
        sells = [s for s in signals if s.score < 0]
        db.save_scan_log(
            len(all_data), len(actionable),
            len(buys), len(sells)
        )

        results = []
        for s in signals:
            results.append({
                "ticker": s.ticker,
                "name": config.TICKER_NAMES.get(s.ticker, s.ticker),
                "signal": s.signal_type.value,
                "score": s.score,
                "price": s.price,
                "stop_loss": s.stop_loss,
                "target": s.target_price,
                "confidence": s.confidence,
                "reasons": s.reasons,
                "timestamp": s.timestamp.isoformat(),
            })

        duration_ms = (time.time() - start_time) * 1000
        return jsonify({
            "status": "ok",
            "scanned": len(all_data),
            "signals": results,
            "timestamp": datetime.now().isoformat(),
            "duration_ms": round(duration_ms, 2),
        })

    except Exception as e:
        logger.error(f"Tarama hatası: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/analyze/<ticker>")
def api_analyze(ticker):
    start_time = time.time()
    try:
        if not ticker.endswith(".IS"):
            ticker += ".IS"

        df = fetcher.fetch_single(ticker, period="6mo")
        if df is None:
            return jsonify({"status": "error", "message": "Veri bulunamadı"}), 404

        ti = TechnicalIndicators()
        df = ti.add_all(df)
        snapshot = ti.get_snapshot(df)

        signal = engine.analyze(ticker, fetcher.fetch_single(ticker, period="6mo"))

        price_data = []
        for idx, row in df.tail(60).iterrows():
            price_data.append({
                "date": idx.strftime("%Y-%m-%d"),
                "open": round(row["open"], 2),
                "high": round(row["high"], 2),
                "low": round(row["low"], 2),
                "close": round(row["close"], 2),
                "volume": int(row["volume"]),
                "rsi": round(row.get("rsi", 50), 2) if pd.notna(row.get("rsi")) else None,
                "sma_fast": round(row.get(f"sma_{config.SMA_FAST}", 0), 2) if pd.notna(row.get(f"sma_{config.SMA_FAST}")) else None,
                "sma_slow": round(row.get(f"sma_{config.SMA_SLOW}", 0), 2) if pd.notna(row.get(f"sma_{config.SMA_SLOW}")) else None,
            })

        result = {
            "status": "ok",
            "ticker": ticker,
            "name": config.TICKER_NAMES.get(ticker, ticker),
            "snapshot": snapshot,
            "signal": {
                "type": signal.signal_type.value if signal else "N/A",
                "score": signal.score if signal else 0,
                "reasons": signal.reasons if signal else [],
                "stop_loss": signal.stop_loss if signal else 0,
                "target": signal.target_price if signal else 0,
            },
            "price_data": price_data,
            "duration_ms": round((time.time() - start_time) * 1000, 2),
        }

        return jsonify(result)

    except Exception as e:
        import traceback
        logger.error(f"Analiz hatası: {traceback.format_exc()}")
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/signals/history")
def api_signal_history():
    limit = request.args.get("limit", 50, type=int)
    ticker = request.args.get("ticker", None)
    signals = db.get_recent_signals(limit=limit, ticker=ticker)
    return jsonify({"status": "ok", "signals": signals})


@app.route("/api/stats")
def api_stats():
    stats = db.get_performance_stats()
    return jsonify({"status": "ok", "stats": stats})


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=config.FLASK_PORT,
        debug=config.FLASK_DEBUG
    )
