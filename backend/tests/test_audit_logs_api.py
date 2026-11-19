import uuid
from datetime import date, timedelta

import pytest
from sqlalchemy import select

from app.db.seed import seed_demo_data
from app.main import app
from app.models.audit import AuditLog
from app.models.user import User
from app.services.ollama_service import get_llm
from tests.fakes import FakeLLM

URL = "/api/v1/audit-logs"
TODAY = date.today()


@pytest.fixture
def reconciled(client, finance, db):
    seed_demo_data(db)
    db.commit()
    assert client.post("/api/v1/reconciliation/run", headers=finance).status_code == 200


@pytest.fixture
def with_ai(client, finance, ops, reconciled):
    app.dependency_overrides[get_llm] = lambda: FakeLLM(down=True)
    client.post("/api/v1/ai/chat", json={"message": "Which invoices are overdue?"}, headers=finance)
    client.post("/api/v1/ai/chat", json={"message": "What is the capital of France?"}, headers=ops)
    yield
    app.dependency_overrides.pop(get_llm, None)


def get(client, headers, path="", **params):
    return client.get(f"{URL}{path}", params=params, headers=headers)


def actions(body):
    return [i["action"] for i in body["items"]]


# ======================================================================== access: Admin only


@pytest.mark.parametrize("path", ["", "/ai", "/options"])
def test_audit_logs_are_admin_only(client, finance, ops, admin, reconciled, path):
    assert client.get(f"{URL}{path}").status_code == 401
    assert get(client, finance, path).status_code == 403
    assert get(client, ops, path).status_code == 403
    assert get(client, admin, path).status_code == 200


@pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
def test_the_audit_trail_is_read_only(client, admin, method):
    for path in ("", "/ai", f"/{uuid.uuid4()}"):
        assert getattr(client, method)(f"{URL}{path}", headers=admin).status_code in (404, 405)


# ======================================================================== business activity


def test_reconciliation_run_appears_in_the_trail(client, admin, reconciled):
    body = get(client, admin, page_size=100).json()
    assert actions(body).count("PAYMENT_RECONCILED") == 20 and actions(body).count("RECONCILIATION_RUN") == 1
    run = next(i for i in body["items"] if i["action"] == "RECONCILIATION_RUN")
    assert run["user_name"] == "Farhan Finance" and run["new_values"]["processed"] == 20


def test_entries_are_newest_first_with_a_stable_order(client, admin, reconciled):
    items = get(client, admin, page_size=100).json()["items"]
    stamps = [i["created_at"] for i in items]
    assert stamps == sorted(stamps, reverse=True)


def test_filter_by_action_entity_and_user(client, admin, finance, reconciled, db):
    assert get(client, admin, action="RECONCILIATION_RUN").json()["total"] == 1
    assert get(client, admin, action="payment_reconciled").json()["total"] == 0  # exact match on the action name
    assert get(client, admin, entity_type="payment").json()["total"] == 20
    finance_id = str(db.scalar(select(User.id).where(User.email == "finance@example.com")))
    ops_id = str(db.scalar(select(User.id).where(User.email == "operations@example.com")))
    assert get(client, admin, user_id=finance_id).json()["total"] == 21
    assert get(client, admin, user_id=ops_id).json()["total"] == 0


def test_search_matches_part_of_the_action_name(client, admin, reconciled):
    assert get(client, admin, search="reconcil").json()["total"] == 21
    assert get(client, admin, search="nothing-like-this").json()["total"] == 0


def test_filter_by_entity_id(client, admin, finance, reconciled, db):
    result = client.get("/api/v1/reconciliation", params={"search": "TXN-1019"}, headers=finance).json()["items"][0]
    client.post(f"/api/v1/reconciliation/{result['id']}/reject", json={"note": "not theirs"}, headers=finance)
    body = get(client, admin, entity_id=result["id"]).json()
    assert actions(body) == ["RECONCILIATION_REJECTED"]


def test_changes_show_old_and_new_values(client, admin, finance, reconciled):
    result = client.get("/api/v1/reconciliation", params={"search": "TXN-1019"}, headers=finance).json()["items"][0]
    client.post(f"/api/v1/reconciliation/{result['id']}/reject", json={"note": "Different entity"}, headers=finance)
    entry = get(client, admin, action="RECONCILIATION_REJECTED").json()["items"][0]
    assert entry["old_values"]["status"] == "MANUAL_REVIEW" and entry["new_values"]["status"] == "UNMATCHED"
    assert entry["new_values"]["note"] == "Different entity" and entry["entity_type"] == "reconciliation_result"


