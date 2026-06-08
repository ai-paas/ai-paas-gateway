from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.auth import get_current_user
from app.database import get_db
from app.main import app
from app.models.service import Service
from app.schemas.service import (
    ExternalServiceDetailResponse,
    MonitoringMetrics,
    ServiceMonitoringData,
)


@contextmanager
def _client_with_overrides(db, current_user):
    def override_get_db():
        yield db

    def override_get_current_user():
        return current_user

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()


def test_service_detail_accepts_upstream_creator_without_password(
    db, sample_member, monkeypatch
):
    surro_service_id = "87cded99-326a-4b6b-a2e2-71944cf89d02"
    db.add(
        Service(
            name="aipaas-gw-test-service",
            description="gateway test",
            tags=["test", "gateway"],
            created_by=sample_member.member_id,
            surro_service_id=surro_service_id,
        )
    )
    db.flush()

    upstream_payload = {
        "created_at": "2026-04-14T20:28:55",
        "updated_at": "2026-04-14T20:28:55",
        "created_by": None,
        "updated_by": None,
        "id": surro_service_id,
        "name": "aipaas-gw-test-service",
        "description": "gateway test",
        "tags": ["test", "gateway"],
        "creator_id": 1,
        "creator": {
            "created_at": "2026-04-29T13:57:05",
            "updated_at": "2026-04-29T13:57:05",
            "created_by": "",
            "updated_by": "",
            "id": 1,
            "username": "surromind",
            "name": "surromind",
        },
        "workflows": [],
        "monitoring_data": {
            "total_metrics": {
                "1h": {
                    "message_count": 0,
                    "active_users": 0,
                    "token_usage": 0,
                    "avg_interaction_count": 0,
                    "response_time_ms": None,
                    "error_count": 0,
                    "success_rate": None,
                },
                "1d": {
                    "message_count": 0,
                    "active_users": 0,
                    "token_usage": 0,
                    "avg_interaction_count": 0,
                    "response_time_ms": None,
                    "error_count": 0,
                    "success_rate": None,
                },
                "1w": {
                    "message_count": 0,
                    "active_users": 0,
                    "token_usage": 0,
                    "avg_interaction_count": 0,
                    "response_time_ms": None,
                    "error_count": 0,
                    "success_rate": None,
                },
            },
            "workflow_metrics": [],
            "aggregated_at": "2026-05-19T05:22:45.412069",
        },
    }

    async def fake_get_service(service_id, user_info=None):
        assert service_id == surro_service_id
        return ExternalServiceDetailResponse(**upstream_payload)

    monkeypatch.setattr("app.routes.service.service_service.get_service", fake_get_service)

    with _client_with_overrides(db, sample_member) as client:
        response = client.get(f"/api/v1/services/{surro_service_id}")

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["surro_service_id"] == surro_service_id
    assert data["workflow_count"] == 0
    # 데이터(요청)가 없는 기간이라 success_rate는 명세상 null이어야 함
    assert data["monitoring_data"]["total_metrics"]["1h"]["success_rate"] is None
    assert data["monitoring_data"]["total_metrics"]["1d"]["success_rate"] is None
    assert data["monitoring_data"]["total_metrics"]["1w"]["success_rate"] is None
    # 카운트/합산 메트릭은 0
    assert data["monitoring_data"]["total_metrics"]["1h"]["message_count"] == 0
    assert data["monitoring_data"]["aggregated_at"] == "2026-05-19T05:22:45.412069"


