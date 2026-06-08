"""P2 하이브리드 도메인 정렬 통합 테스트.

datasets / learning(experiments) / knowledge-bases / prompts 의 CRUD 에 `order_by`
인자가 정상 반영되는지. 외부 API 를 타지 않는 순수 DB 계층 테스트.
"""
import pytest

from app.common.sort import parse_sort, resolve_sort_columns, sort_in_memory
from app.cruds.dataset import dataset_crud
from app.cruds.experiment import experiment_crud
from app.cruds.knowledge_base import knowledge_base_crud
from app.cruds.prompt import prompt_crud
from app.models.dataset import Dataset
from app.models.experiment import Experiment
from app.models.knowledge_base import KnowledgeBase
from app.models.prompt import Prompt


class TestDatasetsSort:
    def test_order_by_name_asc(self, db, sample_member):
        for i, name in enumerate(["beta", "alpha", "gamma"]):
            dataset_crud.create_dataset_mapping(
                db=db,
                surro_dataset_id=10 + i,
                member_id=sample_member.member_id,
                dataset_name=name,
            )
        order_by = resolve_sort_columns(
            parsed=parse_sort("name"),
            allowed={"name": Dataset.name},
            default=[(Dataset.created_at, True)],
            tie_breaker=Dataset.surro_dataset_id,
        )
        results, total = dataset_crud.search_datasets_by_member_id(
            db=db,
            member_id=sample_member.member_id,
            skip=0,
            limit=10,
            order_by=order_by,
        )
        assert total == 3
        assert [d.name for d in results] == ["alpha", "beta", "gamma"]

    def test_default_fallback_when_order_by_none(self, db, sample_member):
        for i in range(3):
            dataset_crud.create_dataset_mapping(
                db=db,
                surro_dataset_id=20 + i,
                member_id=sample_member.member_id,
                dataset_name=f"ds-{i}",
            )
        # order_by=None 이면 CRUD 가 surro_dataset_id DESC 기본 정렬
        results, _ = dataset_crud.search_datasets_by_member_id(
            db=db, member_id=sample_member.member_id, skip=0, limit=10,
        )
        ids = [d.surro_dataset_id for d in results]
        assert ids == sorted(ids, reverse=True)

    def test_search_preserves_order(self, db, sample_member):
        dataset_crud.create_dataset_mapping(
            db=db, surro_dataset_id=30, member_id=sample_member.member_id,
            dataset_name="zeta match",
        )
        dataset_crud.create_dataset_mapping(
            db=db, surro_dataset_id=31, member_id=sample_member.member_id,
            dataset_name="alpha match",
        )
        dataset_crud.create_dataset_mapping(
            db=db, surro_dataset_id=32, member_id=sample_member.member_id,
            dataset_name="no hit",
        )
        order_by = resolve_sort_columns(
            parsed=parse_sort("name"),
            allowed={"name": Dataset.name},
            default=[(Dataset.created_at, True)],
            tie_breaker=Dataset.surro_dataset_id,
        )
        results, total = dataset_crud.search_datasets_by_member_id(
            db=db, member_id=sample_member.member_id,
            skip=0, limit=10, search="match", order_by=order_by,
        )
        assert total == 2
        assert [d.name for d in results] == ["alpha match", "zeta match"]

    def test_page_boundary_stable(self, db, sample_member):
        # 6 rows, size=3 → page1 + page2 결합 시 중복 없음
        for i in range(6):
            dataset_crud.create_dataset_mapping(
                db=db, surro_dataset_id=40 + i,
                member_id=sample_member.member_id,
                dataset_name="same",  # 모두 동일 → tie-breaker 동작 확인
            )
        order_by = resolve_sort_columns(
            parsed=parse_sort("name"),
            allowed={"name": Dataset.name},
            default=[(Dataset.created_at, True)],
            tie_breaker=Dataset.surro_dataset_id,
        )
        page1, _ = dataset_crud.search_datasets_by_member_id(
            db=db, member_id=sample_member.member_id, skip=0, limit=3, order_by=order_by,
        )
        page2, _ = dataset_crud.search_datasets_by_member_id(
            db=db, member_id=sample_member.member_id, skip=3, limit=3, order_by=order_by,
        )
        ids = [d.surro_dataset_id for d in page1] + [d.surro_dataset_id for d in page2]
        assert len(set(ids)) == 6


