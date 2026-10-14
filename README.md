# Meridian Finance Command Center (prototype, synthetic data)

## Run
```bash
pip install -r requirements.txt
cd backend && uvicorn app.main:app --reload        # API on :8000 (docs: /docs), DB auto-created and seeded
cd frontend && npm install && npm run dev          # UI on :5173
cd backend && pytest -q                            # test cases
```
Put your key in `.env` (`GROQ_API_KEY`, model `qwen/qwen3-32b`). Without a key the copilot returns rule-based answers.
Switch users in the sidebar to see role-based access (viewer read-only, only controller approves).

## Architecture
`frontend` (React/Vite) -> `backend/app/main.py` (FastAPI, RBAC, audit) -> `rules.py` (detection, scoring, analysis: no LLM) and `ai.py` (copilot: SQL facts -> Groq/Qwen wording only) -> SQLite (`db.py` schema + seed, `random.Random(42)`, fixed as-of date 2026-10-14).

## Prioritisation rule
score (0-100) = amount (<=40, log scale) + age (<=25, 90 days = max) + deadline (past 25, <=3d 20, <=7d 12, else 5) + category weight (carrier 10, close 9, cash 8, commission 7, receivable 6, duplicate 4).
Critical >= 70, High >= 50, Medium >= 30, else Low.

## Exception detection
Unapplied cash (receipt without invoice), probable duplicate (same agency/payer/amount as an earlier receipt, grouped as DG-R<id>), overdue receivable (past due, balance >= $500), carrier shortfall (> 0.5% below expected), commission variance (> 2% and >= $50), blocked close task.

## API
GET /api/health, /api/users, /api/dashboard, /api/exceptions?q=&category=&severity=&status=&agency_id=, /api/exceptions/{id}, /api/exceptions/{id}/analysis, /api/approvals, /api/audit
POST /api/exceptions/{id}/assign | status | notes | notify | approvals, /api/approvals/{id}/decide, /api/copilot

## Safeguards
Roles: viewer read-only; analyst/manager/controller work exceptions; only a controller approves payment, ledger_posting, commission_change, and never their own request. Resolving cash, carrier and commission exceptions is blocked (409) without an approved request. The app never pays, posts or changes pay; approvals are recorded only. Every action, denial and block goes to a hash-chained audit log.

## Business value / success metrics
Tracked on the dashboard: duplicate alerts removed by grouping, open vs resolved exceptions, close readiness. Measure investigation time and resolution time from audit timestamps (VIEW -> STATUS Resolved), and reconciliation effort from unmatched accounts.

## Roadmap
Done: cash and receivables, carrier, commissions, close tasks (all synthetic). Next: real data import, resolved-time metrics view, SSO, email delivery of approved notifications.
