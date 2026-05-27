"""공용 정렬 유틸.

RFC-style `sort=-field,field2` 쿼리 파라미터를 파싱해 SQL `ORDER BY` 절 또는
인메모리 정렬 키로 변환한다. 허용 필드 화이트리스트 검증, 중복/빈 토큰 거절(422),
tie-breaker 자동 부가(페이지 경계 안정성), NULL 값 항상 마지막 규칙을 포함한다.
"""
from functools import cmp_to_key
from typing import Any, Callable, List, Optional, Tuple

from fastapi import HTTPException, status
from sqlalchemy.orm.attributes import InstrumentedAttribute
from sqlalchemy.sql.elements import UnaryExpression


SortSpec = List[Tuple[str, bool]]
ColumnSpec = List[Tuple[InstrumentedAttribute, bool]]


def parse_sort(raw: Optional[str]) -> SortSpec:
    """`sort` 쿼리 문자열을 `(field, desc)` 튜플 리스트로 파싱한다.

    - `None` 또는 빈 문자열 → 빈 리스트
    - `-` 접두사 = DESC, 접두사 없음 = ASC
    - 빈 토큰(`,name` 등) → 422
    - 중복 필드(`name,-name`) → 422
    """
    if raw is None or not raw.strip():
        return []

    parsed: SortSpec = []
    seen: set = set()
    for token in raw.split(","):
        token = token.strip()
        if not token:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="invalid sort: empty token",
            )
        desc = token.startswith("-")
        field = token[1:] if desc else token
        if not field:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="invalid sort: empty field",
            )
        if field in seen:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"invalid sort: duplicate field '{field}'",
            )
        seen.add(field)
        parsed.append((field, desc))
    return parsed


def _to_order_clause(col: InstrumentedAttribute, desc: bool) -> UnaryExpression:
    """SQLAlchemy 컬럼을 `ORDER BY` 절로 변환. NULL 은 항상 뒤."""
    return (col.desc() if desc else col.asc()).nullslast()


def resolve_sort_columns(
    parsed: SortSpec,
    allowed: dict,
    default: ColumnSpec,
    tie_breaker: InstrumentedAttribute,
) -> List[UnaryExpression]:
    """SQL `ORDER BY` 절용 `UnaryExpression` 리스트를 만든다.

    - `parsed` 가 비면 `default` 사용
    - 화이트리스트 외 필드 → 422
    - 마지막에 `tie_breaker asc` 를 부가(사용자 지정 중 같은 컬럼이 이미 있으면 생략)
    """
    clauses: List[UnaryExpression] = []
    used_keys: set = set()

    if parsed:
        for field, desc in parsed:
            if field not in allowed:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"invalid sort field: {field}",
                )
            col = allowed[field]
            clauses.append(_to_order_clause(col, desc))
            used_keys.add(col.key)
    else:
        for col, desc in default:
            clauses.append(_to_order_clause(col, desc))
            used_keys.add(col.key)

    if tie_breaker.key not in used_keys:
        clauses.append(_to_order_clause(tie_breaker, desc=False))

    return clauses


def sort_in_memory(
    items: list,
    parsed: SortSpec,
    getters: dict,
    default: List[Tuple[str, bool]],
    tie_breaker_getter: Callable[[Any], Any],
) -> list:
    """dict/객체 리스트를 다중 키로 정렬한다. NULL 은 항상 마지막.

    - `parsed` 가 비면 `default` 사용
    - `getters` 는 `{field_name: lambda item: item.xxx}` 형태 (dict/객체 공용)
    - 마지막 우선순위에 `tie_breaker_getter` 를 asc 로 부가
    """
    spec = parsed if parsed else [(f, d) for f, d in default]

    resolved: List[Tuple[Callable[[Any], Any], bool]] = []
    for field, desc in spec:
        if field not in getters:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"invalid sort field: {field}",
            )
        resolved.append((getters[field], desc))
    resolved.append((tie_breaker_getter, False))

    def _cmp(a, b) -> int:
        for getter, desc in resolved:
            va = getter(a)
            vb = getter(b)
            if va is None and vb is None:
                continue
            if va is None:
                return 1
            if vb is None:
                return -1
            if va == vb:
                continue
            if va < vb:
                return 1 if desc else -1
            return -1 if desc else 1
        return 0

    return sorted(items, key=cmp_to_key(_cmp))
