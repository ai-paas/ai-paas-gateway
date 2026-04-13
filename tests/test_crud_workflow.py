"""WorkflowCRUD 단위 테스트"""
import pytest
from app.cruds.workflow import workflow_crud


class TestWorkflowCRUD:
    """WorkflowCRUD 기본 CRUD 테스트"""

    def _create_wf(self, db, member_id, surro_id="wf-001", name="test-workflow"):
        return workflow_crud.create_workflow(
            db=db,
            name=name,
            description="테스트 워크플로우",
            created_by=member_id,
            surro_workflow_id=surro_id
        )

    def test_create_workflow(self, db, sample_member):
        """워크플로우 생성"""
        wf = self._create_wf(db, sample_member.member_id)

        assert wf.name == "test-workflow"
        assert wf.surro_workflow_id == "wf-001"
        assert wf.created_by == sample_member.member_id
        assert wf.description == "테스트 워크플로우"

    def test_get_workflow_by_id(self, db, sample_member):
        """내부 ID로 조회"""
        created = self._create_wf(db, sample_member.member_id, surro_id="wf-010")
        found = workflow_crud.get_workflow(db, created.id)
        assert found is not None
        assert found.surro_workflow_id == "wf-010"

    def test_get_workflow_by_surro_id(self, db, sample_member):
        """외부 ID로 조회"""
        self._create_wf(db, sample_member.member_id, surro_id="wf-020")
        found = workflow_crud.get_workflow_by_surro_id(db, "wf-020")
        assert found is not None

    def test_get_workflow_not_found(self, db):
        """존재하지 않는 워크플로우"""
        assert workflow_crud.get_workflow(db, 99999) is None
        assert workflow_crud.get_workflow_by_surro_id(db, "nonexistent") is None

    def test_get_workflows_pagination(self, db, sample_member):
        """목록 페이지네이션"""
        for i in range(5):
            self._create_wf(
                db, sample_member.member_id,
                surro_id=f"wf-page-{i}",
                name=f"workflow-{i}"
            )
        wfs, total = workflow_crud.get_workflows(db, skip=0, limit=3)
        assert total == 5
        assert len(wfs) == 3

    def test_get_workflows_search(self, db, sample_member):
        """검색 필터"""
        self._create_wf(db, sample_member.member_id, surro_id="wf-s1", name="데이터 전처리")
        self._create_wf(db, sample_member.member_id, surro_id="wf-s2", name="모델 학습")

        wfs, total = workflow_crud.get_workflows(db, search="전처리")
        assert total == 1
        assert "전처리" in wfs[0].name

    def test_get_workflows_creator_filter(self, db, sample_member, admin_member):
        """생성자 필터"""
        self._create_wf(db, sample_member.member_id, surro_id="wf-u1", name="user-wf")
        self._create_wf(db, admin_member.member_id, surro_id="wf-a1", name="admin-wf")

        wfs, total = workflow_crud.get_workflows(
            db, creator_id=sample_member.member_id
        )
        assert total == 1
        assert wfs[0].name == "user-wf"

    def test_update_workflow_by_id(self, db, sample_member):
        """내부 ID로 업데이트"""
        created = self._create_wf(db, sample_member.member_id, surro_id="wf-upd1")
        updated = workflow_crud.update_workflow(
            db, created.id,
            name="수정된 이름",
            description="수정된 설명"
        )
        assert updated.name == "수정된 이름"
        assert updated.description == "수정된 설명"

    def test_update_workflow_by_surro_id(self, db, sample_member):
        """외부 ID로 업데이트"""
        self._create_wf(db, sample_member.member_id, surro_id="wf-upd2")
        updated = workflow_crud.update_workflow_by_surro_id(
            db, "wf-upd2",
            name="새이름"
        )
        assert updated.name == "새이름"

    def test_update_workflow_partial(self, db, sample_member):
        """부분 업데이트 (이름만)"""
        created = self._create_wf(
            db, sample_member.member_id, surro_id="wf-partial"
        )
        original_desc = created.description

        updated = workflow_crud.update_workflow(db, created.id, name="only-name")
        assert updated.name == "only-name"
        assert updated.description == original_desc  # 설명은 변경 안 됨

    def test_update_workflow_not_found(self, db):
        """존재하지 않는 워크플로우 업데이트"""
        result = workflow_crud.update_workflow(db, 99999, name="nope")
        assert result is None

    def test_delete_workflow_by_id(self, db, sample_member):
        """내부 ID로 삭제"""
        created = self._create_wf(db, sample_member.member_id, surro_id="wf-del1")
        result = workflow_crud.delete_workflow(db, created.id)
        assert result is True
        assert workflow_crud.get_workflow(db, created.id) is None

    def test_delete_workflow_by_surro_id(self, db, sample_member):
        """외부 ID로 삭제"""
        self._create_wf(db, sample_member.member_id, surro_id="wf-del2")
        result = workflow_crud.delete_workflow_by_surro_id(db, "wf-del2")
        assert result is True
        assert workflow_crud.get_workflow_by_surro_id(db, "wf-del2") is None

    def test_delete_workflow_not_found(self, db):
        """존재하지 않는 워크플로우 삭제"""
        assert workflow_crud.delete_workflow(db, 99999) is False
        assert workflow_crud.delete_workflow_by_surro_id(db, "nonexistent") is False

    def test_get_workflows_ordering(self, db, sample_member):
        """목록 최신순 정렬"""
        wf1 = self._create_wf(db, sample_member.member_id, surro_id="wf-ord1", name="first")
        wf2 = self._create_wf(db, sample_member.member_id, surro_id="wf-ord2", name="second")

        wfs, _ = workflow_crud.get_workflows(db)
        # 최신순이므로 second가 먼저
        assert wfs[0].name == "second"
