"""Tests for canonical import paths and legacy shim deprecation."""

from __future__ import annotations

import importlib

import pytest


class TestRemovedLegacyShims:
    def test_database_shim_removed(self):
        with pytest.raises(ImportError):
            importlib.import_module("bist_bot.database")


class TestRiskManagerShimRemoved:
    def test_import_raises_import_error(self):
        with pytest.raises(ImportError):
            importlib.import_module("bist_bot.risk_manager")


class TestCanonicalImportPaths:
    def test_risk_package_exports_risk_manager(self):
        from bist_bot.risk import RiskManager, RiskLevels

        assert RiskManager is not None
        assert RiskLevels is not None

    def test_db_package_exports_data_access(self):
        from bist_bot.db import DataAccess

        assert DataAccess is not None
