"""Regression tests for production manifest security hardening (Round 9+12).

Guards cloudrun/api-service.yaml against silent RBAC/cookie downgrades:
- RBAC_MODE must be "enforce" (in "warn" mode admin routes only LOG
  unauthorized access without blocking it).
- JWT_COOKIE_SECURE must be "true" (Cloud Run is HTTPS-only; without the
  Secure flag auth cookies are sent over plain HTTP on downgrade).

Round 12: the deploy workflow (deploy-cloud-run.yml) — NOT the manifest —
is the real production env source (`gcloud run deploy --set-env-vars`).
Parity tests below lock both files together so a fix in one cannot be
silently bypassed by the other.
"""

from __future__ import annotations

import pathlib
import re

import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
MANIFEST = REPO_ROOT / "cloudrun" / "api-service.yaml"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "deploy-cloud-run.yml"


def _load_env() -> dict[str, str]:
    doc = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    containers = doc["spec"]["template"]["spec"]["containers"]
    assert containers, "manifest must define at least one container"
    env_list = containers[0].get("env", [])
    env: dict[str, str] = {}
    for entry in env_list:
        if "value" in entry:
            env[entry["name"]] = str(entry["value"])
    return env


def test_manifest_enforces_rbac():
    """RBAC_MODE=enforce blocks non-admin access; warn only logs it."""
    env = _load_env()
    assert env.get("RBAC_MODE", "").lower() == "enforce"


def test_manifest_secures_auth_cookies():
    """JWT_COOKIE_SECURE=true keeps auth cookies off plain HTTP."""
    env = _load_env()
    assert env.get("JWT_COOKIE_SECURE", "").lower() == "true"


def test_manifest_has_no_hardcoded_secrets():
    """Secret values must come from Secret Manager, never inline."""
    text = MANIFEST.read_text(encoding="utf-8")
    for forbidden in ("sk-", "ghp_", "xoxb-", "AKIA"):
        assert forbidden not in text
    # JWT_SECRET_KEY must remain a commented Secret Manager reference.
    assert "JWT_SECRET_KEY" in text
    env = _load_env()
    assert "JWT_SECRET_KEY" not in env


def _workflow_deploy_env() -> str:
    """Extract the --set-env-vars payload from the deploy workflow."""
    text = WORKFLOW.read_text(encoding="utf-8")
    match = re.search(r"--set-env-vars\s+([A-Za-z0-9_=,./:\-]+)", text)
    assert match, "deploy workflow must use --set-env-vars"
    return match.group(1)


def test_deploy_workflow_enforces_rbac():
    """The real deploy path must carry RBAC_MODE=enforce (Round 12)."""
    assert "RBAC_MODE=enforce" in _workflow_deploy_env()


def test_deploy_workflow_secures_auth_cookies():
    """The real deploy path must carry JWT_COOKIE_SECURE=true (Round 12)."""
    assert "JWT_COOKIE_SECURE=true" in _workflow_deploy_env()
