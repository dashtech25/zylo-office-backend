from httpx import AsyncClient
import uuid

from app.audit.models import AuditLog
from app.core.database import AsyncSessionLocal
from app.operator.audit_models import OperatorAuditLog
from sqlalchemy import select


async def test_operator_endpoints_deny_by_default(client: AsyncClient, registered_user: dict, monkeypatch):
    monkeypatch.delenv("OPERATOR_READ_USER_IDS", raising=False)
    headers = {"Authorization": f"Bearer {registered_user['accessToken']}"}
    response = await client.get("/api/v1/operator/organizations", headers=headers)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "operator_access_denied"


async def test_operator_allowlist_is_read_only_and_returns_redacted_metadata(
    client: AsyncClient, registered_user: dict, organization: dict, monkeypatch,
):
    headers = {"Authorization": f"Bearer {registered_user['accessToken']}"}
    me = await client.get("/api/v1/auth/me", headers=headers)
    monkeypatch.setenv("OPERATOR_READ_USER_IDS", me.json()["id"])

    listed = await client.get(
        "/api/v1/operator/organizations?limit=20&offset=0",
        headers={**headers, "X-Request-Id": "operator-list-audit"},
    )
    assert listed.status_code == 200
    assert organization["id"] in [row["id"] for row in listed.json()["data"]]
    assert "email" not in listed.text

    overview = await client.get(
        f"/api/v1/operator/organizations/{organization['id']}",
        headers={**headers, "X-Request-Id": "operator-org-audit"},
    )
    assert overview.status_code == 200
    assert overview.json()["organization"]["id"] == organization["id"]
    assert "members" not in overview.json()
    assert "email" not in overview.text

    health = await client.get(
        "/api/v1/operator/health", headers={**headers, "X-Request-Id": "operator-health-test"}
    )
    assert health.status_code == 200
    assert health.json() == {"status": "ok", "database": "ok", "requestId": "operator-health-test"}

    trace = await client.get(
        "/api/v1/operator/requests/no-persisted-trace",
        headers={**headers, "X-Request-Id": "operator-trace-miss"},
    )
    assert trace.status_code == 200
    assert trace.json() == {"requestId": "no-persisted-trace", "found": False, "events": []}
    assert "summary" not in trace.text

    request_id = "persisted-trace-test-1"
    async with AsyncSessionLocal() as db:
        db.add(AuditLog(
            organizationId=uuid.UUID(organization["id"]), actorUserId=uuid.UUID(me.json()["id"]),
            action="billing.invoice.create", entityType="Invoice", entityId=uuid.uuid4(),
            summary=f"Invoice created (request_id={request_id}) private-person@example.test",
            changes={"email": "private-person@example.test"},
            request_id=request_id, eventId=uuid.uuid4().hex,
        ))
        await db.commit()
    persisted_trace = await client.get(f"/api/v1/operator/requests/{request_id}", headers=headers)
    assert persisted_trace.status_code == 200
    assert persisted_trace.json()["found"] is True
    assert "private-person@example.test" not in persisted_trace.text
    assert "summary" not in persisted_trace.text

    missing_event = await client.get(
        "/api/v1/operator/payment-events/no-such-event",
        headers={**headers, "X-Request-Id": "operator-payment-miss"},
    )
    assert missing_event.status_code == 404
    assert missing_event.json()["error"]["code"] == "payment_event_not_found"

    async with AsyncSessionLocal() as db:
        audit_rows = list((await db.scalars(select(OperatorAuditLog))).all())
    by_request_id = {row.requestId: row for row in audit_rows}
    assert by_request_id["operator-list-audit"].actorUserId == uuid.UUID(me.json()["id"])
    assert by_request_id["operator-list-audit"].scope == "platform"
    assert by_request_id["operator-list-audit"].action == "organization.list"
    assert by_request_id["operator-list-audit"].outcome == "success"
    assert by_request_id["operator-org-audit"].scope == "organization"
    assert by_request_id["operator-org-audit"].targetId == uuid.UUID(organization["id"])
    assert by_request_id["operator-trace-miss"].action == "request_trace.read"
    assert by_request_id["operator-trace-miss"].outcome == "not_found"
    assert by_request_id["operator-payment-miss"].outcome == "not_found"


async def test_malformed_operator_allowlist_does_not_grant_access(
    client: AsyncClient, registered_user: dict, monkeypatch,
):
    monkeypatch.setenv("OPERATOR_READ_USER_IDS", "*,not-a-uuid")
    headers = {"Authorization": f"Bearer {registered_user['accessToken']}"}
    response = await client.get("/api/v1/operator/health", headers=headers)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "operator_access_denied"
