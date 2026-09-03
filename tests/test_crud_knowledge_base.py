"""KnowledgeBaseCRUD 단위 테스트"""
import pytest

from app.cruds.knowledge_base import knowledge_base_crud


class TestKnowledgeBaseCRUD:
    """KnowledgeBaseCRUD 매핑 관리 테스트"""

    def _create_kb(self, db, member_id, surro_id=1, name="test-kb"):
        return knowledge_base_crud.create_knowledge_base(
            db=db,
            name=name,
            description="테스트 지식베이스",
            created_by=member_id,
            surro_knowledge_id=surro_id,
            collection_name=f"col_{surro_id}"
        )

    def test_create_knowledge_base(self, db, sample_member):
        """지식베이스 생성"""
        kb = self._create_kb(db, sample_member.member_id, surro_id=10)

        assert kb.name == "test-kb"
        assert kb.surro_knowledge_id == 10
        assert kb.created_by == sample_member.member_id
        assert kb.collection_name == "col_10"
        assert kb.is_active is True
        assert kb.deleted_at is None

    def test_create_duplicate_separates_reused_external_id(self, db, sample_member):
        """MLOps 재설치로 ID가 재사용되면 기존 소유권 이력을 분리한다."""
        kb1 = self._create_kb(db, sample_member.member_id, surro_id=20, name="old-kb")
        kb2 = self._create_kb(db, sample_member.member_id, surro_id=20, name="new-kb")

        assert kb2.id != kb1.id
        assert kb1.deleted_at is not None
        assert kb1.is_active is False
        assert kb1.deleted_by == "system:upstream-id-reused"
        assert kb2.name == "new-kb"

    def test_create_duplicate_keeps_soft_deleted_history(self, db, sample_member):
        """소프트 삭제된 숫자 ID가 재등장해도 기존 행을 복원하지 않는다."""
        kb = self._create_kb(db, sample_member.member_id, surro_id=25, name="deleted-kb")
        knowledge_base_crud.delete_knowledge_base_by_surro_id(
            db, 25, deleted_by=sample_member.member_id
        )

        # 삭제 확인
        active = knowledge_base_crud.get_active_knowledge_base_by_surro_id(db, 25)
        assert active is None

        replacement = self._create_kb(
            db, sample_member.member_id, surro_id=25, name="restored-kb"
        )
        assert replacement.id != kb.id
        assert replacement.is_active is True
        assert replacement.deleted_at is None
        assert kb.deleted_at is not None

    def test_get_knowledge_base_by_surro_id(self, db, sample_member):
        """surro_id로 조회"""
        self._create_kb(db, sample_member.member_id, surro_id=30)
        found = knowledge_base_crud.get_knowledge_base_by_surro_id(db, 30)
        assert found is not None
        assert found.surro_knowledge_id == 30

    def test_get_active_knowledge_base_by_surro_id(self, db, sample_member):
        """활성 레코드만 조회"""
        self._create_kb(db, sample_member.member_id, surro_id=40)
        knowledge_base_crud.delete_knowledge_base_by_surro_id(
            db, 40, deleted_by=sample_member.member_id
        )

        # get_knowledge_base_by_surro_id: 삭제된 것도 반환
        found_any = knowledge_base_crud.get_knowledge_base_by_surro_id(db, 40)
        assert found_any is not None

        # get_active: 삭제된 것 제외
        found_active = knowledge_base_crud.get_active_knowledge_base_by_surro_id(db, 40)
        assert found_active is None

    def test_soft_delete(self, db, sample_member):
        """소프트 삭제"""
        self._create_kb(db, sample_member.member_id, surro_id=50)
        result = knowledge_base_crud.delete_knowledge_base_by_surro_id(
            db, 50, deleted_by=sample_member.member_id
        )
        assert result is True

        kb = knowledge_base_crud.get_knowledge_base_by_surro_id(db, 50)
        assert kb.deleted_at is not None
        assert kb.deleted_by == sample_member.member_id
        assert kb.is_active is False

    def test_soft_delete_not_found(self, db):
        """존재하지 않는 레코드 삭제"""
        result = knowledge_base_crud.delete_knowledge_base_by_surro_id(db, 99999)
        assert result is False

    def test_get_knowledge_bases_member_filter(self, db, sample_member, admin_member):
        """사용자별 필터링"""
        self._create_kb(db, sample_member.member_id, surro_id=60, name="user-kb")
        self._create_kb(db, admin_member.member_id, surro_id=61, name="admin-kb")

        # sample_member 소유만 조회
        kbs, total = knowledge_base_crud.get_knowledge_bases(
            db, member_id=sample_member.member_id
        )
        assert total == 1
        assert kbs[0].name == "user-kb"

    def test_get_knowledge_bases_excludes_deleted(self, db, sample_member):
        """삭제된 레코드 목록 제외"""
        self._create_kb(db, sample_member.member_id, surro_id=70, name="active")
        self._create_kb(db, sample_member.member_id, surro_id=71, name="deleted")
        knowledge_base_crud.delete_knowledge_base_by_surro_id(
            db, 71, deleted_by=sample_member.member_id
        )

        kbs, total = knowledge_base_crud.get_knowledge_bases(
            db, member_id=sample_member.member_id
        )
        assert total == 1
        assert kbs[0].name == "active"

    def test_get_knowledge_bases_search(self, db, sample_member):
        """검색 필터"""
        self._create_kb(db, sample_member.member_id, surro_id=80, name="파이썬 가이드")
        self._create_kb(db, sample_member.member_id, surro_id=81, name="자바 매뉴얼")

        kbs, total = knowledge_base_crud.get_knowledge_bases(
            db, search="파이썬", member_id=sample_member.member_id
        )
        assert total == 1
        assert "파이썬" in kbs[0].name

    def test_get_knowledge_bases_pagination(self, db, sample_member):
        """페이지네이션"""
        for i in range(5):
            self._create_kb(db, sample_member.member_id, surro_id=90 + i, name=f"kb-{i}")

        kbs, total = knowledge_base_crud.get_knowledge_bases(
            db, skip=0, limit=3, member_id=sample_member.member_id
        )
        assert total == 5
        assert len(kbs) == 3

    def test_update_knowledge_base(self, db, sample_member):
        """지식베이스 업데이트"""
        self._create_kb(db, sample_member.member_id, surro_id=100, name="before")
        updated = knowledge_base_crud.update_knowledge_base_by_surro_id(
            db, surro_knowledge_id=100,
            name="after",
            description="새 설명",
            updated_by=sample_member.member_id
        )
        assert updated.name == "after"
        assert updated.description == "새 설명"
        assert updated.updated_by == sample_member.member_id