class TestExperimentsSort:
    def test_order_by_name_asc(self, db, sample_member):
        for i, name in enumerate(["gamma", "beta", "alpha"]):
            experiment_crud.create_mapping(
                db=db,
                surro_experiment_id=100 + i,
                member_id=sample_member.member_id,
                name=name,
            )
        order_by = resolve_sort_columns(
            parsed=parse_sort("name"),
            allowed={"name": Experiment.name},
            default=[(Experiment.created_at, True)],
            tie_breaker=Experiment.surro_experiment_id,
        )
        results, total = experiment_crud.search_experiments_by_member_id(
            db=db, member_id=sample_member.member_id,
            skip=0, limit=10, order_by=order_by,
        )
        assert total == 3
        assert [e.name for e in results] == ["alpha", "beta", "gamma"]

    def test_default_fallback(self, db, sample_member):
        for i in range(3):
            experiment_crud.create_mapping(
                db=db, surro_experiment_id=200 + i,
                member_id=sample_member.member_id, name=f"exp-{i}",
            )
        results, _ = experiment_crud.search_experiments_by_member_id(
            db=db, member_id=sample_member.member_id, skip=0, limit=10,
        )
        ids = [e.surro_experiment_id for e in results]
        assert ids == sorted(ids, reverse=True)


class TestKnowledgeBasesSort:
    def _make_kb(self, db, member_id, name, collection_name, surro_id):
        knowledge_base_crud.create_knowledge_base(
            db=db,
            name=name,
            description="",
            created_by=member_id,
            surro_knowledge_id=surro_id,
            collection_name=collection_name,
        )

    def test_order_by_name_asc(self, db, sample_member):
        for surro_id, name in enumerate(["zeta", "alpha", "mid"], start=500):
            self._make_kb(db, sample_member.member_id, name, f"col-{surro_id}", surro_id)
        order_by = resolve_sort_columns(
            parsed=parse_sort("name"),
            allowed={"name": KnowledgeBase.name},
            default=[(KnowledgeBase.created_at, True)],
            tie_breaker=KnowledgeBase.id,
        )
        results, total = knowledge_base_crud.get_knowledge_bases(
            db=db, skip=0, limit=10, member_id=sample_member.member_id, order_by=order_by,
        )
        assert total == 3
        assert [kb.name for kb in results] == ["alpha", "mid", "zeta"]

    def test_order_by_collection_name_desc(self, db, sample_member):
        self._make_kb(db, sample_member.member_id, "a", "zeta", 600)
        self._make_kb(db, sample_member.member_id, "b", "alpha", 601)
        self._make_kb(db, sample_member.member_id, "c", "mid", 602)
        order_by = resolve_sort_columns(
            parsed=parse_sort("-collection_name"),
            allowed={"collection_name": KnowledgeBase.collection_name},
            default=[(KnowledgeBase.created_at, True)],
            tie_breaker=KnowledgeBase.id,
        )
        results, _ = knowledge_base_crud.get_knowledge_bases(
            db=db, skip=0, limit=10, member_id=sample_member.member_id, order_by=order_by,
        )
        assert [kb.collection_name for kb in results] == ["zeta", "mid", "alpha"]