def _make_service_payload(surro_service_id, creator_override, service_timestamps=None):
    created_at = "2026-04-14T20:28:55" if service_timestamps is None else service_timestamps.get("created_at")
    updated_at = "2026-04-14T20:28:55" if service_timestamps is None else service_timestamps.get("updated_at")
    return {
        "created_at": created_at,
        "updated_at": updated_at,
        "created_by": None,
        "updated_by": None,
        "id": surro_service_id,
        "name": "aipaas-gw-test-service",
        "description": "gateway test",
        "tags": ["test", "gateway"],
        "creator_id": 1,
        "creator": creator_override,
        "workflows": [],
        "monitoring_data": {
            "total_metrics": {
                "1h": {
                    "message_count": 0,
                    "active_users": 0,
                    "token_usage": 0,
                    "avg_interaction_count": 0,
                    "response_time_ms": None,
                    "error_count": 0,
                    "success_rate": None,
                },
                "1d": {
                    "message_count": 0,
                    "active_users": 0,
                    "token_usage": 0,
                    "avg_interaction_count": 0,
                    "response_time_ms": None,
                    "error_count": 0,
                    "success_rate": None,
                },
                "1w": {
                    "message_count": 0,
                    "active_users": 0,
                    "token_usage": 0,
                    "avg_interaction_count": 0,
                    "response_time_ms": None,
                    "error_count": 0,
                    "success_rate": None,
                },
            },
            "workflow_metrics": [],
            "aggregated_at": "2026-05-19T05:22:45.412069",
        },
    }


def test_service_detail_accepts_creator_with_null_timestamps(
    db, sample_member, monkeypatch
):
    """MLOps UserBriefSchema는 created_at/updated_at이 nullable. null이어도 통과해야 함."""
    surro_service_id = "87cded99-326a-4b6b-a2e2-71944cf89d02"
    db.add(
        Service(
            name="aipaas-gw-test-service",
            description="gateway test",
            tags=["test", "gateway"],
            created_by=sample_member.member_id,
            surro_service_id=surro_service_id,
        )
    )
    db.flush()

    upstream_payload = _make_service_payload(
        surro_service_id,
        creator_override={
            "created_at": None,
            "updated_at": None,
            "created_by": None,
            "updated_by": None,
            "id": 1,
            "username": "upstream-admin",
            "name": "upstream-admin",
        },
    )

    async def fake_get_service(service_id, user_info=None):
        return ExternalServiceDetailResponse(**upstream_payload)

    monkeypatch.setattr("app.routes.service.service_service.get_service", fake_get_service)

    with _client_with_overrides(db, sample_member) as client:
        response = client.get(f"/api/v1/services/{surro_service_id}")

    assert response.status_code == 200, response.text


SENSITIVE_KEY = "pass" + "word"  # split to avoid secret-scanning false positives
SENSITIVE_VALUE = "leak-canary-token"


def test_service_detail_drops_sensitive_key_if_upstream_leaks_it(
    db, sample_member, monkeypatch
):
    """upstream이 실수로 민감 키를 흘려도 게이트웨이 응답에는 노출되지 않아야 함."""
    surro_service_id = "87cded99-326a-4b6b-a2e2-71944cf89d02"
    db.add(
        Service(
            name="aipaas-gw-test-service",
            description="gateway test",
            tags=["test", "gateway"],
            created_by=sample_member.member_id,
            surro_service_id=surro_service_id,
        )
    )
    db.flush()

    creator_override = {
        "created_at": "2026-04-29T13:57:05",
        "updated_at": "2026-04-29T13:57:05",
        "created_by": "",
        "updated_by": "",
        "id": 1,
        "username": "upstream-admin",
        "name": "upstream-admin",
    }
    creator_override[SENSITIVE_KEY] = SENSITIVE_VALUE
    upstream_payload = _make_service_payload(surro_service_id, creator_override)

    async def fake_get_service(service_id, user_info=None):
        return ExternalServiceDetailResponse(**upstream_payload)

    monkeypatch.setattr("app.routes.service.service_service.get_service", fake_get_service)

    with _client_with_overrides(db, sample_member) as client:
        response = client.get(f"/api/v1/services/{surro_service_id}")

    assert response.status_code == 200, response.text
    body = response.text
    assert SENSITIVE_VALUE not in body
    assert SENSITIVE_KEY not in body.lower()


