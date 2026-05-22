"""API 응답시간 히스토그램 수집 / 집계 service.

middleware가 `record()`를 호출해 in-memory buffer에 누적.
스케줄러가 `flush_buffered_buckets()`를 호출해 DB로 옮긴다 (분 단위 bucket).

p95는 stored bucket 누적합 보간으로 근사 (정확값 아님).
"""
from __future__ import annotations

import re
import threading
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models.api_metric import ApiRequestHistogram

# Prometheus-like bucket 경계 (ms). 999999는 +Inf 의미.
BUCKETS_MS: List[int] = [10, 50, 100, 250, 500, 1000, 5000, 999999]

_UUID_RE = re.compile(
    r"/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE
)
_INT_RE = re.compile(r"/\d+")


def normalize_path(path: str) -> str:
    """경로의 path-param 부분을 `{id}`로 정규화."""
    p = _UUID_RE.sub("/{id}", path)
    p = _INT_RE.sub("/{id}", p)
    return p


def _le_bucket(duration_ms: float) -> int:
    for b in BUCKETS_MS:
        if duration_ms <= b:
            return b
    return BUCKETS_MS[-1]


def _status_class(status_code: int) -> str:
    return f"{status_code // 100}xx"


# (bucket_ts, path_pattern, status_class, le_bucket_ms) -> dict(count, sum, max)
_BufferKey = Tuple[datetime, str, str, int]
_buffer: Dict[_BufferKey, Dict[str, int]] = {}
_lock = threading.Lock()


def record(path: str, status_code: int, duration_ms: float) -> None:
    """middleware에서 매 요청마다 호출. in-memory buffer에 누적."""
    bucket_ts = datetime.utcnow().replace(second=0, microsecond=0)
    path_pattern = normalize_path(path)
    status_class = _status_class(status_code)
    le = _le_bucket(duration_ms)
    key = (bucket_ts, path_pattern, status_class, le)
    dur = int(round(duration_ms))
    with _lock:
        entry = _buffer.get(key)
        if entry is None:
            _buffer[key] = {"count": 1, "sum": dur, "max": dur}
        else:
            entry["count"] += 1
            entry["sum"] += dur
            if dur > entry["max"]:
                entry["max"] = dur


def _snapshot_and_clear() -> Dict[_BufferKey, Dict[str, int]]:
    with _lock:
        snapshot = _buffer.copy()
        _buffer.clear()
    return snapshot


def flush_buffered_buckets(db: Session) -> int:
    """buffer를 DB에 upsert. 반환: 처리된 unique bucket 수."""
    snapshot = _snapshot_and_clear()
    if not snapshot:
        return 0

    rows = [
        {
            "bucket_ts": k[0],
            "path_pattern": k[1],
            "status_class": k[2],
            "le_bucket_ms": k[3],
            "count": v["count"],
            "sum_duration_ms": v["sum"],
            "max_duration_ms": v["max"],
            "generated_at": datetime.utcnow(),
        }
        for k, v in snapshot.items()
    ]

    if db.bind.dialect.name == "postgresql":
        stmt = pg_insert(ApiRequestHistogram.__table__).values(rows)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_api_hist_key",
            set_={
                "count": ApiRequestHistogram.__table__.c.count + stmt.excluded.count,
                "sum_duration_ms": ApiRequestHistogram.__table__.c.sum_duration_ms + stmt.excluded.sum_duration_ms,
                "max_duration_ms": func.greatest(
                    ApiRequestHistogram.__table__.c.max_duration_ms, stmt.excluded.max_duration_ms
                ),
                "generated_at": stmt.excluded.generated_at,
            },
        )
        db.execute(stmt)
    else:
        # SQLite: 키 매칭 row를 직접 조회·합산하여 update, 없으면 insert
        for r in rows:
            existing = db.query(ApiRequestHistogram).filter(
                ApiRequestHistogram.bucket_ts == r["bucket_ts"],
                ApiRequestHistogram.path_pattern == r["path_pattern"],
                ApiRequestHistogram.status_class == r["status_class"],
                ApiRequestHistogram.le_bucket_ms == r["le_bucket_ms"],
            ).one_or_none()
            if existing:
                existing.count += r["count"]
                existing.sum_duration_ms += r["sum_duration_ms"]
                existing.max_duration_ms = max(existing.max_duration_ms, r["max_duration_ms"])
                existing.generated_at = r["generated_at"]
            else:
                db.add(ApiRequestHistogram(**r))
    db.commit()
    return len(rows)


