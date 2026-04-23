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


class TestDatasetDescriptionCache:
    """description 캐시 저장/갱신 테스트"""

    def test_create_mapping_with_description(self, db, sample_member):
        ds = dataset_crud.create_dataset_mapping(
            db=db, surro_dataset_id=2000,
            member_id=sample_member.member_id,
            dataset_name="ds",
            dataset_description="초기 설명"
        )
        assert ds.description == "초기 설명"

    def test_update_dataset_cache_sets_description(self, db, sample_member):
        dataset_crud.create_dataset_mapping(
            db=db, surro_dataset_id=2001,
            member_id=sample_member.member_id,
            dataset_name="ds"
        )
        updated = dataset_crud.update_dataset_cache(
            db=db, surro_dataset_id=2001,
            member_id=sample_member.member_id,
            dataset_name=None,
            dataset_description="나중에 추가된 설명"
        )
        assert updated.description == "나중에 추가된 설명"
        assert updated.name == "ds"  # 이름은 유지

    def test_backfill_updates_when_values_differ(self, db, sample_member):
        dataset_crud.create_dataset_mapping(
            db=db, surro_dataset_id=2002,
            member_id=sample_member.member_id,
            dataset_name="old-name",
            dataset_description="old-desc"
        )
        changed = dataset_crud.backfill_cache_if_changed(
            db=db, surro_dataset_id=2002,
            member_id=sample_member.member_id,
            name="new-name",
            description="new-desc"
        )
        assert changed is True
        found = dataset_crud.get_dataset_by_surro_id(db, 2002, sample_member.member_id)
        assert found.name == "new-name"
        assert found.description == "new-desc"

    def test_backfill_noop_when_same(self, db, sample_member):
        dataset_crud.create_dataset_mapping(
            db=db, surro_dataset_id=2003,
            member_id=sample_member.member_id,
            dataset_name="same",
            dataset_description="same-desc"
        )
        changed = dataset_crud.backfill_cache_if_changed(
            db=db, surro_dataset_id=2003,
            member_id=sample_member.member_id,
            name="same",
            description="same-desc"
        )
        assert changed is False

    def test_backfill_skips_when_args_omitted(self, db, sample_member):
        """인자 미지정 시 해당 필드는 건드리지 않음 (sentinel 동작)"""
        dataset_crud.create_dataset_mapping(
            db=db, surro_dataset_id=2004,
            member_id=sample_member.member_id,
            dataset_name="keep-name",
            dataset_description="keep-desc"
        )
        changed = dataset_crud.backfill_cache_if_changed(
            db=db, surro_dataset_id=2004,
            member_id=sample_member.member_id,
        )
        assert changed is False
        found = dataset_crud.get_dataset_by_surro_id(db, 2004, sample_member.member_id)
        assert found.name == "keep-name"
        assert found.description == "keep-desc"

    def test_backfill_clears_description_when_external_nulls_it(self, db, sample_member):
        """외부가 description을 null로 보내면 로컬도 NULL로 수렴 (검색 false positive 방지)"""
        dataset_crud.create_dataset_mapping(
            db=db, surro_dataset_id=2005,
            member_id=sample_member.member_id,
            dataset_name="ds",
            dataset_description="removed-soon-token"
        )
        # 사용자가 검색 대상 문자열로 설명을 검색하면 먼저 잡혀야 함
        _, pre_total = dataset_crud.search_datasets_by_member_id(
            db=db, member_id=sample_member.member_id, search="removed-soon-token"
        )
        assert pre_total == 1

        # 외부가 설명을 null로 지운 상황을 시뮬레이션
        changed = dataset_crud.backfill_cache_if_changed(
            db=db, surro_dataset_id=2005,
            member_id=sample_member.member_id,
            name="ds",
            description=None,
        )
        assert changed is True

        found = dataset_crud.get_dataset_by_surro_id(db, 2005, sample_member.member_id)
        assert found.description is None
        assert found.name == "ds"

        # 검색 false positive가 제거됐는지 확인
        _, post_total = dataset_crud.search_datasets_by_member_id(
            db=db, member_id=sample_member.member_id, search="removed-soon-token"
        )
        assert post_total == 0

    def test_backfill_returns_false_for_missing_mapping(self, db, sample_member):
        changed = dataset_crud.backfill_cache_if_changed(
            db=db, surro_dataset_id=9999,
            member_id=sample_member.member_id,
            name="x", description="y"
        )
        assert changed is False


