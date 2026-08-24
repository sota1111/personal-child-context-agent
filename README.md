# Personal Child Context Agent

**Same information. Different child. Different action.**

Schools send generic information, but every child has different needs. Parents
still have to figure out what matters to *their* child. This agent closes the gap
between **Generic School Information** and **Personal Child Context**.

It continuously reconciles the two and surfaces — *with evidence* — what is
relevant to this child, explicit conflicts, missing information needed to decide,
questions for the parent, and the next required action. It does not just display a
warning and stop: with the parent's approval it performs real actions, keeps
unresolved items as **persistent actions**, and re-evaluates them when new school
information arrives.

## Core flow

```
Detect → Clarify → Plan → Act → Track → Re-evaluate
```

The initial MVP focuses on **Field Trip / Excursion Readiness**.

These six steps are wired together by the deterministic orchestrator
`pcca.flow.AgentFlow` (`build_flow()`): it runs the Document Tool (Detect), the
Conflict Tool (Clarify), plans evidence-backed actions, executes only the
human-approved ones (Act), persists them as **persistent actions** (Track), and
re-runs the conflict evaluation when new information arrives so a still-open action
can move `WAITING_FOR_INFORMATION → READY_FOR_REVIEW` (Re-evaluate). It never
advances an action to `COMPLETED` on its own — that only comes from an approved
Action Tool execution or a human. The flow is deterministic and offline, so the
whole loop (including the Zoo Field Trip Example Scenario) runs in CI without
Gemini/Vertex or Firestore credentials; the ADK `LlmAgent` in `pcca.root_agent`
is the interactive entry point exposing the same tools.

## Architecture

```
                 ADK Root Agent            (orchestration only — NOT source of truth)
                       │
        ┌──────────────┼──────────────┐
        ↓              ↓              ↓
  Document Tool   Conflict Tool   Action Tools
                                   ├─ Calendar
                                   ├─ Reminder
                                   └─ Gmail Draft
                       │
                       ↓
                   Firestore
              Context / Actions          (persistent source of truth)
```

- **ADK Root Agent** — orchestrates the workflow (tool selection, ordering,
  clarification, planning, human approval, re-evaluation). It never holds the
  source of truth; facts and action state come from Firestore. Uses **Gemini via
  Vertex AI**.
- **Document Tool** — turns school documents (PDF / image / newsletter / notice /
  lunch / schedule / text) into structured School Information. Never fabricates
  missing values — unparseable data stays `Unknown`. Keeps evidence & source.
- **Conflict Tool** — reconciles structured School Information against Personal
  Child Context. Prefers **deterministic logic** (e.g. time-overlap) over the LLM.
  Returns one of four classifications plus evidence.
- **Action Tools** — Calendar (dedup-protected), Reminder, Gmail **Draft** (never
  auto-sent; human-in-the-loop). Human approval + idempotency. Executes against an
  injectable `ActionExecutor`: the default `MockActionExecutor` is fully offline;
  set `PCCA_ACTION_EXECUTOR=google` to reflect approved actions into real Google
  Calendar / Gmail drafts / Tasks (SOT-2799) — Gmail stays draft-only, no send path.
- **Firestore** — persistent source of truth for `ChildContext`,
  `SchoolInformation`, `Actions`.

### Conflict classifications

| Classification | Meaning |
| --- | --- |
| `CONFIRMED_RELEVANCE` | An explicit relevance/conflict exists. |
| `INFORMATION_MISSING` | School-side information needed to evaluate is missing. |
| `CLARIFICATION_REQUIRED` | Personal Context is unconfirmed, stale, or ambiguous. |
| `NO_RELEVANT_MATCH_FOUND` | No relevant item found from current evidence. **Not** "safe / no risk". |

### Personal Context model

`known_present` · `explicitly_absent` · `unknown`. `unknown` is **never** treated
as `explicitly_absent`.

## Safety boundaries

- Makes **no** medical judgements; never asserts "safe" / "can eat" / "no risk".
- States missing information explicitly; `unknown` is not treated as safe.
- Keeps evidence for every conflict and action; considers Personal Context
  freshness and detects stale context and inter-document contradictions.
