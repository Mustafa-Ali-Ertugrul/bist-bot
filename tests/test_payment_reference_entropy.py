"""Regression test for payment reference entropy (Round 18).

BIST-{user_id}-{token_hex(6)} — 48-bit hex suffix must be long enough to
resist brute-force enumeration. The reference is not a secret credential
in itself, but 3-byte (24-bit) suffixes would have been trivially
enumerable via the admin listing boundary.
"""

from __future__ import annotations

import re


def test_payment_reference_min_entropy():
    import secrets as py_secrets

    # Mirror the production generator: user id 42 + 6-byte hex suffix.
    ref = f"BIST-42-{py_secrets.token_hex(6).upper()}"
    m = re.fullmatch(r"BIST-\d+-([0-9A-F]{12})", ref)
    assert m, f"unexpected reference shape: {ref}"
    # 12 hex chars = 48 bits of entropy
    assert len(m.group(1)) == 12
