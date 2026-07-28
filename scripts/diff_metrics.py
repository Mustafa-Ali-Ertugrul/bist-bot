"""Generate delta report comparing HEAD vs pre-fix baseline metrics."""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

# Force UTF-8 stdout to avoid Windows cp1252 errors with non-ASCII chars.
try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
except Exception:
    pass

if len(sys.argv) != 3:
    print("Usage: python scripts/diff_metrics.py <old.json> <new.json>")
    sys.exit(1)

old = json.loads(Path(sys.argv[1]).read_text())
new = json.loads(Path(sys.argv[2]).read_text())


def _line(label, old_v, new_v, fmt="{:>8.2f}"):
    if isinstance(old_v, dict) or isinstance(new_v, dict):
        return f"  {label}: <see component stats>"
    delta = ""
    try:
        d = float(new_v) - float(old_v)
        delta = f" (DELTA {d:+.2f})" if d else ""
    except (TypeError, ValueError):
        delta = ""
    try:
        ov = fmt.format(float(old_v)) if isinstance(old_v, (int, float)) else str(old_v)
        nv = fmt.format(float(new_v)) if isinstance(new_v, (int, float)) else str(new_v)
    except (TypeError, ValueError):
        ov, nv = str(old_v), str(new_v)
    return f"  {label:<32} old={ov:>8}  new={nv:>8}{delta}"


def _section(title):
    print()
    print("=" * 70)
    print(title)
    print("=" * 70)


def _signal_counts(old_c, new_c):
    keys = sorted(set(old_c) | set(new_c))
    print(f"  {'signal':<16}{'old':>8}{'new':>8}  delta")
    for k in keys:
        o = old_c.get(k, 0)
        n = new_c.get(k, 0)
        d = n - o
        marker = "*" if d != 0 else " "
        print(f"  {k:<16}{o:>8}{n:>8}  {d:+d} {marker}")


def _stats_block(label, o, n):
    if o.get("count", 0) == 0 and n.get("count", 0) == 0:
        print(f"  {label}: no samples")
        return
    for k in ("count", "mean", "p50", "p90", "p99", "min", "max"):
        ov = o.get(k, "-")
        nv = n.get(k, "-")
        if isinstance(ov, float) and isinstance(nv, float):
            d = nv - ov
            line = f"  {label}.{k:<6} old={ov:>10.3f}  new={nv:>10.3f}  DELTA {d:+.3f}"
        else:
            line = f"  {label}.{k:<6} old={str(ov):>10}  new={str(nv):>10}"
        print(line)


_section("CONFIG")
print(f"  n_bars={old['config']['n_bars']} n_symbols={old['config']['n_symbols']} seed={old['config']['seed']}")
print(f"  n_analyzed old={old['n_analyzed']} new={new['n_analyzed']}")

_section("SIGNAL COUNTS")
_signal_counts(old["signal_counts"], new["signal_counts"])

_section("AGGREGATE SCORE")
_stats_block("scores", old["scores"], new["scores"])

_section("MOMENTUM")
_stats_block("momentum", old["momentum"], new["momentum"])

_section("TREND")
_stats_block("trend", old["trend"], new["trend"])

_section("VOLUME")
_stats_block("volume", old["volume"], new["volume"])

_section("STRUCTURE")
_stats_block("structure", old["structure"], new["structure"])

_section("EMA INITIAL CROSS")
print(_line("triggered symbols", old["ema_initial_cross_triggered_symbols"],
            new["ema_initial_cross_triggered_symbols"], "{:>8.0f}"))

_section("SELL STOP / TARGET (Asama 4 etkisi)")
_stats_block("sell_stop", old["sell_stop_stats"], new["sell_stop_stats"])
_stats_block("sell_target", old["sell_target_stats"], new["sell_target_stats"])
print(_line("stop above price count", old["sell_stop_above_price_count"],
            new["sell_stop_above_price_count"], "{:>8.0f}"))
print(_line("target below price count", old["sell_target_below_price_count"],
            new["sell_target_below_price_count"], "{:>8.0f}"))

_section("INTERPRETATION")
buy_old = sum(old["signal_counts"].get(k, 0) for k in ("STRONG_BUY", "BUY", "WEAK_BUY"))
buy_new = sum(new["signal_counts"].get(k, 0) for k in ("STRONG_BUY", "BUY", "WEAK_BUY"))
sell_old = sum(old["signal_counts"].get(k, 0) for k in ("STRONG_SELL", "SELL", "WEAK_SELL"))
sell_new = sum(new["signal_counts"].get(k, 0) for k in ("STRONG_SELL", "SELL", "WEAK_SELL"))
hold_old = old["signal_counts"].get("HOLD", 0)
hold_new = new["signal_counts"].get("HOLD", 0)
print(f"  BUY total   old={buy_old}  new={buy_new}  DELTA {buy_new - buy_old:+d}")
print(f"  SELL total  old={sell_old}  new={sell_new}  DELTA {sell_new - sell_old:+d}")
print(f"  HOLD        old={hold_old}  new={hold_new}  DELTA {hold_new - hold_old:+d}")
print(f"  Score max   old={old['scores']['max']:>6.1f}  new={new['scores']['max']:>6.1f}  "
      f"DELTA {new['scores']['max'] - old['scores']['max']:+.1f}")
print(f"  Score p99   old={old['scores']['p99']:>6.2f}  new={new['scores']['p99']:>6.2f}  "
      f"DELTA {new['scores']['p99'] - old['scores']['p99']:+.2f}")
