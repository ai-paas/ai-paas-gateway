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

    def test_create_duplicate_updates_stale_mapping(self, db, sample_member):
        """중복 매핑 시 stale 데이터 업데이트 (MLOps 재설치 대응)"""
        kb1 = self._create_kb(db, sample_member.member_id, surro_id=20, name="old-kb")
        kb2 = self._create_kb(db, sample_member.member_id, surro_id=20, name="new-kb")

        assert kb2.id == kb1.id  # 같은 레코드
        assert kb2.name == "new-kb"  # 이름 업데이트됨

    def test_create_duplicate_restores_soft_deleted(self, db, sample_member):
        """소프트 삭제된 매핑에 재생성 시 복원"""
        kb = self._create_kb(db, sample_member.member_id, surro_id=25, name="deleted-kb")
        knowledge_base_crud.delete_knowledge_base_by_surro_id(
            db, 25, deleted_by=sample_member.member_id
        )

        # 삭제 확인
        active = knowledge_base_crud.get_active_knowledge_base_by_surro_id(db, 25)
        assert active is None

        # 재생성 → 복원
        restored = self._create_kb(db, sample_member.member_id, surro_id=25, name="restored-kb")
        assert restored.is_active is True
        assert restored.deleted_at is None
        assert restored.name == "restored-kb"

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