- No unsupported medical generalisation from general knowledge — only relates
  facts explicitly present in Personal Context.
- Personal Context changes and external actions require **human approval**; Gmail
  is draft-only. Minimises stored personal/health data and avoids logging it.

## Status

Bootstrap skeleton (SOT-2738) with the Firestore persistence layer & data models
in place (SOT-2739): `ChildContext` / `SchoolInformation` / `Action` models, the
Personal Context Model (`known_present` / `explicitly_absent` / `unknown`, where
`unknown` is never treated as `explicitly_absent`), the `ActionStatus` enum, and an
idempotency-key-guarded repository with both in-memory and Firestore backends
(`PCCA_PERSISTENCE=memory|firestore`). Tools are still interface stubs; the
deterministic Conflict logic, Document extraction, Action execution, and the
evaluation dataset are implemented in follow-up issues (SOT-2740 … SOT-2744).

## Development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
ruff check . && mypy src && pytest       # CI runs the same
```

See `.env.example` for configuration (no real secrets are committed).

## Serving layer & Cloud Run deploy (SOT-2794)

A FastAPI backend (`src/pcca/api/`) exposes the deterministic flow over HTTP,
following the おたよりナビ (`toddler-private-rag`) backend structure:

| Method & path | Purpose |
| --- | --- |
| `GET /health` | Unauthenticated Cloud Run startup/liveness probe → `{"status":"ok"}` |
| `POST /api/auth/session` | email+password → Firebase Identity Toolkit REST → allow-list → signed session cookie |
| `POST /api/auth/logout` · `GET /api/auth/me` | End / introspect the session |
| `POST /api/documents:process` | Run Detect→…→Track for one document; returns the evidence-backed `FlowResult` |
| `POST /api/actions:reevaluate` | Re-evaluate a child's pending actions |
| `GET/PUT /api/children/{child_id}/context` | Read / replace the child's Personal Context |
| `GET /api/children/{child_id}/actions` | List the child's tracked actions |

**Auth:** every route except `/health` and `/api/auth/*` requires a valid session
cookie. The cookie is `<owner_id>.<issued_at>.<hmac>` signed with `AUTH_SECRET`
(`owner_id = sha256(email)`); `ALLOWED_USER_EMAILS` gates who may sign in. The
serving layer keeps every safety invariant intact — no medical judgement, `unknown`
never treated as safe, unapproved actions are tracked but never executed, and
Evidence is retained on every response.

Run locally:

```bash
pip install -e ".[serving]"
AUTH_SECRET=$(python -c "import secrets;print(secrets.token_urlsafe(48))") \
ALLOWED_USER_EMAILS=you@example.com \
uvicorn pcca.api.app:app --host 0.0.0.0 --port 8080
curl -s localhost:8080/health          # {"status":"ok"}
```

Deploy to Cloud Run (`sota-app-hub` / `asia-northeast1`, co-located with the
Firestore from SOT-2739 to avoid cross-project IAM). One-time prerequisites:

```bash
# 1. Enable the required APIs on the project.
gcloud services enable run.googleapis.com cloudbuild.googleapis.com \
  secretmanager.googleapis.com artifactregistry.googleapis.com \
  aiplatform.googleapis.com --project=sota-app-hub

# 2. Create the secrets (values are yours — Firebase Web API key comes from your
#    Firebase project's web app; AUTH_SECRET is a strong random string).
printf '%s' "$(python -c 'import secrets;print(secrets.token_urlsafe(48))')" \
  | gcloud secrets create pcca-auth-secret --data-file=- --project=sota-app-hub
printf '%s' "you@example.com" \
  | gcloud secrets create pcca-allowed-emails --data-file=- --project=sota-app-hub
printf '%s' "<firebase-web-api-key>" \
  | gcloud secrets create pcca-firebase-api-key --data-file=- --project=sota-app-hub

# 3. Deploy (Cloud Build builds the Dockerfile and pushes the image).
GCP_PROJECT_ID=sota-app-hub bash scripts/deploy_cloudrun.sh
```

The deploy sets `PCCA_PERSISTENCE=firestore` and `GOOGLE_GENAI_USE_VERTEXAI=true`
(Firestore + Gemini via ADC — no API keys in the image) and prints the service URL;
verify with `curl -fsS <url>/health`.

### Automated deploy — gated canary + auto-rollback (SOT-2802)

`.github/workflows/deploy-cloudrun.yml` promotes `scripts/deploy_cloudrun.sh` to
CI/CD, following the おたよりナビ structure:

- **Gated on CI** — triggers via `workflow_run` only after the **CI** workflow
  succeeds on `main` (a failing ruff/mypy/pytest blocks the deploy); `workflow_dispatch`
  stays for manual deploys.
- **Keyless (WIF)** — authenticates with **Workload Identity Federation**; no
  service-account JSON key is stored in the repo. Provisioned by
  `infra/terraform/wif.tf` (see that README for the GitHub secrets to set).
- **Canary + rollback** — deploys the new revision with `--no-traffic --tag canary`,
  health-checks the canary's `/health` tag URL (retried for cold-start), then either
  promotes it to 100 % traffic or removes the canary and **fails the job** so
  production keeps serving the previous revision.

Terraform (`infra/terraform/`, SOT-2803) codifies the infra including the WIF setup.

## Login setup — first real sign-in (SOT-2801)

`/api/auth/session` verifies email/password server-side against **Firebase Identity
Toolkit REST**, so a sign-in only works once a Firebase user exists and the two
auth secrets match. After the Cloud Run deploy above, complete these one-time steps
to make a real login work (`<url>` = the deployed service URL from the deploy step).

**1. Enable the email/password provider** in the Firebase project (`sota-app-hub`):
Firebase Console → *Authentication* → *Sign-in method* → enable **Email/Password**.

**2. Create the user** (the human owns the real address + password — never commit or
log it). Either in the Console (*Authentication → Users → Add user*), or with the
Firebase CLI / Admin SDK, e.g.:

```bash
# Admin SDK (service-account credentials required). Set a strong password interactively.
python - <<'PY'
import getpass, firebase_admin
from firebase_admin import auth
firebase_admin.initialize_app()  # uses GOOGLE_APPLICATION_CREDENTIALS / ADC
auth.create_user(email="you@example.com", password=getpass.getpass("New password: "))
print("created")
PY
```

**3. Make the secrets consistent** with that user. The allow-list must contain the
email, and the Firebase Web API key must belong to the same project (Firebase
Console → *Project settings → General → Web API Key*):

```bash
# Add/replace the allowed email(s) — comma-separated, no spaces.
printf '%s' "you@example.com" \
  | gcloud secrets versions add pcca-allowed-emails --data-file=- --project=sota-app-hub
# Point pcca-firebase-api-key at the project's Web API key if not already set.
printf '%s' "<firebase-web-api-key>" \
  | gcloud secrets versions add pcca-firebase-api-key --data-file=- --project=sota-app-hub
# The service reads secrets at startup — redeploy (or roll a new revision) to pick up changes:
GCP_PROJECT_ID=sota-app-hub bash scripts/deploy_cloudrun.sh
```

**4. Verify the real login** (allowed email → cookie → protected `200`; wrong
password → `401`; non-allow-listed email → `403`). Use the helper, which never
prints passwords:

```bash
BASE_URL=<url> LOGIN_EMAIL=you@example.com \
  WRONG_PASSWORD=definitely-wrong \
  bash scripts/login_smoke_test.sh
# expect: /health 200, session 200, /api/auth/me 200, wrong password 401
```

Manual equivalent with `curl` (cookie jar → protected route):

```bash
curl -sS -c cookies.txt -H 'Content-Type: application/json' \
  -d '{"email":"you@example.com","password":"<password>"}' \
  <url>/api/auth/session                       # -> {"success":true,...} + Set-Cookie
curl -sS -o /dev/null -w '%{http_code}\n' -b cookies.txt <url>/api/auth/me   # -> 200
```

> The user-provisioning step (2) and the live verification (4) require the human's
> real credentials and an enabled Firebase project, so they are performed by a human
> operator; this repo ships the exact steps plus `scripts/login_smoke_test.sh` to make
> that a one-command check.

Webhook sequence verification: step 1 completed.

Webhook sequence verification: step 2 completed.

Webhook sequence verification: step 3 completed.