def test_service_detail_rejects_non_owner_non_admin(
    db, sample_member, admin_member, monkeypatch
):
    """다른 사용자가 소유한 service를 일반 사용자가 조회하면 403."""
    surro_service_id = "87cded99-326a-4b6b-a2e2-71944cf89d02"
    db.add(
        Service(
            name="aipaas-gw-test-service",
            description="gateway test",
            tags=["test"],
            created_by=admin_member.member_id,  # 소유자는 admin
            surro_service_id=surro_service_id,
        )
    )
    db.flush()

    upstream_called = {"flag": False}

    async def fake_get_service(service_id, user_info=None):
        upstream_called["flag"] = True
        return None

    monkeypatch.setattr(
        "app.routes.service.service_service.get_service", fake_get_service
    )

    # sample_member(role=user)가 admin 소유 service 조회 시도
    with _client_with_overrides(db, sample_member) as client:
        response = client.get(f"/api/v1/services/{surro_service_id}")

    assert response.status_code == 403
    # 권한 거부 시 upstream 호출이 일어나선 안 됨
    assert upstream_called["flag"] is False


def test_service_detail_admin_bypasses_ownership(
    db, sample_member, admin_member, monkeypatch
):
    """admin은 다른 사용자가 소유한 service도 조회 가능."""
    surro_service_id = "87cded99-326a-4b6b-a2e2-71944cf89d02"
    db.add(
        Service(
            name="aipaas-gw-test-service",
            description="gateway test",
            tags=["test"],
            created_by=sample_member.member_id,  # 일반 사용자 소유
            surro_service_id=surro_service_id,
        )
    )
    db.flush()

    upstream_payload = _make_service_payload(
        surro_service_id,
        creator_override={"id": 1, "username": "tester", "name": "tester"},
    )

    async def fake_get_service(service_id, user_info=None):
        return ExternalServiceDetailResponse(**upstream_payload)

    monkeypatch.setattr(
        "app.routes.service.service_service.get_service", fake_get_service
    )

    with _client_with_overrides(db, admin_member) as client:
        response = client.get(f"/api/v1/services/{surro_service_id}")

    assert response.status_code == 200, response.text


def test_service_detail_accepts_service_with_null_timestamps(
    db, sample_member, monkeypatch
):
    """MLOps ServiceBriefSchema의 required는 id/name/creator_id/creator뿐. service-level
    created_at/updated_at이 null이어도 통과해야 한다.
    """
    surro_service_id = "87cded99-326a-4b6b-a2e2-71944cf89d02"
    db.add(
        Service(
            name="aipaas-gw-test-service",
            description="gateway test",
            tags=["test", "gateway"],
            created_by=sample_member.member_id,
            surro_service_id=surro_service_id,
        )
    )
    db.flush()

    upstream_payload = _make_service_payload(
        surro_service_id,
        creator_override={
            "id": 1,
            "username": "upstream-admin",
            "name": "upstream-admin",
        },
        service_timestamps={"created_at": None, "updated_at": None},
    )

    async def fake_get_service(service_id, user_info=None):
        return ExternalServiceDetailResponse(**upstream_payload)

    monkeypatch.setattr("app.routes.service.service_service.get_service", fake_get_service)

    with _client_with_overrides(db, sample_member) as client:
        response = client.get(f"/api/v1/services/{surro_service_id}")

    assert response.status_code == 200, response.text


