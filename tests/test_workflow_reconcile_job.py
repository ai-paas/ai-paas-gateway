"""워크플로우 매핑 reconcile 잡 — 목록을 받는 동안 만든 워크플로우를 지우지 않는다.

잡은 MLOps 전체 목록을 받은 뒤 DB 활성 매핑을 읽어, 목록에 없는 매핑을 soft-delete 한다.
목록을 받은 뒤 사용자가 만든 워크플로우는 목록에 없을 뿐 사라진 것이 아니다. 지우면 다음 목록
조회에서 admin 소유로 자동 등록되어 만든 사람이 403 을 받는다.
"""
from datetime import datetime, timedelta
from types import SimpleNamespace

from app.cruds.workflow import workflow_crud
from app.models.workflow import Workflow
from app.scheduler import job_reconcile_workflow_mappings


def test_reconcile_keeps_workflow_created_during_fetch(db, sample_member, monkeypatch):
    for sid in ("wf-keep", "wf-gone"):
        wf = workflow_crud.create_workflow(
            db=db, name=sid, description=None,
            created_by=sample_member.member_id, surro_workflow_id=sid,
        )
        # Windows 의 utcnow 해상도에서는 잡의 fetched_at 과 같은 값이 찍혀 정리 대상에서 빠질 수 있다
        wf.created_at = datetime.utcnow() - timedelta(minutes=1)
    db.commit()

    class FakeWorkflowService:
        async def get_workflows(self, page=None, page_size=None):
            # 목록 스냅샷 이후 사용자가 워크플로우를 만들어 매핑까지 커밋했다
            workflow_crud.create_workflow(
                db=db, name="new", description=None,
                created_by=sample_member.member_id, surro_workflow_id="wf-new",
            )
            return [SimpleNamespace(id="wf-keep")]

        async def close(self):
            return None

    monkeypatch.setattr(db, "close", lambda: None)
    monkeypatch.setattr("app.scheduler.SessionLocal", lambda: db)
    monkeypatch.setattr("app.services.workflow_service.WorkflowService", FakeWorkflowService)

    job_reconcile_workflow_mappings()

    state = {
        w.surro_workflow_id: w.deleted_at is None
        for w in db.query(Workflow).filter(
            Workflow.surro_workflow_id.in_(["wf-keep", "wf-gone", "wf-new"])
        )
    }
    assert state == {"wf-keep": True, "wf-gone": False, "wf-new": True}
