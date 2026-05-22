"""대시보드 트렌드/시계열 집계 service.

저장 계층 우선순위(자동 fallback):
1. `daily_stats` 테이블 — 스케줄러가 채움. 가장 빠름.
2. PostgreSQL view `v_daily_trends` — 실시간. 데이터 적을 때 OK.
3. ORM raw 집계 — SQLite/테스트 환경 폴백.

`refresh_daily_stats()` 호출 시 raw 집계 결과를 `daily_stats`에 upsert.
PostgreSQL 환경에선 `mv_daily_trends`도 함께 REFRESH (CONCURRENTLY).
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Type

from sqlalchemy import func, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models import (
    DailyStat,
    Dataset,
    Experiment,
    KnowledgeBase,
    Member,
    Model,
    ModelImprovement,
    Prompt,
    Service,
    Workflow,
)
from app.schemas.dashboard import TrendPoint, TrendSeries, TrendsResponse

logger = logging.getLogger(__name__)


# (model_cls, domain, has_soft_delete)
_ASSET_DOMAINS: List[tuple[Type, str, bool]] = [
    (Service, "service", False),
    (Workflow, "workflow", False),
    (Model, "model", True),
    (ModelImprovement, "model_improvement", True),
    (Dataset, "dataset", True),
    (Experiment, "experiment", True),
    (KnowledgeBase, "knowledge_base", True),
    (Prompt, "prompt", True),
]

ALLOWED_DOMAINS = {d for _, d, _ in _ASSET_DOMAINS} | {"signup"}


# ---------- raw 집계 (SQLite/PG 호환) ----------

def _to_date(value) -> Optional[date]:
    """sqlite은 string 'YYYY-MM-DD', PG는 date 객체로 반환되는 차이 흡수."""
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    s = str(value)[:10]
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


def _bucket_expr(column):
    """dialect-agnostic 일자 추출. PG/SQLite 모두 DATE() 함수 지원."""
    return func.date(column)


def _aggregate_creations(db: Session, model_cls: Type) -> Dict[date, int]:
    rows = (
        db.query(_bucket_expr(model_cls.created_at).label("bucket"),
                 func.count(model_cls.id).label("value"))
        .group_by("bucket")
        .all()
    )
    out: Dict[date, int] = {}
    for r in rows:
        d = _to_date(r.bucket)
        if d is not None:
            out[d] = r.value
    return out


def _aggregate_deletions(db: Session, model_cls: Type) -> Dict[date, int]:
    if not hasattr(model_cls, "deleted_at"):
        return {}
    rows = (
        db.query(_bucket_expr(model_cls.deleted_at).label("bucket"),
                 func.count(model_cls.id).label("value"))
        .filter(model_cls.deleted_at.isnot(None))
        .group_by("bucket")
        .all()
    )
    out: Dict[date, int] = {}
    for r in rows:
        d = _to_date(r.bucket)
        if d is not None:
            out[d] = r.value
    return out


def _aggregate_signups(db: Session) -> Dict[date, int]:
    rows = (
        db.query(_bucket_expr(Member.created_at).label("bucket"),
                 func.count(Member.id).label("value"))
        .group_by("bucket")
        .all()
    )
    out: Dict[date, int] = {}
    for r in rows:
        d = _to_date(r.bucket)
        if d is not None:
            out[d] = r.value
    return out


# ---------- daily_stats upsert ----------

def _upsert_daily_stats(db: Session, records: List[Dict]) -> int:
    """records: [{'date':..., 'domain':..., 'metric':..., 'value':...}, ...]

    PG는 ON CONFLICT, SQLite/others는 delete+insert 폴백.
    """
    if not records:
        return 0

    dialect = db.bind.dialect.name
    now = datetime.utcnow()

    if dialect == "postgresql":
        stmt = pg_insert(DailyStat.__table__).values([
            {
                "date": r["date"],
                "domain": r["domain"],
                "metric": r["metric"],
                "value": r["value"],
                "generated_at": now,
            }
            for r in records
        ])
        stmt = stmt.on_conflict_do_update(
            constraint="uq_daily_stats_date_domain_metric",
            set_={"value": stmt.excluded.value, "generated_at": stmt.excluded.generated_at},
        )
        db.execute(stmt)
    else:
        # SQLite: 키 기반으로 기존 row 삭제 후 신규 insert
        for r in records:
            db.query(DailyStat).filter(
                DailyStat.date == r["date"],
                DailyStat.domain == r["domain"],
                DailyStat.metric == r["metric"],
            ).delete()
        db.bulk_insert_mappings(DailyStat, [
            {
                "date": r["date"],
                "domain": r["domain"],
                "metric": r["metric"],
                "value": r["value"],
                "generated_at": now,
            }
            for r in records
        ])
    db.commit()
    return len(records)


def refresh_daily_stats(db: Session) -> int:
    """raw 집계 → daily_stats upsert. PG에선 mv_daily_trends도 REFRESH.

    반환: upsert된 행 수.
    """
    records: List[Dict] = []

    for model_cls, domain, _ in _ASSET_DOMAINS:
        for d, v in _aggregate_creations(db, model_cls).items():
            records.append({"date": d, "domain": domain, "metric": "created", "value": v})
        for d, v in _aggregate_deletions(db, model_cls).items():
            records.append({"date": d, "domain": domain, "metric": "deleted", "value": v})

    for d, v in _aggregate_signups(db).items():
        records.append({"date": d, "domain": "signup", "metric": "created", "value": v})

    n = _upsert_daily_stats(db, records)

    if db.bind.dialect.name == "postgresql":
        try:
            db.execute(text("REFRESH MATERIALIZED VIEW CONCURRENTLY mv_daily_trends"))
            db.commit()
        except Exception:
            logger.exception("mv_daily_trends refresh failed (non-fatal)")
            db.rollback()

    return n


# ---------- 조회 ----------

def get_trends(
    db: Session,
    days: int = 30,
    domain: Optional[str] = None,
    end_date: Optional[date] = None,
) -> TrendsResponse:
    """days(기본 30) 범위의 일별 트렌드. domain 지정 시 그 도메인만.

    소스 우선순위: daily_stats 테이블 → raw 집계 폴백.
    """
    end = end_date or datetime.utcnow().date()
    start = end - timedelta(days=days - 1)

    if domain is not None and domain not in ALLOWED_DOMAINS:
        raise ValueError(f"unknown domain: {domain}")

    query = db.query(DailyStat).filter(
        DailyStat.date >= start, DailyStat.date <= end
    )
    if domain:
        query = query.filter(DailyStat.domain == domain)

    rows = query.order_by(DailyStat.domain, DailyStat.metric, DailyStat.date).all()
    source = "daily_stats"

    if not rows:
        # 테이블이 비었으면 raw 집계로 폴백
        rows = _raw_fallback_rows(db, start, end, domain)
        source = "live"

    series_map: Dict[tuple[str, str], List[TrendPoint]] = {}
    for r in rows:
        key = (r.domain if hasattr(r, "domain") else r["domain"],
               r.metric if hasattr(r, "metric") else r["metric"])
        d = r.date if hasattr(r, "date") else r["date"]
        v = r.value if hasattr(r, "value") else r["value"]
        series_map.setdefault(key, []).append(TrendPoint(date=d, value=v))

    series = [
        TrendSeries(domain=dom, metric=met, points=pts)
        for (dom, met), pts in sorted(series_map.items())
    ]
    return TrendsResponse(
        start=start, end=end, days=days,
        source=source, series=series,
        generated_at=datetime.utcnow(),
    )


def _raw_fallback_rows(
    db: Session, start: date, end: date, domain: Optional[str]
) -> List[Dict]:
    """daily_stats가 비어있을 때 실시간 폴백 (raw 집계). 응답 형식 통일을 위해 dict 리스트."""
    out: List[Dict] = []
    for model_cls, dom, _ in _ASSET_DOMAINS:
        if domain and domain != dom:
            continue
        for d, v in _aggregate_creations(db, model_cls).items():
            if start <= d <= end:
                out.append({"date": d, "domain": dom, "metric": "created", "value": v})
        for d, v in _aggregate_deletions(db, model_cls).items():
            if start <= d <= end:
                out.append({"date": d, "domain": dom, "metric": "deleted", "value": v})

    if domain is None or domain == "signup":
        for d, v in _aggregate_signups(db).items():
            if start <= d <= end:
                out.append({"date": d, "domain": "signup", "metric": "created", "value": v})
    return out