def test_service_detail_monitoring_period_values_passthrough(
    db, sample_member, monkeypatch
):
    """upstream의 1h/1d/1w 누적 메트릭이 게이트웨이 응답으로 그대로 전달되는지 검증.

    누적 윈도우(cumulative)이므로 일반적으로 1h ≤ 1d ≤ 1w. workflow_metrics 항목의
    metrics도 동일한 기간 구조를 가지며, success_rate/response_time_ms는 null 허용.
    """
    surro_service_id = "87cded99-326a-4b6b-a2e2-71944cf89d02"
    db.add(
        Service(
            name="aipaas-gw-test-service",
            description="gateway test",
            tags=["test"],
            created_by=sample_member.member_id,
            surro_service_id=surro_service_id,
        )
    )
    db.flush()

    workflow_id = "a64bb394-8ed6-4f3b-ab8b-52586931c2c6"
    aggregated_at = "2026-05-22T04:00:00"

    upstream_payload = _make_service_payload(
        surro_service_id,
        creator_override={"id": 1, "username": "tester", "name": "tester"},
    )
    upstream_payload["workflows"] = [
        {
            "created_at": "2026-05-12T11:33:09",
            "updated_at": "2026-05-19T17:51:51",
            "id": workflow_id,
            "name": "wf-monitoring-fixture",
            "description": None,
            "status": "DRAFT",
            "service_id": surro_service_id,
            "creator_id": 1,
            "is_template": False,
            "template_id": None,
            "category": None,
        }
    ]
    upstream_payload["monitoring_data"] = {
        "total_metrics": {
            "1h": {
                "message_count": 128,
                "active_users": 12,
                "token_usage": 45230,
                "avg_interaction_count": 3.4,
                "response_time_ms": 842.5,
                "error_count": 3,
                "success_rate": 97.6,
            },
            "1d": {
                "message_count": 2140,
                "active_users": 86,
                "token_usage": 781450,
                "avg_interaction_count": 3.9,
                "response_time_ms": 905.2,
                "error_count": 41,
                "success_rate": 98.1,
            },
            "1w": {
                "message_count": 13980,
                "active_users": 312,
                "token_usage": 5123900,
                "avg_interaction_count": 4.2,
                "response_time_ms": 887.0,
                "error_count": 205,
                "success_rate": 98.5,
            },
        },
        "workflow_metrics": [
            {
                "workflow_id": workflow_id,
                "workflow_name": "wf-monitoring-fixture",
                "metrics": {
                    "1h": {
                        "message_count": 80,
                        "active_users": 8,
                        "token_usage": 30120,
                        "avg_interaction_count": 3.1,
                        "response_time_ms": None,
                        "error_count": 2,
                        "success_rate": None,
                    },
                    "1d": {
                        "message_count": 1320,
                        "active_users": 54,
                        "token_usage": 498200,
                        "avg_interaction_count": 3.6,
                        "response_time_ms": 922.4,
                        "error_count": 22,
                        "success_rate": 98.3,
                    },
                    "1w": {
                        "message_count": 8640,
                        "active_users": 198,
                        "token_usage": 3240100,
                        "avg_interaction_count": 4.0,
                        "response_time_ms": 901.7,
                        "error_count": 120,
                        "success_rate": 98.6,
                    },
                },
                "last_updated": aggregated_at,
            }
        ],
        "aggregated_at": aggregated_at,
    }

    async def fake_get_service(service_id, user_info=None):
        return ExternalServiceDetailResponse(**upstream_payload)

    monkeypatch.setattr(
        "app.routes.service.service_service.get_service", fake_get_service
    )

    with _client_with_overrides(db, sample_member) as client:
        response = client.get(f"/api/v1/services/{surro_service_id}")

    assert response.status_code == 200, response.text
    data = response.json()
    md = data["monitoring_data"]

    # 0) upstream detail에 workflow_count 키가 없어도 len(workflows)로 보정되어 노출
    assert "workflow_count" not in upstream_payload
    assert data["workflow_count"] == 1
    assert len(data["workflows"]) == 1

    # 1) 신규 구조: period_start/period_end 사라지고 aggregated_at만 남음
    assert "period_start" not in md
    assert "period_end" not in md
    assert md["aggregated_at"] == aggregated_at

    # 2) total_metrics 기간별 키 존재
    total = md["total_metrics"]
    assert set(total.keys()) == {"1h", "1d", "1w"}
    assert total["1h"]["message_count"] == 128
    assert total["1d"]["message_count"] == 2140
    assert total["1w"]["message_count"] == 13980
    # 누적 윈도우 검증
    assert total["1h"]["message_count"] <= total["1d"]["message_count"] <= total["1w"]["message_count"]
    assert total["1h"]["response_time_ms"] == 842.5
    assert total["1w"]["success_rate"] == 98.5

    # 3) workflow_metrics 항목도 동일한 기간 구조 + null 허용
    wm = md["workflow_metrics"][0]
    assert set(wm["metrics"].keys()) == {"1h", "1d", "1w"}
    assert wm["metrics"]["1h"]["response_time_ms"] is None
    assert wm["metrics"]["1h"]["success_rate"] is None
    assert wm["metrics"]["1d"]["success_rate"] == 98.3
    assert wm["last_updated"] == aggregated_at


