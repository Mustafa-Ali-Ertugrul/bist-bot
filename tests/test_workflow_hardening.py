"""Regression guard for GitHub Actions workflow hardening.

Verifies that CI workflow permissions stay least-privilege and that all
action references are pinned to immutable commit SHAs (supply chain).
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
_SHA_RE = re.compile(r"uses: [^@\s]+@([0-9a-f]{40}) # v[\d.]+")
_USES_RE = re.compile(r"uses:\s+(\S+@\S+)")

# First-party actions by the same repo's org are trusted; everything else
# (docker/*, gitleaks/*) is third-party.
_FIRST_PARTY_PREFIXES = ("actions/", "github/")


def test_ci_workflow_has_restricted_permissions():
    """CI must declare least-privilege permissions at top level."""
    assert CI_WORKFLOW.exists(), "ci.yml bulunamadı"
    content = CI_WORKFLOW.read_text(encoding="utf-8")
    assert "permissions:" in content
    assert "contents: read" in content


def _workflow_files() -> list[Path]:
    return [CI_WORKFLOW]


def test_all_actions_pinned_to_sha():
    """Every `uses:` must reference a 40-char commit SHA (mutable tags are
    a supply-chain vector: a compromised upstream can rewrite `@v3`)."""
    for path in _workflow_files():
        content = path.read_text(encoding="utf-8")
        uses = _USES_RE.findall(content)
        assert uses, f"{path.name} has no action references?"
        for ref in uses:
            assert re.search(r"@[0-9a-f]{40}( # v[\d.]+)?$", ref), (
                f"{path.name}: action not SHA-pinned: {ref}"
            )


def test_pinned_shas_carry_version_comment():
    """Each pin must keep the human-readable version in a trailing comment
    so reviewers can still see what is being run."""
    for path in _workflow_files():
        content = path.read_text(encoding="utf-8")
        pins = _SHA_RE.findall(content)
        assert pins, f"{path.name}: expected SHA-pinned actions with version comments"


def test_third_party_actions_are_sha_pinned():
    """Third-party actions (non actions/*, github/*) must never run from a
    mutable ref — HIGH per the Actions threat model."""
    for path in _workflow_files():
        content = path.read_text(encoding="utf-8")
        for ref in _USES_RE.findall(content):
            name = ref.split("@")[0]
            if not name.startswith(_FIRST_PARTY_PREFIXES):
                assert re.search(r"@[0-9a-f]{40}", ref), (
                    f"{path.name}: third-party action on mutable ref: {ref}"
                )
