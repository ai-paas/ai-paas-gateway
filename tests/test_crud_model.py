"""ModelCRUD 단위 테스트"""
import pytest
from app.cruds.model import model_crud


class TestModelCRUD:
    """ModelCRUD 매핑 관리 테스트"""

    def test_create_model_mapping(self, db, sample_member):
        """모델 매핑 생성"""
        model = model_crud.create_model_mapping(
            db=db,
            surro_model_id=100,
            member_id=sample_member.member_id,
            model_name="test-model"
        )
        assert model.surro_model_id == 100
        assert model.created_by == sample_member.member_id
        assert model.name == "test-model"
        assert model.is_active is True
        assert model.is_catalog is False

    def test_create_model_mapping_catalog(self, db, sample_member):
        """카탈로그 모델 매핑 생성"""
        model = model_crud.create_model_mapping(
            db=db,
            surro_model_id=101,
            member_id=sample_member.member_id,
            model_name="catalog-model",
            is_catalog=True
        )
        assert model.is_catalog is True

    def test_create_model_mapping_default_name(self, db, sample_member):
        """이름 미지정 시 기본 이름"""
        model = model_crud.create_model_mapping(
            db=db,
            surro_model_id=102,
            member_id=sample_member.member_id
        )
        assert model.name == "Model_102"

    def test_get_model(self, db, sample_member):
        """내부 ID로 모델 조회"""
        created = model_crud.create_model_mapping(
            db=db, surro_model_id=200,
            member_id=sample_member.member_id,
            model_name="findable"
        )
        found = model_crud.get_model(db, created.id)
        assert found is not None
        assert found.name == "findable"

    def test_get_model_excludes_deleted(self, db, sample_member):
        """삭제된 모델은 조회 제외"""
        created = model_crud.create_model_mapping(
            db=db, surro_model_id=201,
            member_id=sample_member.member_id,
            model_name="to-delete"
        )
        model_crud.delete_model(db, created.id, sample_member.member_id)
        assert model_crud.get_model(db, created.id) is None

    def test_get_model_by_surro_id(self, db, sample_member):
        """surro_id + member_id로 조회"""
        model_crud.create_model_mapping(
            db=db, surro_model_id=300,
            member_id=sample_member.member_id,
            model_name="surro-find"
        )
        found = model_crud.get_model_by_surro_id(db, 300, sample_member.member_id)
        assert found is not None

    def test_get_model_by_surro_id_wrong_member(self, db, sample_member):
        """다른 사용자의 모델은 조회 불가"""
        model_crud.create_model_mapping(
            db=db, surro_model_id=301,
            member_id=sample_member.member_id
        )
        found = model_crud.get_model_by_surro_id(db, 301, "other-user")
        assert found is None

    def test_check_model_ownership(self, db, sample_member):
        """소유권 확인"""
        model_crud.create_model_mapping(
            db=db, surro_model_id=400,
            member_id=sample_member.member_id
        )
        assert model_crud.check_model_ownership(db, 400, sample_member.member_id) is True
        assert model_crud.check_model_ownership(db, 400, "stranger") is False

    def test_delete_model_soft(self, db, sample_member):
        """소프트 삭제"""
        created = model_crud.create_model_mapping(
            db=db, surro_model_id=500,
            member_id=sample_member.member_id
        )
        result = model_crud.delete_model(db, created.id, sample_member.member_id)
        assert result is True

        # 삭제 후 일반 조회 불가
        assert model_crud.get_model(db, created.id) is None

    def test_delete_model_mapping_by_surro_id(self, db, sample_member):
        """surro_id 기반 소프트 삭제"""
        model_crud.create_model_mapping(
            db=db, surro_model_id=501,
            member_id=sample_member.member_id
        )
        result = model_crud.delete_model_mapping(db, 501, sample_member.member_id)
        assert result is True
        assert model_crud.get_model_by_surro_id(db, 501, sample_member.member_id) is None

    def test_activate_deactivate_model(self, db, sample_member):
        """모델 활성화/비활성화"""
        created = model_crud.create_model_mapping(
            db=db, surro_model_id=600,
            member_id=sample_member.member_id
        )
        # 비활성화
        deactivated = model_crud.deactivate_model(db, created.id, sample_member.member_id)
        assert deactivated.is_active is False

        # 재활성화
        activated = model_crud.activate_model(db, created.id, sample_member.member_id)
        assert activated.is_active is True

    def test_get_models_by_member_id(self, db, sample_member):
        """사용자별 모델 ID 목록"""
        for i in range(3):
            model_crud.create_model_mapping(
                db=db, surro_model_id=700 + i,
                member_id=sample_member.member_id
            )
        ids = model_crud.get_models_by_member_id(db, sample_member.member_id)
        assert len(ids) == 3
        assert all(isinstance(id_, int) for id_ in ids)

    def test_count_models_by_member_id(self, db, sample_member):
        """사용자별 모델 카운트"""
        for i in range(4):
            model_crud.create_model_mapping(
                db=db, surro_model_id=800 + i,
                member_id=sample_member.member_id
            )
        assert model_crud.count_models_by_member_id(db, sample_member.member_id) == 4

    def test_catalog_models_paginated(self, db, sample_member):
        """카탈로그 모델 페이지네이션"""
        for i in range(5):
            model_crud.create_model_mapping(
                db=db, surro_model_id=900 + i,
                member_id=sample_member.member_id,
                model_name=f"catalog-{i}",
                is_catalog=True
            )
        models = model_crud.get_catalog_models_paginated(db, skip=0, limit=3)
        assert len(models) == 3
        assert model_crud.count_catalog_models(db) == 5

    def test_user_models_paginated(self, db, sample_member):
        """사용자 모델 페이지네이션"""
        for i in range(4):
            model_crud.create_model_mapping(
                db=db, surro_model_id=1000 + i,
                member_id=sample_member.member_id
            )
        models = model_crud.get_user_models_paginated(
            db, sample_member.member_id, skip=0, limit=2
        )
        assert len(models) == 2

    def test_search_models_by_member(self, db, sample_member):
        """사용자 모델 검색"""
        model_crud.create_model_mapping(
            db=db, surro_model_id=1100,
            member_id=sample_member.member_id,
            model_name="YOLO-Detection"
        )
        model_crud.create_model_mapping(
            db=db, surro_model_id=1101,
            member_id=sample_member.member_id,
            model_name="ResNet-Classification"
        )
        models, total = model_crud.search_models_by_member(
            db, sample_member.member_id, search="YOLO"
        )
        assert total == 1
        assert models[0].name == "YOLO-Detection"
