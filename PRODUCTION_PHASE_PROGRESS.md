# Production MVP Phase Progress

## Completed Phases
- Phase 0: repository and secret hygiene; `.gitignore` hardened; stale root-level `aws_provider.py` removed from git tracking only.
- Phase 1: security foundation with SECRET_KEY enforcement, credential encryption safety, YAML size limit, command-injection validation, CSRF, rate limiting, request IDs, and safer requirements.
- Phase 2: production config classes, PostgreSQL URL support, Flask-Migrate initialization, and migration documentation.
- Phase 3: Redis/RQ-compatible background deployment job plumbing with test-safe queue behavior and deployment status endpoint.
- Phase 4: health retry helper, richer health metadata fields, `cleanup-due` command, and auto-cleanup-on-health-failure handling.
- Phase 5: real-deployment quotas, billing acknowledgement gate, billing safety UI, and quota tests.
- Phase 6: user roles, admin pages, and sanitized audit logs.
- Phase 7: decision audit trail, budget-relative cost scoring, and "Why this provider?" UI.
- Phase 8: visible deployment wizard that generates existing YAML schema.
- Phase 9: deployment timeline on result/detail pages.
- Phase 10: cloud readiness dashboard polish.
- Phase 11: demo scenarios page.
- Phase 12: production readiness checklist page.
- Phase 14: README and `.env.example` production-MVP documentation updates.

## Current Phase
- Complete for this pass.

## Remaining Phases
- None in the reduced scope requested after the usage-limit update.

## Skipped Phases
- Phase 13: Docker/Gunicorn/Sentry/security-header work skipped per usage-conservation instruction. No new risky backend infrastructure should be started unless explicitly requested later.

## Last pytest -q Result
- After Phase 14: `144 passed, 362 warnings in 19.70s`.

## Changed Files So Far
- Modified: `.gitignore`, `README.md`, `app.py`, `config_schema.py`, `credential_vault.py`, `decision_engine.py`, `deployment_history.py`, `models.py`, `orchestrator.py`, `requirements.txt`, `static/js/app.js`.
- Modified templates: `_deployment_table.html`, `_result_sections.html`, `base.html`, `cloud_account_form.html`, `cloud_accounts.html`, `deploy_new.html`, `deployment_detail.html`, `login.html`, `providers.html`, `register.html`, `settings.html`.
- Modified tests: `test_app_cloud_selection.py`, `test_model_b_cloud_accounts.py`.
- Added: `config.py`, `health_checks.py`, `queue_utils.py`, `requirements-dev.txt`, `tasks.py`, `worker.py`, `migrations/.gitkeep`.
- Added templates: `admin.html`, `admin_deployments.html`, `admin_users.html`, `audit.html`, `demo_scenarios.html`, `deploy_wizard.html`, `production_readiness.html`.
- Added tests: `test_admin_audit.py`, `test_billing_quotas.py`, `test_config.py`, `test_decision_audit.py`, `test_demo_scenarios.py`, `test_deployment_timeline.py`, `test_deployment_wizard.py`, `test_health_retry.py`, `test_production_readiness.py`, `test_readiness_dashboard.py`, `test_security_foundation.py`.
- Git index note: tracked root-level `aws_provider.py` is removed from git index only; local copy still exists as untracked. Active AWS provider remains `providers/aws_provider.py`.

## Known Issues
- Test output contains existing deprecation warnings for `datetime.utcnow()` and legacy `Query.get()`. They do not currently fail the test suite.
- Phase 13 is intentionally skipped, so Docker/Gunicorn/Sentry/security headers are not completed in this pass.
- No real cloud/OAuth/network commands have been run.

## Exact Resume Point
- Resume later at Phase 13 only if explicitly requested: Dockerfile, docker-compose, Gunicorn config, optional Sentry initialization, and security headers.
- Keep dry-run default and run `pytest -q` after any future phase.
