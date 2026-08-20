# Production hardening (SOT-2804)

Operational hardening for the Cloud Run backend: **PII-safe structured logging**,
**health probes + scale/concurrency**, and **Cloud Monitoring alerts**.

## 1. Structured, PII-safe logging

`pcca.logging_config` installs a JSON log formatter + a redaction filter on the root
logger; the FastAPI app factory (`create_app`) calls `configure_logging()` at startup.

- **Format** — one JSON object per line on stdout with a Cloud-Logging `severity` field,
  so Cloud Run parses each line into a structured entry at the right level.
- **Invariant (spec Safety)** — the logging layer never emits a child's **Personal
  Context values or health information**:
  - request/response **bodies are never logged** — the access-log middleware records only
    method, path, status, and duration;
  - the global exception handler logs the exception **type + stack frames** only (never
    the exception message/args, which could echo request input);
  - a `RedactionFilter` backstop masks email/phone patterns in messages and replaces the
    value of sensitive `extra` keys (`value`, `notes`, `context`, `password`, `email`,
    health terms, …) with `[REDACTED]`.
- **Level** — `LOG_LEVEL` env var (default `INFO`).

Covered by `tests/test_logging_redaction.py`.

## 2. Cloud Run probes + scale (`scripts/deploy_cloudrun.sh`)

The deploy explicitly sets, all env-overridable:

| Setting | Flag | Default |
| --- | --- | --- |
| Startup probe | `--startup-probe` → `GET /health` | period 5s, failureThreshold 12 |
| Liveness probe | `--liveness-probe` → `GET /health` | period 30s, failureThreshold 3 |
| Min instances | `--min-instances` (`MIN_INSTANCES`) | `0` (scale to zero) |
| Max instances | `--max-instances` (`MAX_INSTANCES`) | `4` (cost / fan-out guard) |
| Concurrency | `--concurrency` (`CONCURRENCY`) | `80` |

`/health` is the unauthenticated probe endpoint (no external calls, PII-free).

## 3. Cloud Monitoring alerts (`deploy/monitoring/`)

Alert policies applied via `apply_alerts.sh`:

- **`alert-error-rate.json`** — Cloud Run 5xx responses > 0.05/s for 5m.
- **`alert-latency.json`** — Cloud Run p95 request latency > 2000ms for 5m.

```bash
GCP_PROJECT_ID=sota-app-hub \
  NOTIFICATION_CHANNELS=projects/<p>/notificationChannels/<id> \
  bash deploy/monitoring/apply_alerts.sh
```

`__SERVICE__` in each policy's metric filter is substituted with `$SERVICE`
(default `personal-child-context-agent-backend`) at apply time.

> Applying probes/scale/alerts to the real GCP project is a deploy-time action
> (human/deploy gate). This directory is the reviewable source of truth for them.
