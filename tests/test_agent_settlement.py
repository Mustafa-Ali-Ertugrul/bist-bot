from datetime import date

from bist_bot.agent.settlement import is_settled, settlement_date


class TestSettlement:
    def test_t2_normal_weekday(self):
        result = settlement_date(date(2026, 6, 8))
        assert result == date(2026, 6, 10)

    def test_t2_over_weekend(self):
        result = settlement_date(date(2026, 6, 11))
        assert result >= date(2026, 6, 15)

    def test_is_settled_true(self):
        assert is_settled(date(2026, 6, 1), date(2026, 6, 5)) is True

    def test_is_settled_false(self):
        assert is_settled(date(2026, 6, 10), date(2026, 6, 10)) is False
