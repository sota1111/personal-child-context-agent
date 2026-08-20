# Personal Child Context Agent — Frontend (SOT-2805)

保護者向けの React SPA。おたよりナビ（`toddler-private-rag`）の frontend 構造を踏襲し、
backend API（FastAPI, SOT-2794）に対して Child Context の編集・学校文書の投入・
Conflict/Action の確認・承認を行う。Cloud Run（nginx）で配信する。

## スタック

- React 19 + TypeScript + Vite
- react-router-dom（`/login`・`/context`・`/ingest`・`/actions`）
- Playwright e2e（backend を起動せず `/api/**` をモック）

## 画面

| ルート | 内容 |
| --- | --- |
| `/login` | email/password ログイン（backend `/api/auth/session` で署名付き cookie を取得） |
| `/context` | Child Context 編集（`known_present` / `explicitly_absent` / `unknown` の3値） |
| `/ingest` | 学校文書を投入 → FlowResult（Conflict 判定・Evidence・Planned/Tracked Action）を表示、承認して実行 |
| `/actions` | トラッキング中 Action の一覧と再評価 |

**安全方針**: UI は Evidence を常に verbatim で表示し、医療判断や安全の断定はしない。
`no_relevant_match_found`（該当なし）は「安全である」という意味では**ない**旨を明示する。

## 認証

email/password は backend が Firebase Identity Toolkit REST でサーバサイド検証し、
署名付き HMAC セッション cookie を発行する（`AUTH_SECRET` / `ALLOWED_USER_EMAILS` /
`FIREBASE_WEB_API_KEY`）。フロントは cookie を保持するだけで、パスワードやトークンは保存しない。

## 開発

```bash
npm install
npm run dev      # http://localhost:5173 （/api は http://localhost:8080 へプロキシ）
npm run lint
npm run build    # tsc -b && vite build
npm run e2e      # Playwright（ビルド成果物を preview 配信、/api はモック）
```

backend をローカルで動かす場合:

```bash
# repo ルートで
uvicorn pcca.api.app:app --host 0.0.0.0 --port 8080
```

## Cloud Run（nginx）配信

`Dockerfile` は multi-stage（node build → `nginx:alpine`, port 8080）。`nginx.conf` /
`start-nginx.sh` が `/api` を backend Cloud Run サービスへ reverse-proxy する
（same-origin で cookie が first-party になる）。

```bash
docker build -t personal-child-context-agent-frontend ./frontend
# 実行時に backend の Cloud Run URL を渡す
docker run -e BACKEND_URL="https://<backend>.a.run.app" -p 8080:8080 \
  personal-child-context-agent-frontend
```

Cloud Run へのデプロイ例:

```bash
gcloud run deploy personal-child-context-agent-frontend \
  --source ./frontend --region <region> --port 8080 \
  --set-env-vars BACKEND_URL="https://<backend>.a.run.app"
```

> 実際の Cloud Run デプロイは認証情報を要するため人手ゲート（`review=human`）で行う。
> 本リポジトリはビルド／nginx 構成と疎通契約（`/api` プロキシ）を提供する。