# ---------------------------------------------------------------------------
# workflow_count: upstream ServiceDetailSchema에는 키가 없음 (브리프에만 존재).
# 게이트웨이는 len(workflows)로 자동 보정해 노출한다.
# ---------------------------------------------------------------------------
def test_external_detail_schema_derives_workflow_count_when_key_missing():
    """스키마 레벨: upstream payload에 workflow_count 키가 없으면 len(workflows)로 채움."""
    payload = {
        "id": "87cded99-326a-4b6b-a2e2-71944cf89d02",
        "name": "svc",
        "creator_id": 1,
        "creator": {"id": 1, "username": "tester", "name": "tester"},
        "workflows": [
            {
                "id": f"a64bb394-8ed6-4f3b-ab8b-52586931c2c{i}",
                "name": f"wf-{i}",
                "status": "DRAFT",
                "is_template": False,
                "creator_id": 1,
                "created_at": "2026-05-12T11:33:09",
                "updated_at": "2026-05-19T17:51:51",
            }
            for i in range(3)
        ],
    }
    assert "workflow_count" not in payload
    parsed = ExternalServiceDetailResponse(**payload)
    assert parsed.workflow_count == 3


def test_external_detail_schema_preserves_explicit_workflow_count():
    """upstream이 미래에 workflow_count를 추가하면 그 값을 그대로 사용 (override 금지)."""
    payload = {
        "id": "87cded99-326a-4b6b-a2e2-71944cf89d02",
        "name": "svc",
        "creator_id": 1,
        "creator": {"id": 1, "username": "tester", "name": "tester"},
        "workflows": [],
        "workflow_count": 7,
    }
    parsed = ExternalServiceDetailResponse(**payload)
    assert parsed.workflow_count == 7


def test_service_detail_route_derives_workflow_count_from_workflows(
    db, sample_member, monkeypatch
):
    """route 레벨 end-to-end: upstream detail에 workflow_count 키가 없어도 응답에서 N개로 노출."""
    surro_service_id = "87cded99-326a-4b6b-a2e2-71944cf89d02"
    db.add(
        Service(
            name="aipaas-gw-test-service",
            description="gateway test",
            tags=["test"],
            created_by=sample_member.member_id,
            surro_service_id=surro_service_id,
        )
    )
    db.flush()

    upstream_payload = _make_service_payload(
        surro_service_id,
        creator_override={"id": 1, "username": "tester", "name": "tester"},
    )
    upstream_payload["workflows"] = [
        {
            "id": f"a64bb394-8ed6-4f3b-ab8b-52586931c2c{i}",
            "name": f"wf-{i}",
            "description": None,
            "status": "DRAFT",
            "service_id": surro_service_id,
            "creator_id": 1,
            "is_template": False,
            "template_id": None,
            "category": None,
            "created_at": "2026-05-12T11:33:09",
            "updated_at": "2026-05-19T17:51:51",
        }
        for i in range(3)
    ]
    assert "workflow_count" not in upstream_payload  # upstream contract 재확인

    async def fake_get_service(service_id, user_info=None):
        return ExternalServiceDetailResponse(**upstream_payload)

    monkeypatch.setattr(
        "app.routes.service.service_service.get_service", fake_get_service
    )

    with _client_with_overrides(db, sample_member) as client:
        response = client.get(f"/api/v1/services/{surro_service_id}")

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["workflow_count"] == 3
    assert len(data["workflows"]) == 3
    assert data["workflow_count"] == len(data["workflows"])


