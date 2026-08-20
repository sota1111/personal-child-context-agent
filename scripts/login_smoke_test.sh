#!/usr/bin/env bash
set -euo pipefail

# Real login smoke test for the Personal Child Context Agent backend (SOT-2801).
#
# Verifies the deployed auth flow end-to-end against a live service URL:
#   1. An allow-listed email + correct password -> POST /api/auth/session issues a
#      session cookie, and a protected route returns 200 with that cookie.
#   2. An allow-listed email + WRONG password  -> 401.
#   3. A non-allow-listed email + valid Firebase password -> 403.
#
# It never stores or prints passwords. Prerequisites the human must satisfy first
# (see README "Login setup"): Firebase Auth email/password provider enabled, the
# target user created, and the pcca-allowed-emails / pcca-firebase-api-key secrets
# consistent with that user.
#
# Usage:
#   BASE_URL=https://<service>.a.run.app \
#   LOGIN_EMAIL=you@example.com LOGIN_PASSWORD=... \
#   [WRONG_PASSWORD=nope] [FORBIDDEN_EMAIL=stranger@example.com] \
#   [CHILD_ID=demo-child] \
#   bash scripts/login_smoke_test.sh
#
# Passwords may also be supplied interactively (prompted, never echoed) if the
# corresponding env var is unset.

BASE_URL="${BASE_URL:?BASE_URL is required (e.g. https://<service>.a.run.app)}"
LOGIN_EMAIL="${LOGIN_EMAIL:?LOGIN_EMAIL is required (an allow-listed email)}"
BASE_URL="${BASE_URL%/}"

# Route used for the authenticated 200 check. /api/auth/me depends on the same
# get_current_user gate as every protected route and needs no pre-existing data.
PROTECTED_PATH="${PROTECTED_PATH:-/api/auth/me}"
FORBIDDEN_EMAIL="${FORBIDDEN_EMAIL:-not-allowed@example.com}"

if [ -z "${LOGIN_PASSWORD:-}" ]; then
  read -rs -p "Password for ${LOGIN_EMAIL}: " LOGIN_PASSWORD && echo
fi

pass=0
fail=0
note() { printf '  %s\n' "$1"; }
ok()   { printf 'PASS  %s\n' "$1"; pass=$((pass + 1)); }
bad()  { printf 'FAIL  %s\n' "$1"; fail=$((fail + 1)); }

# json_login EMAIL PASSWORD COOKIE_JAR -> echoes the HTTP status code.
json_login() {
  local email="$1" password="$2" jar="$3"
  # Password is passed via a file to keep it off the process argv / logs.
  local body
  body=$(python3 - "$email" "$password" <<'PY'
import json, sys
print(json.dumps({"email": sys.argv[1], "password": sys.argv[2]}))
PY
)
  curl -sS -o /dev/null -w '%{http_code}' \
    -c "$jar" \
    -H 'Content-Type: application/json' \
    -d "$body" \
    "${BASE_URL}/api/auth/session"
}

echo "== Login smoke test against ${BASE_URL} =="

# 0. Liveness: /health must be 200 and unauthenticated.
health=$(curl -sS -o /dev/null -w '%{http_code}' "${BASE_URL}/health" || echo "000")
if [ "$health" = "200" ]; then ok "/health -> 200 (unauthenticated)"; else bad "/health -> ${health} (expected 200)"; fi

# 1. Happy path: allow-listed email + correct password -> cookie -> protected 200.
jar=$(mktemp)
trap 'rm -f "$jar"' EXIT
login_code=$(json_login "$LOGIN_EMAIL" "$LOGIN_PASSWORD" "$jar")
if [ "$login_code" = "200" ]; then
  ok "POST /api/auth/session (allowed email + correct password) -> 200"
  prot=$(curl -sS -o /dev/null -w '%{http_code}' -b "$jar" "${BASE_URL}${PROTECTED_PATH}")
  if [ "$prot" = "200" ]; then ok "GET ${PROTECTED_PATH} with session cookie -> 200"; else bad "GET ${PROTECTED_PATH} with cookie -> ${prot} (expected 200)"; fi
else
  bad "POST /api/auth/session (allowed email + correct password) -> ${login_code} (expected 200)"
  note "Check: user exists in Firebase Auth, email is in pcca-allowed-emails, pcca-firebase-api-key is correct."
fi

# 2. Wrong password for an allow-listed email -> 401.
if [ -n "${WRONG_PASSWORD:-}" ]; then
  code=$(json_login "$LOGIN_EMAIL" "$WRONG_PASSWORD" "$(mktemp)")
  if [ "$code" = "401" ]; then ok "wrong password -> 401"; else bad "wrong password -> ${code} (expected 401)"; fi
else
  note "SKIP wrong-password check (set WRONG_PASSWORD to run it)"
fi

# 3. Non-allow-listed email -> 403 (requires a real Firebase password for that email).
if [ -n "${FORBIDDEN_PASSWORD:-}" ]; then
  code=$(json_login "$FORBIDDEN_EMAIL" "$FORBIDDEN_PASSWORD" "$(mktemp)")
  if [ "$code" = "403" ]; then ok "non-allow-listed email (${FORBIDDEN_EMAIL}) -> 403"; else bad "non-allow-listed email -> ${code} (expected 403)"; fi
else
  note "SKIP forbidden-email check (set FORBIDDEN_EMAIL + FORBIDDEN_PASSWORD to run it)"
fi

echo "== ${pass} passed, ${fail} failed =="
[ "$fail" -eq 0 ]
