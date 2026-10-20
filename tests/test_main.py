import time
from typing import Any, cast

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import main
from app.config import Settings
from app.models import Intervention, PendingRequest
from app.tools import FieldTools
from app.workflow import Runtime
from tests.conftest import FAKE, TENANT, FakeClients, FakeContainer

KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
PENDING = PendingRequest(request_id="req-1", kind="function_approval", agent="WorkOrder", tool="create_work_order")
OPEN = Intervention(id="int-1", technician_id="tech-1", asset_id="P-101", status="pending_approval", pending=PENDING)
QUESTION = OPEN.model_copy(update={"id": "int-2", "status": "pending_question"})
QUESTION.pending = PENDING.model_copy(update={"kind": "user_question", "tool": None})
SUPERVISOR, TECHNICIAN = ["Copilot.Use", "supervisor"], ["Copilot.Use"]


class JWKS:
    def get_signing_key_from_jwt(self, token: str) -> Any:
        return type("Key", (), {"key": KEY.public_key()})()


def bearer(oid: str, roles: list[str]) -> dict[str, str]:
    claims = {"aud": FAKE["api_audience"], "iss": f"{main.LOGIN}/{TENANT}/v2.0", "oid": oid, "roles": roles}
    return {"Authorization": f"Bearer {jwt.encode(claims | {'exp': int(time.time()) + 60}, KEY, algorithm='RS256')}"}


@pytest.fixture
def client(settings: Settings) -> TestClient:
    interventions = FakeContainer({"int-1": OPEN.model_dump(mode="json"), "int-2": QUESTION.model_dump(mode="json")})
    fakes = FakeClients({"interventions": interventions, "audit": FakeContainer(), "assets": FakeContainer()})
    main.app.state.settings, main.app.state.jwks = settings, JWKS()
    main.app.state.runtime = Runtime(fakes, settings, FieldTools(fakes, settings), cast(Any, None))
    return TestClient(main.app)


def test_token_and_app_role_are_enforced(client: TestClient) -> None:
    assert client.get("/v1/interventions/int-1").status_code == 401
    assert client.get("/v1/interventions/int-1", headers=bearer("tech-1", [])).status_code == 403
    response = client.get("/v1/interventions/int-1", headers=bearer("tech-1", TECHNICIAN))
    assert response.status_code == 200 and response.json()["status"] == "pending_approval"
    assert response.json()["audit"] == []
    assert client.get("/v1/interventions/int-1", headers=bearer("someone-else", TECHNICIAN)).status_code == 403
    assert client.get("/healthz").status_code == 200


def test_forwarded_identity_is_honoured_only_from_the_proxy_principal(client: TestClient, settings: Settings) -> None:
    settings.proxy_principal_id = "web-proxy"
    forwarded = {"x-forwarded-user": "tech-1", "x-forwarded-roles": "supervisor"}
    proxied, direct = bearer("web-proxy", TECHNICIAN) | forwarded, bearer("someone-else", TECHNICIAN) | forwarded
    assert client.get("/v1/interventions/int-1", headers=proxied).status_code == 200
    assert client.get("/v1/interventions/int-1", headers=direct).status_code == 403


def test_separation_of_duties_is_checked_before_any_checkpoint_is_loaded(settings: Settings) -> None:
    with pytest.raises(HTTPException) as refused:
        main.authorise(settings, {"oid": "tech-1", "roles": SUPERVISOR}, OPEN, PENDING)
    assert refused.value.status_code == 403 and "may not approve its own" in refused.value.detail
    with pytest.raises(HTTPException) as not_supervisor:
        main.authorise(settings, {"oid": "sup-1", "roles": TECHNICIAN}, OPEN, PENDING)
    assert not_supervisor.value.status_code == 403
    main.authorise(settings, {"oid": "sup-1", "roles": SUPERVISOR}, OPEN, PENDING)
    question = cast(PendingRequest, QUESTION.pending)
    with pytest.raises(HTTPException):
        main.authorise(settings, {"oid": "sup-1", "roles": SUPERVISOR}, QUESTION, question)
    main.authorise(settings, {"oid": "tech-1", "roles": TECHNICIAN}, QUESTION, question)


def test_responses_route_refuses_before_resuming(client: TestClient) -> None:
    body, url = {"request_id": "req-1", "approved": True}, "/v1/interventions/int-1/responses"
    assert client.post(url, json=body, headers=bearer("tech-1", SUPERVISOR)).status_code == 403
    stale = client.post(url, json={"request_id": "old", "approved": True}, headers=bearer("sup-1", SUPERVISOR))
    assert stale.status_code == 409
    missing = client.post("/v1/interventions/missing/responses", json=body, headers=bearer("sup-1", SUPERVISOR))
    assert missing.status_code == 404
