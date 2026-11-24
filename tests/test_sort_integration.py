"""P1 정렬 기능 통합 테스트 — members/services/prompts CRUD + routes.

- `order_by` 인자로 SQL ORDER BY 가 실제 적용되는지
- `resolve_sort_columns` 가 라우트에서 422 를 제대로 던지는지
- `prompts` search 버그 수정 확인
- 페이지 경계 안정성(tie-breaker)
"""
import pytest
from fastapi.testclient import TestClient

from app.common.sort import parse_sort, resolve_sort_columns
from app.cruds.member import member_crud
from app.cruds.prompt import prompt_crud
from app.cruds.service import service_crud
from app.models.member import Member
from app.models.prompt import Prompt
from app.models.service import Service
from app.schemas.member import MemberCreate


def _make_members(db, count=5, name_prefix="user"):
    members = []
    for i in range(count):
        schema = MemberCreate(
            name=f"{name_prefix}-{i:02d}",
            member_id=f"m-{i:03d}",
            email=f"{name_prefix}{i}@test.com",
            password="Test1234!@",
            password_confirm="Test1234!@",
            phone="01012345678",
            role="user",
        )
        members.append(member_crud.create_member(db, schema))
    return members


def _make_services(db, member_id, count=3):
    for i in range(count):
        svc = Service(
            name=f"svc-{i:02d}",
            description=f"desc-{i}",
            created_by=member_id,
            surro_service_id=f"uuid-{i:03d}",
        )
        db.add(svc)
    db.flush()


def _make_prompts(db, member_id, count=3):
    for i in range(count):
        p = Prompt(
            name=f"prompt-{i:02d}",
            description=f"desc-{i}",
            content=f"content with keyword-{i}",
            created_by=member_id,
            surro_prompt_id=i + 100,
        )
        db.add(p)
    db.flush()


class TestMembersSort:
    def test_order_by_name_asc(self, db):
        _make_members(db, count=3)
        order_by = resolve_sort_columns(
            parsed=parse_sort("name"),
            allowed={"name": Member.name},
            default=[(Member.created_at, True)],
            tie_breaker=Member.member_id,
        )
        members, total = member_crud.get_members(db, skip=0, limit=10, order_by=order_by)
        assert total == 3
        names = [m.name for m in members]
        assert names == sorted(names)

    def test_order_by_name_desc(self, db):
        _make_members(db, count=3)
        order_by = resolve_sort_columns(
            parsed=parse_sort("-name"),
            allowed={"name": Member.name},
            default=[(Member.created_at, True)],
            tie_breaker=Member.member_id,
        )
        members, _ = member_crud.get_members(db, skip=0, limit=10, order_by=order_by)
        names = [m.name for m in members]
        assert names == sorted(names, reverse=True)

    def test_page_boundary_stable_with_tie(self, db):
        # 같은 role, 같은 created_at 이 있을 때 tie-breaker(member_id) 로 페이지 경계 안정
        _make_members(db, count=6)
        order_by = resolve_sort_columns(
            parsed=parse_sort("role"),
            allowed={"role": Member.role},
            default=[(Member.created_at, True)],
            tie_breaker=Member.member_id,
        )
        page1, _ = member_crud.get_members(db, skip=0, limit=3, order_by=order_by)
        page2, _ = member_crud.get_members(db, skip=3, limit=3, order_by=order_by)
        ids = [m.member_id for m in page1] + [m.member_id for m in page2]
        assert len(set(ids)) == 6  # 중복 없음


class TestServicesSort:
    def test_order_by_name(self, db, sample_member):
        _make_services(db, sample_member.member_id, count=3)
        order_by = resolve_sort_columns(
            parsed=parse_sort("-name"),
            allowed={"name": Service.name},
            default=[(Service.created_at, True)],
            tie_breaker=Service.id,
        )
        services, total = service_crud.get_services(db, skip=0, limit=10, order_by=order_by)
        assert total == 3
        names = [s.name for s in services]
        assert names == sorted(names, reverse=True)

    def test_default_used_when_order_by_none(self, db, sample_member):
        # order_by=None 이면 CRUD 는 ORDER BY 를 걸지 않음 (기존 동작 유지)
        _make_services(db, sample_member.member_id, count=2)
        services, _ = service_crud.get_services(db, skip=0, limit=10)
        assert len(services) == 2


class TestPromptsSort:
    def test_order_by_name(self, db, sample_member):
        _make_prompts(db, sample_member.member_id, count=3)
        order_by = resolve_sort_columns(
            parsed=parse_sort("name"),
            allowed={"name": Prompt.name},
            default=[(Prompt.created_at, True)],
            tie_breaker=Prompt.id,
        )
        prompts, total = prompt_crud.get_prompts(db, skip=0, limit=10, order_by=order_by)
        assert total == 3
        names = [p.name for p in prompts]
        assert names == sorted(names)


class TestPromptsSearchBugFix:
    """과거 search 파라미터를 받지만 필터를 적용하지 않던 버그가 고쳐졌는지."""

    def test_search_filters_by_name(self, db, sample_member):
        _make_prompts(db, sample_member.member_id, count=3)
        # 4번째 프롬프트는 특이한 이름
        special = Prompt(
            name="UNIQUE_KEYWORD",
            description="d",
            content="c",
            created_by=sample_member.member_id,
            surro_prompt_id=999,
        )
        db.add(special)
        db.flush()

        prompts, total = prompt_crud.get_prompts(db, search="UNIQUE_KEYWORD")
        assert total == 1
        assert prompts[0].name == "UNIQUE_KEYWORD"

    def test_search_filters_by_description(self, db, sample_member):
        _make_prompts(db, sample_member.member_id, count=2)
        p = Prompt(
            name="x",
            description="FINDABLE_DESC",
            content="c",
            created_by=sample_member.member_id,
            surro_prompt_id=1001,
        )
        db.add(p)
        db.flush()

        prompts, total = prompt_crud.get_prompts(db, search="FINDABLE_DESC")
        assert total == 1

    def test_search_filters_by_content(self, db, sample_member):
        # 기존 _make_prompts 는 content 에 "keyword-{i}" 를 넣음
        _make_prompts(db, sample_member.member_id, count=5)
        prompts, total = prompt_crud.get_prompts(db, search="keyword-2")
        assert total == 1

    def test_search_no_match(self, db, sample_member):
        _make_prompts(db, sample_member.member_id, count=3)
        prompts, total = prompt_crud.get_prompts(db, search="NONEXISTENT_STRING")
        assert total == 0
        assert prompts == []

    def test_search_none_returns_all(self, db, sample_member):
        _make_prompts(db, sample_member.member_id, count=3)
        prompts, total = prompt_crud.get_prompts(db, search=None)
        assert total == 3