class TestStaleTotalFilter:
    """외부 응답과 교차하지 않는 stale 로컬 매핑이 total 에 포함되지 않아야 한다."""

    def test_dataset_valid_surro_ids_excludes_stale(self, db, sample_member):
        # 5 개 로컬 매핑 중 3 개만 외부 존재
        for i in range(5):
            dataset_crud.create_dataset_mapping(
                db=db, surro_dataset_id=700 + i,
                member_id=sample_member.member_id,
                dataset_name=f"ds-{i}",
            )
        valid = {700, 701, 702}  # 703, 704 는 stale
        results, total = dataset_crud.search_datasets_by_member_id(
            db=db, member_id=sample_member.member_id,
            skip=0, limit=10, valid_surro_ids=valid,
        )
        assert total == 3
        assert len(results) == 3
        returned_ids = {d.surro_dataset_id for d in results}
        assert returned_ids == valid

    def test_dataset_empty_valid_returns_zero(self, db, sample_member):
        dataset_crud.create_dataset_mapping(
            db=db, surro_dataset_id=710,
            member_id=sample_member.member_id, dataset_name="x",
        )
        # 외부가 완전히 비어 있으면 total=0, data=[]
        results, total = dataset_crud.search_datasets_by_member_id(
            db=db, member_id=sample_member.member_id,
            skip=0, limit=10, valid_surro_ids=set(),
        )
        assert total == 0
        assert results == []

    def test_dataset_none_valid_means_no_filter(self, db, sample_member):
        # valid_surro_ids=None 은 "필터 없음" 으로 기존 동작 유지
        for i in range(2):
            dataset_crud.create_dataset_mapping(
                db=db, surro_dataset_id=720 + i,
                member_id=sample_member.member_id, dataset_name=f"ds-{i}",
            )
        results, total = dataset_crud.search_datasets_by_member_id(
            db=db, member_id=sample_member.member_id,
            skip=0, limit=10, valid_surro_ids=None,
        )
        assert total == 2

    def test_experiment_valid_surro_ids_excludes_stale(self, db, sample_member):
        for i in range(4):
            experiment_crud.create_mapping(
                db=db, surro_experiment_id=800 + i,
                member_id=sample_member.member_id, name=f"exp-{i}",
            )
        valid = {800, 802}  # 801, 803 stale
        results, total = experiment_crud.search_experiments_by_member_id(
            db=db, member_id=sample_member.member_id,
            skip=0, limit=10, valid_surro_ids=valid,
        )
        assert total == 2
        returned = {e.surro_experiment_id for e in results}
        assert returned == valid

    def test_experiment_empty_valid_returns_zero(self, db, sample_member):
        experiment_crud.create_mapping(
            db=db, surro_experiment_id=810,
            member_id=sample_member.member_id, name="x",
        )
        results, total = experiment_crud.search_experiments_by_member_id(
            db=db, member_id=sample_member.member_id,
            skip=0, limit=10, valid_surro_ids=set(),
        )
        assert total == 0
        assert results == []

    def test_dataset_valid_with_search(self, db, sample_member):
        # 교차 필터 + search 같이 동작
        dataset_crud.create_dataset_mapping(
            db=db, surro_dataset_id=900,
            member_id=sample_member.member_id, dataset_name="alpha match",
        )
        dataset_crud.create_dataset_mapping(
            db=db, surro_dataset_id=901,
            member_id=sample_member.member_id, dataset_name="beta match",
        )
        dataset_crud.create_dataset_mapping(
            db=db, surro_dataset_id=902,  # search 매치하지만 외부에 없음
            member_id=sample_member.member_id, dataset_name="gamma match",
        )
        results, total = dataset_crud.search_datasets_by_member_id(
            db=db, member_id=sample_member.member_id,
            skip=0, limit=10,
            search="match",
            valid_surro_ids={900, 901},  # 902 stale
        )
        assert total == 2


