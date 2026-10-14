import os, tempfile
os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "t.db"); os.environ["GROQ_API_KEY"] = ""
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app import rules
H = lambda i: {"X-User-Id": str(i)}   # 1 analyst, 3 manager, 4 controller, 5 viewer
@pytest.fixture(scope="module")
def cl():
    with TestClient(app) as c: yield c
def first(cl, cat): return next(e for e in cl.get("/api/exceptions", headers=H(4)).json() if e["category"] == cat)
def test_dashboard_and_synthetic_label(cl):
    assert "SYNTHETIC" in cl.get("/api/health").json()["data"]
    k = cl.get("/api/dashboard", headers=H(4)).json()["kpis"]; assert k["unapplied_cash"] > 0 and 0 <= k["close_readiness"] <= 100
def test_repeatable_data(cl):
    n = len(cl.get("/api/exceptions", headers=H(4)).json()); from app.db import init_db; init_db(force=True)
    assert len(cl.get("/api/exceptions", headers=H(4)).json()) == n
def test_priority_score_orders_by_risk():
    import datetime as dt
    assert rules.score("Carrier Settlement", 50000, 60, rules.AS_OF) > rules.score("Commission Variance", 100, 1, rules.AS_OF + dt.timedelta(days=20))
def test_analysis_separates_facts_from_hypotheses(cl):
    a = cl.get(f"/api/exceptions/{first(cl,'Unapplied Cash')['id']}/analysis", headers=H(1)).json()
    assert a["verified_facts"] and all(h["verified"] is False for h in a["hypotheses"])
def test_viewer_cannot_assign(cl):
    assert cl.post(f"/api/exceptions/{first(cl,'Unapplied Cash')['id']}/assign", json={"owner": "Priya Nair"}, headers=H(5)).status_code == 403
def test_resolve_requires_approval_and_only_controller_approves(cl):
    eid = first(cl, "Unapplied Cash")["id"]
    assert cl.post(f"/api/exceptions/{eid}/status", json={"status": "Resolved"}, headers=H(1)).status_code == 409
    assert cl.post(f"/api/exceptions/{eid}/approvals", json={"action_type": "ledger_posting"}, headers=H(1)).status_code == 200
    aid = cl.get("/api/approvals", headers=H(1)).json()[0]["id"]
    assert cl.post(f"/api/approvals/{aid}/decide", json={"approve": True}, headers=H(3)).status_code == 403
    assert cl.post(f"/api/approvals/{aid}/decide", json={"approve": True}, headers=H(4)).status_code == 200
    assert cl.post(f"/api/exceptions/{eid}/status", json={"status": "Resolved"}, headers=H(1)).status_code == 200
def test_audit_trail_records_actions(cl):
    acts = {a["action"] for a in cl.get("/api/audit", headers=H(4)).json()}; assert {"DENIED", "BLOCKED", "APPROVAL_APPROVED"} <= acts
def test_copilot_grounded_fallback(cl):
    r = cl.post("/api/copilot", json={"question": "What cash remains unapplied?"}, headers=H(1)).json()
    assert r["evidence"] and r["assumptions"] and 0 < r["confidence"] <= 1