# ---------------------------------------------------------------------------
# P1: MonitoringMetrics는 1h/1d/1w required (upstream lockstep). 누락 시 검증 실패.
# ---------------------------------------------------------------------------
_PERIOD_VALID = {
    "message_count": 0,
    "active_users": 0,
    "token_usage": 0,
    "avg_interaction_count": 0.0,
    "response_time_ms": None,
    "error_count": 0,
    "success_rate": None,
}


@pytest.mark.parametrize(
    "missing_key",
    ["1h", "1d", "1w"],
)
def test_monitoring_metrics_rejects_missing_period_key(missing_key):
    """upstream이 1h/1d/1w 중 하나라도 누락하면 ValidationError. 조용한 0 채움 방지."""
    payload = {"1h": _PERIOD_VALID, "1d": _PERIOD_VALID, "1w": _PERIOD_VALID}
    del payload[missing_key]
    with pytest.raises(ValidationError) as exc_info:
        MonitoringMetrics.model_validate(payload)
    # 누락 키가 오류 메시지에 표기되는지 확인
    assert missing_key in str(exc_info.value) or missing_key in repr(exc_info.value.errors())


def test_service_detail_returns_502_on_partial_upstream_monitoring(
    db, sample_member, monkeypatch
):
    """upstream이 1d 누락한 monitoring_data를 보내면 502 BAD_GATEWAY."""
    surro_service_id = "87cded99-326a-4b6b-a2e2-71944cf89d02"
    db.add(
        Service(
            name="aipaas-gw-test-service",
            description="gateway test",
            tags=["test"],
            created_by=sample_member.member_id,
            surro_service_id=surro_service_id,
        )
    )
    db.flush()

    partial_payload = {
        "created_at": "2026-04-14T20:28:55",
        "updated_at": "2026-04-14T20:28:55",
        "id": surro_service_id,
        "name": "aipaas-gw-test-service",
        "description": "gateway test",
        "tags": ["test"],
        "creator_id": 1,
        "creator": {"id": 1, "username": "tester", "name": "tester"},
        "workflows": [],
        "monitoring_data": {
            "total_metrics": {
                "1h": _PERIOD_VALID,
                # 1d 누락 — upstream lockstep 위반
                "1w": _PERIOD_VALID,
            },
            "workflow_metrics": [],
            "aggregated_at": "2026-05-22T04:00:00",
        },
    }

    async def fake_get_service(service_id, user_info=None):
        # 실제 service_service.get_service의 흐름: response_data를 받아 schema로 파싱
        # 여기서 ValidationError가 raise되면 라우트의 except Exception → 502.
        return ExternalServiceDetailResponse(**partial_payload)

    monkeypatch.setattr(
        "app.routes.service.service_service.get_service", fake_get_service
    )

    with _client_with_overrides(db, sample_member) as client:
        response = client.get(f"/api/v1/services/{surro_service_id}")

    assert response.status_code == 502, response.text


# ---------------------------------------------------------------------------
# Hybrid 어댑터: upstream 구 spec(period_start/period_end + 평면 7필드)도 받아들임.
# upstream MLOps 신 spec 배포 전 transitional 호환을 위해.
# ---------------------------------------------------------------------------
def test_monitoring_metrics_accepts_legacy_flat_payload():
    """구 spec 평면 7필드 → 1h로 매핑, 1d/1w는 데이터 없음(0/null)."""
    legacy = {
        "message_count": 128,
        "active_users": 12,
        "token_usage": 45230,
        "avg_interaction_count": 3.4,
        "response_time_ms": 842.5,
        "error_count": 3,
        "success_rate": 97.6,
    }
    mm = MonitoringMetrics.model_validate(legacy)
    # 1h에 평면값 그대로 매핑
    assert mm.period_1h.message_count == 128
    assert mm.period_1h.token_usage == 45230
    assert mm.period_1h.response_time_ms == 842.5
    assert mm.period_1h.success_rate == 97.6
    # 1d/1w는 데이터 없음 — 카운트 0, 비율 null
    assert mm.period_1d.message_count == 0
    assert mm.period_1d.success_rate is None
    assert mm.period_1d.response_time_ms is None
    assert mm.period_1w.message_count == 0
    assert mm.period_1w.success_rate is None


