"""Live-like (gerçekçi) maliyet ve icra varsayımları — v2 toparlama planı adım 3.

Backtest'in iyimserliği, canlı ile arasındaki farkın baş şüphelilerinden.
Bu modül, sinyal tekrar oynatımı (``signal_replay``) için maliyetsiz/iyimser
senaryoların yanına konulacak **gerçekçi** senaryoyu tanımlar:

- ``REALISTIC_COSTS``: v2 planındaki sayısal varsayımlar (dokümantasyon değeri).
- ``RealisticExecution``: icra varsayımları demeti.
- ``realistic_cost_model()``: ``CostModel`` karşılığı (replay motoru tüketir).
- ``realistic_cost_scenarios()``: zero/base/stress + realistic sözlüğü.
- ``compare_cost_scenarios()``: maliyetsiz ↔ gerçekçi fark raporu.

Zorlama (enforcement) durumu — dürüst not:
- Maliyet modeli (komisyon/vergi/spread/slippage): replay motorunda ZORLANIR.
- ``latency_bars``: replay motorunun ``entry_delay_bars`` argümanıyla ZORLANIR
  (çağıran taraf ``realistic_execution().latency_bars`` değerini geçirir).
- Hacim/katılım/fill/tavan-taban/kurumsal-aksiyon/veri-kalitesi: henüz replay
  motorunda filtre olarak YOKTUR; live-health ve shadow tarafında kapı olarak
  eklenene kadar belgelendirilmiş varsayım olarak dururlar.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from bist_bot.backtest.models import CostModel
from bist_bot.config.settings import settings

# v2 planı §3 sayısal varsayımları (bps; 100 bps = %1).
# DK: komisyon AlgoLab perakende tarifesine göre 15 bps; vergi/harçlar 2024
# BIST tarifesiyle aynı (CostModel default'ları).
REALISTIC_COSTS: dict[str, float] = {
    "commission_bps": 15.0,
    "stamp_tax_bps": 9.3,
    "bsmv_bps": 5.0,
    "exchange_fee_bps": 0.3,
    "spread_bps": 20.0,  # min_spread_pct %0.2
    "entry_slippage_bps": 30.0,  # %0.3
    "exit_slippage_bps": 30.0,  # %0.3
    "latency_bars": 1.0,
    "min_volume_try": 100_000.0,
    "max_participation_pct": 1.0,
    "fill_probability": 0.95,
}


@dataclass(frozen=True)
class RealisticExecution:
    """Gerçekçi icra varsayımları demeti.

    Maliyet tarafı ``realistic_cost_model()`` ile replay'de zorlanır.
    ``latency_bars``, replay çağrılarında ``entry_delay_bars`` olarak geçirilir.
    Hacim/katılım/fill/limit/aksiyon/veri bayrakları belgelenmiş varsayımdır
    (henüz replay filtresi değil; live-health kapıları olarak eklenecek).
    """

    latency_bars: int = 1
    entry_slippage_bps: float = 30.0
    exit_slippage_bps: float = 30.0
    min_spread_bps: float = 20.0
    min_volume_try: float = 100_000.0
    max_participation_pct: float = 1.0
    fill_probability: float = 0.95
    price_limit_check: bool = True
    corporate_action_adjustment: bool = True
    data_quality_filter: bool = True


def _getenv_float(name: str, default: float) -> float:
    return float(getattr(settings, name, default))


def _getenv_int(name: str, default: int) -> int:
    return int(getattr(settings, name, default))


def realistic_execution(
    *,
    latency_bars: int | None = None,
    entry_slippage_bps: float | None = None,
    exit_slippage_bps: float | None = None,
    min_spread_bps: float | None = None,
    min_volume_try: float | None = None,
    max_participation_pct: float | None = None,
    fill_probability: float | None = None,
) -> RealisticExecution:
    """Env-override edilebilir gerçekçi icra demeti (fail-safe aralıklı)."""
    execution = RealisticExecution(
        latency_bars=latency_bars
        if latency_bars is not None
        else _getenv_int("BACKTEST_REALISTIC_ENTRY_DELAY_BARS", 1),
        entry_slippage_bps=entry_slippage_bps
        if entry_slippage_bps is not None
        else _getenv_float("BACKTEST_REALISTIC_SLIPPAGE_BPS", 30.0),
        exit_slippage_bps=exit_slippage_bps
        if exit_slippage_bps is not None
        else _getenv_float("BACKTEST_REALISTIC_SLIPPAGE_BPS", 30.0),
        min_spread_bps=min_spread_bps
        if min_spread_bps is not None
        else _getenv_float("BACKTEST_REALISTIC_SPREAD_BPS", 20.0),
        min_volume_try=min_volume_try
        if min_volume_try is not None
        else _getenv_float("BACKTEST_REALISTIC_MIN_VOLUME_TRY", 100_000.0),
        max_participation_pct=max_participation_pct
        if max_participation_pct is not None
        else _getenv_float("BACKTEST_REALISTIC_MAX_PARTICIPATION_PCT", 1.0),
        fill_probability=fill_probability
        if fill_probability is not None
        else _getenv_float("BACKTEST_REALISTIC_FILL_PROBABILITY", 0.95),
    )
    if execution.latency_bars < 0:
        raise ValueError("latency_bars must be >= 0")
    for field_name in (
        "entry_slippage_bps",
        "exit_slippage_bps",
        "min_spread_bps",
        "min_volume_try",
    ):
        if float(getattr(execution, field_name)) < 0:
            raise ValueError(f"{field_name} must be >= 0")
    if not 0.0 < execution.fill_probability <= 1.0:
        raise ValueError("fill_probability must be in (0, 1]")
    if not 0.0 < execution.max_participation_pct <= 100.0:
        raise ValueError("max_participation_pct must be in (0, 100]")
    return execution


def realistic_cost_model(
    *,
    commission_bps: float | None = None,
    execution: RealisticExecution | None = None,
) -> CostModel:
    """Gerçekçi maliyet modeli (iki yönlü slippage ortalaması + spread)."""
    execution = execution or realistic_execution()
    commission = (
        commission_bps
        if commission_bps is not None
        else _getenv_float("BACKTEST_REALISTIC_COMMISSION_BPS", 15.0)
    )
    if commission < 0:
        raise ValueError("commission_bps must be >= 0")
    avg_slippage = (execution.entry_slippage_bps + execution.exit_slippage_bps) / 2.0
    return CostModel(
        commission_bps=commission,
        stamp_tax_bps=float(REALISTIC_COSTS["stamp_tax_bps"]),
        bsmv_bps=float(REALISTIC_COSTS["bsmv_bps"]),
        exchange_fee_bps=float(REALISTIC_COSTS["exchange_fee_bps"]),
        spread_bps=execution.min_spread_bps,
        slippage_model="fixed",
        fixed_slippage_bps=avg_slippage,
    )


def realistic_cost_scenarios() -> dict[str, CostModel]:
    """zero/base/stress + realistic senaryo sözlüğü (dual-run raporu için)."""
    from bist_bot.backtest.signal_replay import build_cost_scenarios

    scenarios = build_cost_scenarios()
    scenarios["realistic"] = realistic_cost_model()
    return scenarios


def compare_cost_scenarios(
    metrics_by_scenario: dict[str, dict[str, Any]],
    *,
    baseline: str = "zero",
    candidate: str = "realistic",
) -> dict[str, Any]:
    """Maliyetsiz ↔ gerçekçi fark raporu (``calculate_cell_metrics`` çıktıları).

    Kabul kuralı (v2 §3): gerçekçi WR, maliyetsiz WR'den çok düşüyorsa sorun
    backtest'in iyimserliğidir — bu rapor o farkı sayıya döker.
    """
    if baseline not in metrics_by_scenario:
        raise KeyError(f"baseline scenario missing: {baseline!r}")
    if candidate not in metrics_by_scenario:
        raise KeyError(f"candidate scenario missing: {candidate!r}")
    base = metrics_by_scenario[baseline]
    cand = metrics_by_scenario[candidate]
    base_traded = int(base.get("n_traded", 0))
    cand_traded = int(cand.get("n_traded", 0))
    return {
        "baseline": baseline,
        "candidate": candidate,
        "win_rate_delta_pp": round(
            (float(cand.get("win_rate", 0.0)) - float(base.get("win_rate", 0.0))) * 100.0,
            2,
        ),
        "avg_net_pnl_delta_pp": round(
            (float(cand.get("avg_net_pnl_pct", 0.0)) - float(base.get("avg_net_pnl_pct", 0.0)))
            * 100.0,
            4,
        ),
        "avg_r_net_delta": round(
            float(cand.get("avg_r_net", 0.0)) - float(base.get("avg_r_net", 0.0)),
            4,
        ),
        "traded_delta": cand_traded - base_traded,
        "baseline_traded": base_traded,
        "candidate_traded": cand_traded,
    }