class TestSearchDatasetsByMemberId:
    """검색 CRUD 테스트"""

    def test_search_by_name_matches(self, db, sample_member):
        dataset_crud.create_dataset_mapping(
            db=db, surro_dataset_id=3000,
            member_id=sample_member.member_id,
            dataset_name="mnist-train", dataset_description="digits"
        )
        dataset_crud.create_dataset_mapping(
            db=db, surro_dataset_id=3001,
            member_id=sample_member.member_id,
            dataset_name="cifar", dataset_description="images"
        )
        results, total = dataset_crud.search_datasets_by_member_id(
            db=db, member_id=sample_member.member_id, search="mnist"
        )
        assert total == 1
        assert len(results) == 1
        assert results[0].surro_dataset_id == 3000

    def test_search_by_description_matches(self, db, sample_member):
        dataset_crud.create_dataset_mapping(
            db=db, surro_dataset_id=3100,
            member_id=sample_member.member_id,
            dataset_name="ds-a", dataset_description="handwritten digits train split"
        )
        dataset_crud.create_dataset_mapping(
            db=db, surro_dataset_id=3101,
            member_id=sample_member.member_id,
            dataset_name="ds-b", dataset_description="photos of cats"
        )
        results, total = dataset_crud.search_datasets_by_member_id(
            db=db, member_id=sample_member.member_id, search="handwritten"
        )
        assert total == 1
        assert results[0].surro_dataset_id == 3100

    def test_search_case_insensitive(self, db, sample_member):
        dataset_crud.create_dataset_mapping(
            db=db, surro_dataset_id=3200,
            member_id=sample_member.member_id,
            dataset_name="MyDataset", dataset_description="UPPER"
        )
        results, total = dataset_crud.search_datasets_by_member_id(
            db=db, member_id=sample_member.member_id, search="mydataset"
        )
        assert total == 1

    def test_search_no_match_returns_empty(self, db, sample_member):
        dataset_crud.create_dataset_mapping(
            db=db, surro_dataset_id=3300,
            member_id=sample_member.member_id,
            dataset_name="exists"
        )
        results, total = dataset_crud.search_datasets_by_member_id(
            db=db, member_id=sample_member.member_id, search="zzz_nonexistent_9999"
        )
        assert results == []
        assert total == 0

    def test_search_none_returns_all(self, db, sample_member):
        for i in range(3):
            dataset_crud.create_dataset_mapping(
                db=db, surro_dataset_id=3400 + i,
                member_id=sample_member.member_id,
                dataset_name=f"ds-{i}"
            )
        results, total = dataset_crud.search_datasets_by_member_id(
            db=db, member_id=sample_member.member_id, search=None
        )
        assert total == 3
        assert len(results) == 3

    def test_search_respects_member_isolation(self, db, sample_member):
        from app.models import Member
        other = Member(
            name="다른유저", member_id="other-user",
            email="other@example.com",
            password_hash="$2b$12$dummyhashvalue1234567890abcdefghijklmnopqrstuv",
            role="user", is_active=True
        )
        db.add(other)
        db.flush()

        dataset_crud.create_dataset_mapping(
            db=db, surro_dataset_id=3500,
            member_id=sample_member.member_id,
            dataset_name="secret-a"
        )
        dataset_crud.create_dataset_mapping(
            db=db, surro_dataset_id=3501,
            member_id=other.member_id,
            dataset_name="secret-b"
        )

        _, total_a = dataset_crud.search_datasets_by_member_id(
            db=db, member_id=sample_member.member_id, search="secret"
        )
        _, total_b = dataset_crud.search_datasets_by_member_id(
            db=db, member_id=other.member_id, search="secret"
        )
        assert total_a == 1
        assert total_b == 1

    def test_search_excludes_soft_deleted(self, db, sample_member):
        dataset_crud.create_dataset_mapping(
            db=db, surro_dataset_id=3600,
            member_id=sample_member.member_id,
            dataset_name="deleted-soon"
        )
        dataset_crud.delete_dataset_mapping(db, 3600, sample_member.member_id)
        results, total = dataset_crud.search_datasets_by_member_id(
            db=db, member_id=sample_member.member_id, search="deleted-soon"
        )
        assert total == 0
        assert results == []

    def test_search_excludes_inactive(self, db, sample_member):
        ds = dataset_crud.create_dataset_mapping(
            db=db, surro_dataset_id=3700,
            member_id=sample_member.member_id,
            dataset_name="inactive-one"
        )
        ds.is_active = False
        db.commit()
        results, total = dataset_crud.search_datasets_by_member_id(
            db=db, member_id=sample_member.member_id, search="inactive-one"
        )
        assert total == 0

    def test_search_pagination(self, db, sample_member):
        for i in range(10):
            dataset_crud.create_dataset_mapping(
                db=db, surro_dataset_id=3800 + i,
                member_id=sample_member.member_id,
                dataset_name=f"page-match-{i}"
            )
        results, total = dataset_crud.search_datasets_by_member_id(
            db=db, member_id=sample_member.member_id,
            search="page-match", skip=5, limit=3
        )
        assert total == 10
        assert len(results) == 3

    def test_search_ordering_surro_id_desc(self, db, sample_member):
        for surro_id in [3900, 3902, 3901]:
            dataset_crud.create_dataset_mapping(
                db=db, surro_dataset_id=surro_id,
                member_id=sample_member.member_id,
                dataset_name=f"ord-{surro_id}"
            )
        results, total = dataset_crud.search_datasets_by_member_id(
            db=db, member_id=sample_member.member_id, search="ord-"
        )
        assert total == 3
        assert [r.surro_dataset_id for r in results] == [3902, 3901, 3900]


class TestLongDescription:
    def test_long_description_roundtrip(self, db, sample_member):
        """Text 컬럼: 긴 설명 저장/검색 정상 동작 (String(1024) 였다면 실패할 케이스)"""
        long_desc = "긴설명-" * 500 + "토큰매칭부분handwritten-digits"
        dataset_crud.create_dataset_mapping(
            db=db, surro_dataset_id=4000,
            member_id=sample_member.member_id,
            dataset_name="long-desc-ds",
            dataset_description=long_desc
        )
        found = dataset_crud.get_dataset_by_surro_id(db, 4000, sample_member.member_id)
        assert found.description == long_desc

        results, total = dataset_crud.search_datasets_by_member_id(
            db=db, member_id=sample_member.member_id,
            search="handwritten-digits"
        )
        assert total == 1
        assert results[0].surro_dataset_id == 4000