def test_service_monitoring_data_maps_period_end_to_aggregated_at():
    """구 spec period_end → aggregated_at 매핑. period_start는 폐기."""
    legacy = {
        "total_metrics": {
            "message_count": 0,
            "active_users": 0,
            "token_usage": 0,
            "avg_interaction_count": 0,
            "response_time_ms": None,
            "error_count": 0,
            "success_rate": None,
        },
        "workflow_metrics": [],
        "period_start": "2026-05-22T00:00:00",
        "period_end": "2026-05-22T01:00:00",
    }
    smd = ServiceMonitoringData.model_validate(legacy)
    assert smd.aggregated_at.isoformat() == "2026-05-22T01:00:00"


def test_monitoring_metrics_partial_new_spec_still_rejected():
    """1h/1d/1w 중 일부만 있는 부분 신 spec은 여전히 ValidationError (P1 유지)."""
    partial = {
        "1h": {
            "message_count": 0, "active_users": 0, "token_usage": 0,
            "avg_interaction_count": 0, "response_time_ms": None,
            "error_count": 0, "success_rate": None,
        },
        # 1d 누락
        "1w": {
            "message_count": 0, "active_users": 0, "token_usage": 0,
            "avg_interaction_count": 0, "response_time_ms": None,
            "error_count": 0, "success_rate": None,
        },
    }
    with pytest.raises(ValidationError):
        MonitoringMetrics.model_validate(partial)


def test_service_detail_route_accepts_legacy_upstream_payload(
    db, sample_member, monkeypatch
):
    """upstream이 구 spec으로 응답해도 게이트웨이 GET /services/{id}가 200 OK.

    응답은 신 spec(1h/1d/1w + aggregated_at)으로 정규화되어 프론트에 노출.
    """
    surro_service_id = "87cded99-326a-4b6b-a2e2-71944cf89d02"
    db.add(
        Service(
            name="aipaas-gw-test-service",
            description="gateway test",
            tags=["test"],
            created_by=sample_member.member_id,
            surro_service_id=surro_service_id,
        )
    )
    db.flush()

    # upstream 실제 구 spec 페이로드 그대로
    legacy_upstream = {
        "created_at": "2026-04-20T12:11:57",
        "updated_at": "2026-04-23T12:21:09",
        "id": surro_service_id,
        "name": "test-service",
        "description": "description",
        "tags": ["test"],
        "creator_id": 1,
        "creator": {"id": 1, "username": "tester", "name": "tester"},
        "workflows": [],
        "monitoring_data": {
            "total_metrics": {
                "message_count": 0,
                "active_users": 0,
                "token_usage": 0,
                "avg_interaction_count": 0,
                "response_time_ms": None,
                "error_count": 0,
                "success_rate": None,
            },
            "workflow_metrics": [],
            "period_start": "2026-05-22T00:19:24.170533",
            "period_end": "2026-05-22T01:19:24.170533",
        },
    }

    async def fake_get_service(service_id, user_info=None):
        return ExternalServiceDetailResponse(**legacy_upstream)

    monkeypatch.setattr(
        "app.routes.service.service_service.get_service", fake_get_service
    )

    with _client_with_overrides(db, sample_member) as client:
        response = client.get(f"/api/v1/services/{surro_service_id}")

    assert response.status_code == 200, response.text
    data = response.json()
    md = data["monitoring_data"]
    # 신 spec으로 정규화되어 응답
    assert set(md["total_metrics"].keys()) == {"1h", "1d", "1w"}
    assert md["aggregated_at"].startswith("2026-05-22T01:19:24")
    # period_start/period_end는 응답에 노출 안 됨
    assert "period_start" not in md
    assert "period_end" not in md