class TestPromptsMLOpsSync:
    """prompts 는 MLOps 연동 — member_id 권한 필터 + valid_surro_ids stale 필터."""

    def _make_prompt(self, db, member_id, surro_id, name="p"):
        return prompt_crud.create_mapping_from_external(
            db=db,
            surro_prompt_id=surro_id,
            member_id=member_id,
            name=name,
            description=f"desc-{surro_id}",
            content=f"content-{surro_id}",
        )

    def test_member_id_filters_by_owner(self, db, sample_member, admin_member):
        # sample_member 소유 2개 + admin 소유 1개
        self._make_prompt(db, sample_member.member_id, 2000)
        self._make_prompt(db, sample_member.member_id, 2001)
        self._make_prompt(db, admin_member.member_id, 2002)

        results, total = prompt_crud.get_prompts(
            db=db, member_id=sample_member.member_id,
        )
        assert total == 2
        assert all(p.created_by == sample_member.member_id for p in results)

    def test_valid_surro_ids_excludes_stale(self, db, sample_member):
        self._make_prompt(db, sample_member.member_id, 2100)
        self._make_prompt(db, sample_member.member_id, 2101)
        self._make_prompt(db, sample_member.member_id, 2102)  # stale

        results, total = prompt_crud.get_prompts(
            db=db, member_id=sample_member.member_id,
            valid_surro_ids={2100, 2101},
        )
        assert total == 2
        assert {p.surro_prompt_id for p in results} == {2100, 2101}

    def test_empty_valid_returns_zero(self, db, sample_member):
        self._make_prompt(db, sample_member.member_id, 2200)
        results, total = prompt_crud.get_prompts(
            db=db, member_id=sample_member.member_id,
            valid_surro_ids=set(),
        )
        assert total == 0
        assert results == []

    def test_none_member_id_returns_all(self, db, sample_member, admin_member):
        # 하위 호환성: member_id=None 이면 전체 조회 (기존 동작 유지)
        self._make_prompt(db, sample_member.member_id, 2300)
        self._make_prompt(db, admin_member.member_id, 2301)

        results, total = prompt_crud.get_prompts(db=db)
        assert total == 2

    def test_create_mapping_from_external(self, db, sample_member):
        created = prompt_crud.create_mapping_from_external(
            db=db,
            surro_prompt_id=2400,
            member_id=sample_member.member_id,
            name="ext-name",
            description="ext-desc",
            content="ext-content",
        )
        assert created.surro_prompt_id == 2400
        assert created.name == "ext-name"
        assert created.created_by == sample_member.member_id

    def test_create_mapping_idempotent_on_duplicate(self, db, sample_member):
        # 이미 매핑이 있으면 기존 반환 (에러 없이)
        first = prompt_crud.create_mapping_from_external(
            db=db, surro_prompt_id=2500, member_id=sample_member.member_id,
            name="first", description=None, content="c",
        )
        second = prompt_crud.create_mapping_from_external(
            db=db, surro_prompt_id=2500, member_id=sample_member.member_id,
            name="second-ignored", description=None, content="c",
        )
        assert first.id == second.id
        assert second.name == "second-ignored"  # external sync 시 캐시 갱신

    def test_backfill_updates_when_changed(self, db, sample_member):
        self._make_prompt(db, sample_member.member_id, 2600, name="old")
        changed = prompt_crud.backfill_cache_if_changed(
            db=db, surro_prompt_id=2600,
            name="new", content="new-content",
        )
        assert changed is True

        refreshed = prompt_crud.get_prompt_by_surro_id(db, 2600)
        assert refreshed.name == "new"
        assert refreshed.content == "new-content"

    def test_backfill_noop_when_unchanged(self, db, sample_member):
        self._make_prompt(db, sample_member.member_id, 2700, name="same")
        refreshed_before = prompt_crud.get_prompt_by_surro_id(db, 2700)
        changed = prompt_crud.backfill_cache_if_changed(
            db=db, surro_prompt_id=2700,
            name="same", description=f"desc-2700", content="content-2700",
        )
        assert changed is False

    def test_backfill_respects_missing_sentinel(self, db, sample_member):
        """인자 미지정 필드는 건드리지 않는다 (명시적 None 과 구분)."""
        self._make_prompt(db, sample_member.member_id, 2800, name="keep-name")
        prompt_crud.backfill_cache_if_changed(
            db=db, surro_prompt_id=2800,
            content="updated-content",  # name/description/prompt_variable 미지정
        )
        refreshed = prompt_crud.get_prompt_by_surro_id(db, 2800)
        assert refreshed.name == "keep-name"  # 보존
        assert refreshed.content == "updated-content"  # 업데이트


