"""AuditLog 모델 + audit_service.log_audit() sanity 테스트."""
from app.models.audit_log import AuditLog
from app.services.audit_service import log_audit


def test_audit_log_columns_exist():
    """DB 컬럼명 sanity — JSON 컬럼은 DB에서 'metadata'로 저장."""
    cols = {c.name for c in AuditLog.__table__.columns}
    expected = {
        "id", "action", "resource_type", "resource_id",
        "actor_member_id", "target_member_id",
        "metadata", "request_id", "ip", "created_at",
    }
    assert expected.issubset(cols)


def test_audit_log_python_attribute_is_metadata_json():
    """Python 속성은 Base.metadata 충돌 회피를 위해 metadata_json."""
    assert hasattr(AuditLog, "metadata_json")
    # 컬럼 객체의 실제 name 은 metadata
    assert AuditLog.metadata_json.property.columns[0].name == "metadata"


def test_audit_log_indexes_declared():
    """필수 인덱스가 선언됐는지."""
    indexes = {idx.name for idx in AuditLog.__table__.indexes}
    assert "idx_audit_created_at" in indexes
    assert "idx_audit_resource" in indexes
    assert "idx_audit_actor" in indexes
    assert "idx_audit_request_id" in indexes


def test_log_audit_inserts_record(db, sample_member):
    record = log_audit(
        db,
        action="create",
        resource_type="service",
        actor_member_id=sample_member.member_id,
        resource_id="srv-123",
        metadata={"name": "test service"},
        request_id="req-abc",
        ip="127.0.0.1",
    )
    db.flush()

    assert record.id is not None
    assert record.action == "create"
    assert record.resource_type == "service"
    assert record.resource_id == "srv-123"
    assert record.actor_member_id == sample_member.member_id
    assert record.metadata_json == {"name": "test service"}
    assert record.request_id == "req-abc"


def test_log_audit_minimal_optional_fields(db, sample_member):
    """선택 필드 생략 가능."""
    record = log_audit(
        db,
        action="login",
        resource_type="member",
        actor_member_id=sample_member.member_id,
    )
    db.flush()
    assert record.resource_id is None
    assert record.target_member_id is None
    assert record.metadata_json is None
    assert record.request_id is None


def test_log_audit_query_by_actor(db, sample_member, admin_member):
    """actor_member_id 기반 조회 가능 — 인덱스 검증 보조."""
    log_audit(db, action="create", resource_type="model",
              actor_member_id=sample_member.member_id)
    log_audit(db, action="update", resource_type="model",
              actor_member_id=admin_member.member_id)
    db.flush()

    sample_logs = db.query(AuditLog).filter(
        AuditLog.actor_member_id == sample_member.member_id
    ).all()
    assert len(sample_logs) == 1
    assert sample_logs[0].action == "create"
