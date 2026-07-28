from __future__ import annotations

from typing import TYPE_CHECKING

from bist_bot.app_logging import get_logger

if TYPE_CHECKING:
    from bist_bot.agent.trading_agent import TradingAgent

logger = get_logger(__name__, component="command_handler")

HELP_TEXT = """🤖 Trading Agent Komutları:

/status — Agent durumu, açık pozisyonlar, P&L
/stop — Acil durum: tüm işlemleri durdur
/pause [dakika] — Yeni girişleri N dakika durdur (varsayılan: 60)
/resume — Duraklatma/acil durum sonrası devam et
/close <TICKER> — Belirli bir pozisyonu manuel kapat
/help — Bu mesajı göster
"""


class CommandHandler:
    def __init__(self, agent: TradingAgent) -> None:
        self.agent = agent

    def handle(self, command: str) -> str:
        cmd = command.strip().lower()
        parts = cmd.split()

        if not parts:
            return HELP_TEXT

        action = parts[0]

        handlers = {
            "/status": self._cmd_status,
            "/stop": self._cmd_stop,
            "/pause": self._cmd_pause,
            "/resume": self._cmd_resume,
            "/close": self._cmd_close,
            "/help": lambda _: HELP_TEXT,
            "status": self._cmd_status,
            "stop": self._cmd_stop,
            "pause": self._cmd_pause,
            "resume": self._cmd_resume,
            "close": self._cmd_close,
            "help": lambda _: HELP_TEXT,
        }

        handler = handlers.get(action)
        if handler:
            try:
                return handler(parts)
            except Exception as exc:
                logger.exception("command_execution_failed", command=command)
                return f"❌ Komut hatası: {exc}"
        return f"❌ Bilinmeyen komut: {action}. Yardım için /help"

    def _cmd_status(self, _parts: list[str]) -> str:
        status = self.agent.status()
        lines = [
            f"📊 Agent Durumu: {status['agent_state']}",
            f"📈 Açık Pozisyon: {status['open_positions']}/{status['max_open_positions']}",
            f"📅 Günlük İşlem: {status['daily_trades']}/{status['max_daily_trades']}",
        ]
        if status["positions"]:
            lines.append("\n📍 Açık Pozisyonlar:")
            for p in status["positions"]:
                lines.append(
                    f"  {p['ticker']} | Giriş: ₺{p['entry_price']:.2f} | "
                    f"Stop: ₺{p['stop_loss']:.2f} | Hedef: ₺{p['target_price']:.2f}"
                )
        else:
            lines.append("\n📍 Açık pozisyon yok.")
        return "\n".join(lines)

    def _cmd_stop(self, _parts: list[str]) -> str:
        self.agent.emergency_stop(reason="manual_command")
        return "🛑 Acil durum: Tüm işlemler durduruldu!"

    def _cmd_pause(self, parts: list[str]) -> str:
        duration = 60
        if len(parts) > 1:
            try:
                duration = int(parts[1])
            except ValueError:
                pass
        return self.agent.pause(duration)

    def _cmd_resume(self, _parts: list[str]) -> str:
        return self.agent.resume()

    def _cmd_close(self, parts: list[str]) -> str:
        if len(parts) < 2:
            return "❌ Kullanım: /close <TICKER> — Örn: /close THYAO.IS"
        ticker = parts[1].upper()
        if not ticker.endswith(".IS"):
            ticker = f"{ticker}.IS"

        status = self.agent.status()
        positions = status.get("positions", [])
        target = None
        for p in positions:
            if p["ticker"] == ticker:
                target = p
                break
        if not target:
            return f"❌ {ticker} için açık pozisyon bulunamadı."

        success = False
        try:

            pm = self.agent.position_manager
            pos = pm.get_position(ticker)
            if pos:
                self.agent.exit_service.exit_position(
                    position_id=pos["id"],
                    ticker=ticker,
                    quantity=pos["quantity"],
                    exit_reason="MANUAL",
                    current_price=pos["entry_price"],
                )
                success = True
        except Exception as exc:
            return f"❌ Kapatma hatası: {exc}"

        if success:
            return f"✅ {ticker} pozisyonu manuel kapatıldı."
        return f"❌ {ticker} kapatılamadı."