def test_date_range_is_inclusive_of_both_ends(client, admin, reconciled):
    today = TODAY.isoformat()
    assert get(client, admin, date_from=today, date_to=today).json()["total"] > 0
    tomorrow = (TODAY + timedelta(days=1)).isoformat()
    assert get(client, admin, date_from=tomorrow).json()["total"] == 0
    yesterday = (TODAY - timedelta(days=1)).isoformat()
    assert get(client, admin, date_to=yesterday).json()["total"] == 0
    assert get(client, admin, date_from=yesterday, date_to=tomorrow).json()["total"] == get(client, admin).json()["total"]


def test_pagination(client, admin, reconciled):
    page = get(client, admin, page=2, page_size=10).json()
    assert page["total"] == 21 and page["pages"] == 3 and len(page["items"]) == 10
    assert get(client, admin, page=3, page_size=10).json()["items"].__len__() == 1
    first = {i["id"] for i in get(client, admin, page=1, page_size=10).json()["items"]}
    assert first.isdisjoint({i["id"] for i in page["items"]})  # no row appears on two pages


@pytest.mark.parametrize(
    "params",
    [{"user_id": "nope"}, {"entity_id": "nope"}, {"date_from": "2026-13-01"}, {"date_from": "2026-05-02", "date_to": "2026-05-01"}, {"page": 0}, {"page_size": 101}],
)
def test_invalid_filters_are_rejected(client, admin, params):
    assert get(client, admin, **params).status_code == 422


def test_an_empty_trail_is_fine(client, admin):
    body = get(client, admin).json()
    assert body["total"] == 0 and body["items"] == [] and body["pages"] == 1


def test_entries_survive_the_user_being_unknown(client, admin, db):
    db.add(AuditLog(user_id=None, action="SYSTEM_TASK", entity_type="system", entity_id=None))
    db.commit()
    item = get(client, admin).json()["items"][0]
    assert item["user_name"] is None and item["action"] == "SYSTEM_TASK"


# ======================================================================== AI requests


def test_ai_requests_are_listed_with_who_asked(client, admin, with_ai):
    body = get(client, admin, "/ai").json()
    assert body["total"] == 2
    by_text = {i["request_summary"]: i for i in body["items"]}
    asked = by_text["Which invoices are overdue?"]
    assert asked["operation_type"] == "CHAT" and asked["user_name"] == "Farhan Finance" and asked["duration_ms"] is not None
    assert asked["details"]["intent"] == "OVERDUE_INVOICES" and asked["status"] == "FALLBACK_UNAVAILABLE"
    unknown = by_text["What is the capital of France?"]
    assert unknown["user_name"] == "Olivia Operations" and unknown["status"] == "UNKNOWN" and unknown["model_name"] == "none"


def test_ai_filters(client, admin, with_ai, db):
    assert get(client, admin, "/ai", operation="CHAT").json()["total"] == 2
    assert get(client, admin, "/ai", operation="EXTRACT").json()["total"] == 0
    assert get(client, admin, "/ai", status="UNKNOWN").json()["total"] == 1
    assert get(client, admin, "/ai", search="capital").json()["total"] == 1
    ops_id = str(db.scalar(select(User.id).where(User.email == "operations@example.com")))
    assert get(client, admin, "/ai", user_id=ops_id).json()["total"] == 1
    today = TODAY.isoformat()
    assert get(client, admin, "/ai", date_from=today, date_to=today).json()["total"] == 2
    assert get(client, admin, "/ai", date_from=(TODAY + timedelta(days=1)).isoformat()).json()["total"] == 0


def test_ai_logs_never_contain_more_than_short_summaries(client, admin, with_ai):
    for item in get(client, admin, "/ai").json()["items"]:
        assert len(item["request_summary"] or "") <= 500 and len(item["response_summary"] or "") <= 2000


def test_ai_log_validation(client, admin):
    assert get(client, admin, "/ai", user_id="nope").status_code == 422
    assert get(client, admin, "/ai", date_from="2026-05-02", date_to="2026-05-01").status_code == 422


# ======================================================================== filter options


def test_options_list_what_exists(client, admin, with_ai):
    opts = get(client, admin, "/options").json()
    assert {u["name"] for u in opts["users"]} == {"Asha Admin", "Farhan Finance", "Olivia Operations"}
    assert {"PAYMENT_RECONCILED", "RECONCILIATION_RUN"} <= set(opts["actions"]) and opts["actions"] == sorted(opts["actions"])
    assert {"payment", "reconciliation"} <= set(opts["entity_types"])
    assert opts["ai_operations"] == ["CHAT"] and set(opts["ai_statuses"]) == {"FALLBACK_UNAVAILABLE", "UNKNOWN"}


def test_options_on_an_empty_system(client, admin):
    opts = get(client, admin, "/options").json()
    assert len(opts["users"]) == 3 and opts["actions"] == [] and opts["ai_operations"] == []
