# AUTO_EXECUTE migration note

`AUTO_EXECUTE_ENABLED` is a new independent money-movement gate. It defaults to `false` even when
the legacy `AUTO_EXECUTE=true` setting is present.

## Operator action

1. Keep `BROKER_MODE=paper` / `ALGOLAB_DRY_RUN=true` while validating the release.
2. Confirm `/metrics` reports `bist_auto_execute_migration_blocked 1` when only the legacy flag is
   enabled.
3. Review `auto_execute_disabled_new_gate_required` startup warnings.
4. After RBAC, broker, persistent DB, and circuit-breaker checks pass, explicitly set both:

   ```text
   AUTO_EXECUTE=true
   AUTO_EXECUTE_ENABLED=true
   ```

5. Restart and confirm the migration-blocked gauge becomes `0` before any controlled live test.

The legacy `AUTO_EXECUTE` compatibility flag is retained for one release and is planned for removal
after operators migrate to the independent gate.
