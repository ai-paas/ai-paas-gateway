"""app.common.sort 유틸 단위 테스트"""
import pytest
from fastapi import HTTPException

from app.common.sort import parse_sort, resolve_sort_columns, sort_in_memory
from app.models.member import Member


class TestParseSort:
    def test_none(self):
        assert parse_sort(None) == []

    def test_empty_string(self):
        assert parse_sort("") == []
        assert parse_sort("   ") == []

    def test_single_asc(self):
        assert parse_sort("name") == [("name", False)]

    def test_single_desc(self):
        assert parse_sort("-created_at") == [("created_at", True)]

    def test_multiple(self):
        assert parse_sort("-created_at,name") == [("created_at", True), ("name", False)]

    def test_spaces_stripped(self):
        assert parse_sort(" -created_at , name ") == [("created_at", True), ("name", False)]

    def test_empty_token_rejected(self):
        with pytest.raises(HTTPException) as exc:
            parse_sort(",name")
        assert exc.value.status_code == 422

    def test_bare_minus_rejected(self):
        with pytest.raises(HTTPException) as exc:
            parse_sort("-")
        assert exc.value.status_code == 422

    def test_duplicate_field_rejected(self):
        with pytest.raises(HTTPException) as exc:
            parse_sort("name,-name")
        assert exc.value.status_code == 422


class TestResolveSortColumns:
    def test_default_used_when_empty(self):
        clauses = resolve_sort_columns(
            parsed=[],
            allowed={"name": Member.name, "created_at": Member.created_at},
            default=[(Member.created_at, True)],
            tie_breaker=Member.member_id,
        )
        # default 1개 + tie_breaker 1개 = 2개
        assert len(clauses) == 2

    def test_parsed_used(self):
        clauses = resolve_sort_columns(
            parsed=[("name", False)],
            allowed={"name": Member.name, "created_at": Member.created_at},
            default=[(Member.created_at, True)],
            tie_breaker=Member.member_id,
        )
        assert len(clauses) == 2

    def test_invalid_field_rejected(self):
        with pytest.raises(HTTPException) as exc:
            resolve_sort_columns(
                parsed=[("nonexistent", False)],
                allowed={"name": Member.name},
                default=[(Member.created_at, True)],
                tie_breaker=Member.member_id,
            )
        assert exc.value.status_code == 422
        assert "nonexistent" in exc.value.detail

    def test_tie_breaker_dedup(self):
        # 사용자가 tie_breaker 와 같은 컬럼을 지정하면 중복 부가하지 않음
        clauses = resolve_sort_columns(
            parsed=[("member_id", True)],
            allowed={"member_id": Member.member_id},
            default=[(Member.created_at, True)],
            tie_breaker=Member.member_id,
        )
        assert len(clauses) == 1

    def test_multiple_columns(self):
        clauses = resolve_sort_columns(
            parsed=[("name", False), ("created_at", True)],
            allowed={"name": Member.name, "created_at": Member.created_at},
            default=[(Member.created_at, True)],
            tie_breaker=Member.member_id,
        )
        # 2 + tie_breaker = 3
        assert len(clauses) == 3


class TestSortInMemory:
    def test_default_used_when_empty(self):
        items = [
            {"id": 2, "name": "b", "created_at": 20},
            {"id": 1, "name": "a", "created_at": 10},
        ]
        result = sort_in_memory(
            items=items,
            parsed=[],
            getters={"name": lambda x: x["name"], "created_at": lambda x: x["created_at"]},
            default=[("created_at", True)],
            tie_breaker_getter=lambda x: x["id"],
        )
        assert [r["id"] for r in result] == [2, 1]

    def test_asc(self):
        items = [{"name": "c"}, {"name": "a"}, {"name": "b"}]
        result = sort_in_memory(
            items=items,
            parsed=[("name", False)],
            getters={"name": lambda x: x["name"]},
            default=[("name", False)],
            tie_breaker_getter=lambda x: x["name"],
        )
        assert [r["name"] for r in result] == ["a", "b", "c"]

    def test_desc(self):
        items = [{"name": "a"}, {"name": "c"}, {"name": "b"}]
        result = sort_in_memory(
            items=items,
            parsed=[("name", True)],
            getters={"name": lambda x: x["name"]},
            default=[("name", False)],
            tie_breaker_getter=lambda x: x["name"],
        )
        assert [r["name"] for r in result] == ["c", "b", "a"]

    def test_none_always_last_asc(self):
        items = [{"v": 2}, {"v": None}, {"v": 1}]
        result = sort_in_memory(
            items=items,
            parsed=[("v", False)],
            getters={"v": lambda x: x["v"]},
            default=[("v", False)],
            tie_breaker_getter=lambda x: x["v"] if x["v"] is not None else -1,
        )
        assert [r["v"] for r in result] == [1, 2, None]

    def test_none_always_last_desc(self):
        items = [{"v": 2}, {"v": None}, {"v": 1}]
        result = sort_in_memory(
            items=items,
            parsed=[("v", True)],
            getters={"v": lambda x: x["v"]},
            default=[("v", True)],
            tie_breaker_getter=lambda x: x["v"] if x["v"] is not None else -1,
        )
        # None 은 DESC 에서도 맨 뒤
        assert [r["v"] for r in result] == [2, 1, None]

    def test_multi_key_with_tie(self):
        items = [
            {"status": "a", "name": "z", "id": 1},
            {"status": "a", "name": "a", "id": 2},
            {"status": "b", "name": "a", "id": 3},
        ]
        result = sort_in_memory(
            items=items,
            parsed=[("status", False), ("name", False)],
            getters={
                "status": lambda x: x["status"],
                "name": lambda x: x["name"],
            },
            default=[("status", False)],
            tie_breaker_getter=lambda x: x["id"],
        )
        # status asc → a,a,b. a 끼리는 name asc → a,z.
        assert [r["id"] for r in result] == [2, 1, 3]

    def test_tie_breaker_stabilizes(self):
        items = [
            {"name": "a", "id": 3},
            {"name": "a", "id": 1},
            {"name": "a", "id": 2},
        ]
        result = sort_in_memory(
            items=items,
            parsed=[("name", False)],
            getters={"name": lambda x: x["name"]},
            default=[("name", False)],
            tie_breaker_getter=lambda x: x["id"],
        )
        assert [r["id"] for r in result] == [1, 2, 3]

    def test_invalid_field_rejected(self):
        with pytest.raises(HTTPException) as exc:
            sort_in_memory(
                items=[{"name": "a"}],
                parsed=[("nonexistent", False)],
                getters={"name": lambda x: x["name"]},
                default=[("name", False)],
                tie_breaker_getter=lambda x: x["name"],
            )
        assert exc.value.status_code == 422
