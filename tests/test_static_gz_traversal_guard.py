"""Regression tests for the static gzip fast-path traversal guard (Round 13).

The after_request gzip fast-path derives a filesystem path from
request.path. Round 13 replaced os.path.join with werkzeug safe_join,
so traversal sequences (../) can no longer escape the static folder.

NOTE: request.path is URL-DECODED by the time this code runs, so the
decoded form (../) is what the guard must block.
"""

from __future__ import annotations

import gzip
import os
import pathlib

from werkzeug.utils import safe_join

from bist_bot.dashboard import precompressed_is_fresh, safe_join_static

STATIC_DIR = pathlib.Path(__file__).resolve().parent.parent / "src" / "bist_bot" / "static"


def test_safe_join_blocks_traversal_in_gz_fast_path():
    """Decoded traversal payloads must resolve to None (no readable path).

    Uses the app's safe_join_static wrapper (backslash-normalized), not
    bare werkzeug safe_join: werkzeug only treats ``\\\\`` as a separator
    on Windows, so the backslash payload sails through on Linux CI while
    remaining a live traversal on Windows hosts.
    """
    for payload in (
        "../../../etc/passwd",
        "..\\..\\..\\etc\\passwd",
        "subdir/../../secrets",
    ):
        assert safe_join_static(str(STATIC_DIR), payload + ".gz") is None, payload


def test_safe_join_result_stays_inside_static():
    """Any surviving safe_join result must remain under the static root."""
    for payload in (
        "app.js",
        "css/main.css",
        "fonts/inter.woff2",
        "....//....//etc/passwd",
    ):
        joined = safe_join(str(STATIC_DIR), payload + ".gz")
        if joined is not None:
            assert str(pathlib.Path(joined).resolve()).startswith(str(STATIC_DIR)), payload


def test_safe_join_allows_normal_asset_names():
    """Legitimate static asset names still resolve inside the folder."""
    joined = safe_join(str(STATIC_DIR), "app.js.gz")
    assert joined is not None
    assert joined.startswith(str(STATIC_DIR))


def test_static_folder_no_symlinks():
    """No symlink inside static/ may point outside the folder."""
    if not STATIC_DIR.exists():
        return  # static assets not shipped in this checkout
    for root, _dirs, files in os.walk(STATIC_DIR):
        for name in files:
            path = pathlib.Path(root) / name
            if path.is_symlink():
                target = os.path.realpath(path)
                assert str(STATIC_DIR) in target, f"symlink escapes static: {path}"


def test_gzip_files_are_valid_and_not_bombs():
    """Shipped .gz assets must decompress to sane sizes (no zip bombs)."""
    if not STATIC_DIR.exists():
        return
    gz_files = list(STATIC_DIR.rglob("*.gz"))
    assert gz_files, "static folder must ship at least one .gz asset"
    for gz in gz_files:
        with gzip.open(gz, "rb") as fh:
            data = fh.read(2 * 1024 * 1024)  # cap read at 2MB
        compressed = gz.stat().st_size
        # Decompressed size must stay within a sane ratio (<200x) of the
        # compressed size; JavaScript/CSS text rarely exceeds 20x.
        assert len(data) < max(200 * compressed, 1024 * 1024), f"suspect ratio: {gz}"


def test_precompressed_assets_match_their_sources():
    """A shipped .gz must decompress to exactly the current source bytes.

    The gzip fast-path serves the .gz to every browser that accepts gzip, so
    an edited source with an old .gz ships stale JS/CSS (the app.js
    regression). If this fails, rebuild the .gz from the source.
    """
    if not STATIC_DIR.exists():
        return
    gz_files = list(STATIC_DIR.rglob("*.gz"))
    assert gz_files, "static folder must ship at least one .gz asset"
    for gz in gz_files:
        source = gz.with_suffix("")
        assert source.is_file(), f"orphan .gz without source: {gz}"
        with gzip.open(gz, "rb") as fh:
            assert fh.read() == source.read_bytes(), f"stale pre-compressed asset: {gz}"


def test_precompressed_freshness_guard_skips_stale_artifacts(tmp_path):
    """A .gz older than its source must never be served by the fast-path."""
    source = tmp_path / "app.js"
    gz = tmp_path / "app.js.gz"
    source.write_text("current", encoding="utf-8")
    gz.write_bytes(gzip.compress(b"stale"))

    os.utime(gz, (1_000_000, 1_000_000))
    os.utime(source, (2_000_000, 2_000_000))
    assert precompressed_is_fresh(str(gz), str(source)) is False, "stale .gz must be skipped"

    os.utime(gz, (3_000_000, 3_000_000))
    assert precompressed_is_fresh(str(gz), str(source)) is True

    assert precompressed_is_fresh(str(tmp_path / "missing.js.gz"), str(source)) is False
    assert precompressed_is_fresh(None, str(source)) is False
    assert precompressed_is_fresh(str(gz), None) is False