class TestKnowledgeBaseRouteIdContract:
    """경로 파라미터가 MLOps ID(surro_knowledge_id) 공간임을 고정한다.

    응답의 `id`(게이트웨이 PK)와 값이 겹칠 수 있어, 경로 이름이 흐려지면
    프론트가 잘못된 ID로 404를 맞는다.
    """

    def test_kb_paths_use_surro_id_param(self):
        from app.main import app

        kb_paths = [p for p in app.openapi()["paths"] if p.startswith("/api/v1/knowledge-bases/{")]
        assert kb_paths, "knowledge-bases 경로 엔드포인트가 없다"
        for path in kb_paths:
            assert "{surro_knowledge_id}" in path, path
            assert "{knowledge_base_id}" not in path, path


class TestKnowledgeBaseUpstreamErrorDetail:
    """upstream 에러 body를 그대로 넣어 detail이 이중 JSON이 되는 것을 막는다."""

    def test_json_detail_unwrapped(self):
        import httpx

        from app.services.knowledge_base_service import _upstream_error_detail

        assert _upstream_error_detail(
            httpx.Response(400, json={"detail": "Deployment not found"})
        ) == "Deployment not found"

    def test_non_json_body_falls_back(self):
        import httpx

        from app.services.knowledge_base_service import _upstream_error_detail

        assert _upstream_error_detail(httpx.Response(500, text="boom")) == "upstream request rejected"
