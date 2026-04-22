"""Tests for canonical import paths and legacy shim deprecation."""

from __future__ import annotations

import importlib
import warnings

import pytest


class TestRemovedLegacyShims:
    def test_database_shim_removed(self):
        with pytest.raises(ImportError):
            importlib.import_module("bist_bot.database")


class TestRiskManagerDeprecatedShim:
    def test_import_emits_deprecation_warning(self):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            importlib.import_module("bist_bot.risk_manager")
        deprecation_warnings = [w for w in caught if issubclass(w.category, DeprecationWarning)]
        assert len(deprecation_warnings) >= 1
        msg = str(deprecation_warnings[0].message)
        assert "bist_bot.risk" in msg

    def test_shim_exports_risk_manager(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            mod = importlib.import_module("bist_bot.risk_manager")
        assert hasattr(mod, "RiskManager")
        assert hasattr(mod, "RiskLevels")


class TestCanonicalImportPaths:
    def test_risk_package_exports_risk_manager(self):
        from bist_bot.risk import RiskManager, RiskLevels

        assert RiskManager is not None
        assert RiskLevels is not None

    def test_db_package_exports_data_access(self):
        from bist_bot.db import DataAccess

        assert DataAccess is not None
