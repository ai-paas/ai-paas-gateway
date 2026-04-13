"""DatasetCRUD 단위 테스트"""
import pytest
from app.cruds.dataset import dataset_crud


class TestDatasetCRUD:
    """DatasetCRUD 매핑 관리 테스트"""

    def test_create_dataset_mapping(self, db, sample_member):
        """매핑 생성"""
        ds = dataset_crud.create_dataset_mapping(
            db=db,
            surro_dataset_id=100,
            member_id=sample_member.member_id,
            dataset_name="test-dataset"
        )
        assert ds.surro_dataset_id == 100
        assert ds.created_by == sample_member.member_id
        assert ds.name == "test-dataset"
        assert ds.is_active is True
        assert ds.deleted_at is None

    def test_create_dataset_mapping_duplicate_updates_name(self, db, sample_member):
        """중복 매핑 시 stale 이름 업데이트 (MLOps 재설치 대응)"""
        # 첫 생성
        ds1 = dataset_crud.create_dataset_mapping(
            db=db, surro_dataset_id=200,
            member_id=sample_member.member_id,
            dataset_name="old-name"
        )
        # 동일 surro_id로 재생성 (다른 이름)
        ds2 = dataset_crud.create_dataset_mapping(
            db=db, surro_dataset_id=200,
            member_id=sample_member.member_id,
            dataset_name="new-name"
        )
        assert ds2.id == ds1.id  # 같은 레코드
        assert ds2.name == "new-name"  # 이름 업데이트됨

    def test_get_dataset_by_surro_id(self, db, sample_member):
        """surro_id + member_id로 조회"""
        dataset_crud.create_dataset_mapping(
            db=db, surro_dataset_id=300,
            member_id=sample_member.member_id,
            dataset_name="find-me"
        )
        found = dataset_crud.get_dataset_by_surro_id(db, 300, sample_member.member_id)
        assert found is not None
        assert found.name == "find-me"

    def test_get_dataset_by_surro_id_wrong_member(self, db, sample_member):
        """다른 사용자의 매핑은 조회 불가"""
        dataset_crud.create_dataset_mapping(
            db=db, surro_dataset_id=301,
            member_id=sample_member.member_id,
            dataset_name="not-yours"
        )
        found = dataset_crud.get_dataset_by_surro_id(db, 301, "other-user")
        assert found is None

    def test_check_dataset_ownership(self, db, sample_member):
        """소유권 확인"""
        dataset_crud.create_dataset_mapping(
            db=db, surro_dataset_id=400,
            member_id=sample_member.member_id,
            dataset_name="owned"
        )
        assert dataset_crud.check_dataset_ownership(db, 400, sample_member.member_id) is True
        assert dataset_crud.check_dataset_ownership(db, 400, "stranger") is False

    def test_delete_dataset_mapping_soft(self, db, sample_member):
        """소프트 삭제"""
        dataset_crud.create_dataset_mapping(
            db=db, surro_dataset_id=500,
            member_id=sample_member.member_id,
            dataset_name="to-delete"
        )
        result = dataset_crud.delete_dataset_mapping(db, 500, sample_member.member_id)
        assert result is True

        # 삭제 후 조회 불가 (deleted_at 필터)
        found = dataset_crud.get_dataset_by_surro_id(db, 500, sample_member.member_id)
        assert found is None

    def test_get_datasets_count_by_member(self, db, sample_member):
        """사용자별 데이터셋 카운트"""
        for i in range(3):
            dataset_crud.create_dataset_mapping(
                db=db, surro_dataset_id=600 + i,
                member_id=sample_member.member_id,
                dataset_name=f"ds-{i}"
            )
        count = dataset_crud.get_datasets_count_by_member(db, sample_member.member_id)
        assert count == 3

    def test_get_datasets_count_excludes_deleted(self, db, sample_member):
        """삭제된 데이터셋은 카운트 제외"""
        dataset_crud.create_dataset_mapping(
            db=db, surro_dataset_id=700,
            member_id=sample_member.member_id,
            dataset_name="active"
        )
        dataset_crud.create_dataset_mapping(
            db=db, surro_dataset_id=701,
            member_id=sample_member.member_id,
            dataset_name="to-be-deleted"
        )
        dataset_crud.delete_dataset_mapping(db, 701, sample_member.member_id)

        count = dataset_crud.get_datasets_count_by_member(db, sample_member.member_id)
        assert count == 1

    def test_get_dataset_mappings_by_member_id(self, db, sample_member):
        """사용자별 매핑 딕셔너리 조회"""
        for i in range(3):
            dataset_crud.create_dataset_mapping(
                db=db, surro_dataset_id=800 + i,
                member_id=sample_member.member_id,
                dataset_name=f"mapped-{i}"
            )
        mappings = dataset_crud.get_dataset_mappings_by_member_id(
            db, sample_member.member_id
        )
        assert isinstance(mappings, dict)
        assert len(mappings) == 3
        assert 800 in mappings

    def test_get_dataset_mappings_pagination(self, db, sample_member):
        """매핑 페이지네이션"""
        for i in range(5):
            dataset_crud.create_dataset_mapping(
                db=db, surro_dataset_id=900 + i,
                member_id=sample_member.member_id,
                dataset_name=f"page-{i}"
            )
        mappings = dataset_crud.get_dataset_mappings_by_member_id(
            db, sample_member.member_id, skip=0, limit=3
        )
        assert len(mappings) == 3

    def test_update_dataset_cache(self, db, sample_member):
        """캐시 이름 업데이트"""
        dataset_crud.create_dataset_mapping(
            db=db, surro_dataset_id=1000,
            member_id=sample_member.member_id,
            dataset_name="original"
        )
        updated = dataset_crud.update_dataset_cache(
            db=db, surro_dataset_id=1000,
            member_id=sample_member.member_id,
            dataset_name="updated"
        )
        assert updated.name == "updated"

    def test_bulk_create_mappings(self, db, sample_member):
        """벌크 매핑 생성"""
        mappings = [
            (1100, sample_member.member_id, "bulk-1"),
            (1101, sample_member.member_id, "bulk-2"),
            (1102, sample_member.member_id, "bulk-3"),
        ]
        created = dataset_crud.bulk_create_mappings(db, mappings)
        assert created == 3

    def test_bulk_create_mappings_skip_existing(self, db, sample_member):
        """벌크 생성 시 기존 매핑 건너뜀"""
        dataset_crud.create_dataset_mapping(
            db=db, surro_dataset_id=1200,
            member_id=sample_member.member_id,
            dataset_name="existing"
        )
        mappings = [
            (1200, sample_member.member_id, "existing"),  # 이미 존재
            (1201, sample_member.member_id, "new-one"),
        ]
        created = dataset_crud.bulk_create_mappings(db, mappings)
        assert created == 1