class TestWorkflowsMergeSort:
    """workflows 는 merge 후 WorkflowResponse 리스트 기준 in-memory 정렬.

    로컬 필드(id/name/created_at/updated_at/created_by) + 외부 필드(status) 모두 지원.
    """

    class FakeWorkflow:
        def __init__(self, id, name, status, created_at, created_by="user"):
            self.id = id
            self.name = name
            self.status = status
            self.created_at = created_at
            self.updated_at = created_at
            self.created_by = created_by

    def _getters(self):
        return {
            "id": lambda w: w.id,
            "name": lambda w: w.name,
            "created_at": lambda w: w.created_at,
            "updated_at": lambda w: w.updated_at,
            "created_by": lambda w: w.created_by,
            "status": lambda w: w.status,
        }

    def test_sort_by_local_field_name_asc(self):
        from datetime import datetime
        items = [
            self.FakeWorkflow(1, "zeta", "DRAFT", datetime(2024, 1, 1)),
            self.FakeWorkflow(2, "alpha", "ACTIVE", datetime(2024, 2, 1)),
            self.FakeWorkflow(3, "mid", "ERROR", datetime(2024, 3, 1)),
        ]
        result = sort_in_memory(
            items=items,
            parsed=parse_sort("name"),
            getters=self._getters(),
            default=[("created_at", True)],
            tie_breaker_getter=lambda w: w.id,
        )
        assert [w.name for w in result] == ["alpha", "mid", "zeta"]

    def test_sort_by_external_field_status(self):
        """status 는 MLOps 응답에서만 오는 외부 필드 — in-memory 경로로 정렬."""
        from datetime import datetime
        items = [
            self.FakeWorkflow(1, "a", "ERROR", datetime(2024, 1, 1)),
            self.FakeWorkflow(2, "b", "ACTIVE", datetime(2024, 2, 1)),
            self.FakeWorkflow(3, "c", "DRAFT", datetime(2024, 3, 1)),
        ]
        result = sort_in_memory(
            items=items,
            parsed=parse_sort("status"),
            getters=self._getters(),
            default=[("created_at", True)],
            tie_breaker_getter=lambda w: w.id,
        )
        assert [w.status for w in result] == ["ACTIVE", "DRAFT", "ERROR"]

    def test_sort_status_then_name(self):
        """다중 키: status ASC → 동점시 name ASC."""
        from datetime import datetime
        items = [
            self.FakeWorkflow(1, "zeta", "ACTIVE", datetime(2024, 1, 1)),
            self.FakeWorkflow(2, "alpha", "ACTIVE", datetime(2024, 2, 1)),
            self.FakeWorkflow(3, "mid", "DRAFT", datetime(2024, 3, 1)),
        ]
        result = sort_in_memory(
            items=items,
            parsed=parse_sort("status,name"),
            getters=self._getters(),
            default=[("created_at", True)],
            tie_breaker_getter=lambda w: w.id,
        )
        # ACTIVE(alpha), ACTIVE(zeta), DRAFT(mid)
        assert [w.id for w in result] == [2, 1, 3]

    def test_default_created_at_desc(self):
        from datetime import datetime
        items = [
            self.FakeWorkflow(1, "a", "ACTIVE", datetime(2024, 1, 1)),
            self.FakeWorkflow(2, "b", "ACTIVE", datetime(2024, 3, 1)),
            self.FakeWorkflow(3, "c", "ACTIVE", datetime(2024, 2, 1)),
        ]
        result = sort_in_memory(
            items=items,
            parsed=parse_sort(None),
            getters=self._getters(),
            default=[("created_at", True)],
            tie_breaker_getter=lambda w: w.id,
        )
        assert [w.id for w in result] == [2, 3, 1]

    def test_tie_breaker_stability(self):
        """같은 status 에 같은 created_at 일 때 id 로 안정 정렬."""
        from datetime import datetime
        same_ts = datetime(2024, 1, 1)
        items = [
            self.FakeWorkflow(3, "c", "ACTIVE", same_ts),
            self.FakeWorkflow(1, "a", "ACTIVE", same_ts),
            self.FakeWorkflow(2, "b", "ACTIVE", same_ts),
        ]
        result = sort_in_memory(
            items=items,
            parsed=parse_sort("status"),
            getters=self._getters(),
            default=[("created_at", True)],
            tie_breaker_getter=lambda w: w.id,
        )
        assert [w.id for w in result] == [1, 2, 3]


class TestModelsInMemorySort:
    """models 는 외부 응답 기준 in-memory 정렬. Pydantic-like 객체 mock 으로 검증."""

    class FakeModel:
        def __init__(self, id, name, created_at, updated_at):
            self.id = id
            self.name = name
            self.created_at = created_at
            self.updated_at = updated_at

    def test_sort_by_name_asc(self):
        from datetime import datetime
        items = [
            self.FakeModel(1, "zeta", datetime(2024, 1, 1), datetime(2024, 1, 1)),
            self.FakeModel(2, "alpha", datetime(2024, 2, 1), datetime(2024, 2, 1)),
            self.FakeModel(3, "mid", datetime(2024, 3, 1), datetime(2024, 3, 1)),
        ]
        getters = {
            "name": lambda m: m.name,
            "id": lambda m: m.id,
            "created_at": lambda m: m.created_at,
        }
        result = sort_in_memory(
            items=items,
            parsed=parse_sort("name"),
            getters=getters,
            default=[("created_at", True)],
            tie_breaker_getter=lambda m: m.id,
        )
        assert [m.name for m in result] == ["alpha", "mid", "zeta"]

    def test_default_used_when_no_sort(self):
        from datetime import datetime
        items = [
            self.FakeModel(1, "a", datetime(2024, 1, 1), datetime(2024, 1, 1)),
            self.FakeModel(2, "b", datetime(2024, 3, 1), datetime(2024, 3, 1)),
            self.FakeModel(3, "c", datetime(2024, 2, 1), datetime(2024, 2, 1)),
        ]
        getters = {
            "created_at": lambda m: m.created_at,
        }
        result = sort_in_memory(
            items=items,
            parsed=parse_sort(None),
            getters=getters,
            default=[("created_at", True)],
            tie_breaker_getter=lambda m: m.id,
        )
        assert [m.id for m in result] == [2, 3, 1]