# ---------- 조회 / p95 근사 ----------

def _percentile_from_buckets(
    bucket_counts: List[Tuple[int, int]],
    percentile: float,
    max_observed: Optional[int] = None,
) -> Optional[int]:
    """bucket_counts: [(le_bucket_ms, count), ...] le 오름차순 가정.

    Prometheus histogram_quantile 식의 비누적 bucket 변형. 정확값 아님.

    - +Inf bucket(le=999999)에 데이터가 있으면 `max_observed`(실측 최대)를 우선 반환
    - 보간 결과가 `max_observed`를 초과하지 않도록 capping (sparse bucket 보호)
    """
    total = sum(c for _, c in bucket_counts)
    if total == 0:
        return None

    target = total * percentile
    cumulative = 0
    prev_le = 0
    result: Optional[int] = None

    for le, c in sorted(bucket_counts, key=lambda x: x[0]):
        cumulative += c
        if cumulative >= target:
            if le == 999999:
                # +Inf bucket: 실측 max가 정답에 가장 가까움
                result = max_observed if max_observed is not None else prev_le
            elif cumulative == c:
                # 첫 bucket 단독 — bucket 상한이 곧 상한
                result = le
            else:
                # 이전 경계와 현재 경계 사이 선형 보간
                ratio = (target - (cumulative - c)) / c
                result = int(round(prev_le + (le - prev_le) * ratio))
            break
        prev_le = le

    if result is None:
        return None
    if max_observed is not None:
        return min(result, max_observed)
    return result


def get_api_metrics(
    db: Session,
    since: Optional[datetime] = None,
    path_pattern: Optional[str] = None,
) -> Dict:
    """since(기본 24시간 전) 이후 path별 status_class별 합산 + p95 근사.

    응답 구조:
    {
      "since": ..., "generated_at": ...,
      "paths": [
        {"path_pattern": "/x", "status_class": "2xx", "count": 100, "avg_ms": 23, "max_ms": 980, "p95_ms": 410}, ...
      ]
    }
    """
    if since is None:
        since = datetime.utcnow() - timedelta(hours=24)

    query = db.query(
        ApiRequestHistogram.path_pattern,
        ApiRequestHistogram.status_class,
        ApiRequestHistogram.le_bucket_ms,
        func.sum(ApiRequestHistogram.count).label("count"),
        func.sum(ApiRequestHistogram.sum_duration_ms).label("sum_ms"),
        func.max(ApiRequestHistogram.max_duration_ms).label("max_ms"),
    ).filter(ApiRequestHistogram.bucket_ts >= since)
    if path_pattern:
        query = query.filter(ApiRequestHistogram.path_pattern == path_pattern)

    rows = query.group_by(
        ApiRequestHistogram.path_pattern,
        ApiRequestHistogram.status_class,
        ApiRequestHistogram.le_bucket_ms,
    ).all()

    # path+status별 그룹핑
    grouped: Dict[Tuple[str, str], Dict] = {}
    for r in rows:
        key = (r.path_pattern, r.status_class)
        g = grouped.setdefault(key, {
            "path_pattern": r.path_pattern,
            "status_class": r.status_class,
            "count": 0,
            "sum_ms": 0,
            "max_ms": 0,
            "_buckets": [],
        })
        g["count"] += int(r.count or 0)
        g["sum_ms"] += int(r.sum_ms or 0)
        if (r.max_ms or 0) > g["max_ms"]:
            g["max_ms"] = int(r.max_ms or 0)
        g["_buckets"].append((int(r.le_bucket_ms), int(r.count or 0)))

    paths = []
    for g in grouped.values():
        avg_ms = round(g["sum_ms"] / g["count"], 2) if g["count"] else None
        p95 = _percentile_from_buckets(g["_buckets"], 0.95, max_observed=g["max_ms"])
        paths.append({
            "path_pattern": g["path_pattern"],
            "status_class": g["status_class"],
            "count": g["count"],
            "avg_ms": avg_ms,
            "max_ms": g["max_ms"],
            "p95_ms": p95,
        })
    paths.sort(key=lambda x: (x["path_pattern"], x["status_class"]))

    return {
        "since": since,
        "generated_at": datetime.utcnow(),
        "buckets_ms": BUCKETS_MS,
        "paths": paths,
    }
