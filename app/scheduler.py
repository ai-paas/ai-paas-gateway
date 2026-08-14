"""대시보드 백그라운드 작업 스케줄러.

기본은 비활성. `ENABLE_SCHEDULER=true`에서만 main.py lifespan이 start_scheduler()를 호출.

운영 권장:
- 멀티 워커일 경우 worker마다 스케줄러가 도는 중복 실행을 피해야 함
- 별도 단일 컨테이너에서 `python -m app.scheduler`로 띄우거나
- PG advisory lock 패턴으로 단일 실행 보장

현재 구현은 in-process BackgroundScheduler — 단일 워커 또는 dev 환경 가정.
"""
from __future__ import annotations

import logging
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.config import settings
from app.database import SessionLocal

logger = logging.getLogger(__name__)

_scheduler: Optional[BackgroundScheduler] = None


# ---------- Job 함수들 ----------

def job_refresh_daily_stats() -> None:
    """매일 0시: raw 집계 → daily_stats upsert + mat view refresh."""
    from app.services import trends_service
    db = SessionLocal()
    try:
        n = trends_service.refresh_daily_stats(db)
        logger.info("[scheduler] daily_stats refreshed rows=%d", n)
    except Exception:
        logger.exception("[scheduler] daily_stats refresh failed")
    finally:
        db.close()


def job_flush_api_metrics() -> None:
    """매 분: in-memory request histogram → api_request_histograms 테이블 flush."""
    from app.services import api_metrics_service
    db = SessionLocal()
    try:
        n = api_metrics_service.flush_buffered_buckets(db)
        if n:
            logger.info("[scheduler] api_metrics flushed rows=%d", n)
    except Exception:
        logger.exception("[scheduler] api_metrics flush failed")
    finally:
        db.close()


def job_probe_providers() -> None:
    """매 분: provider health probe → provider_health_snapshots insert."""
    from app.services import provider_health_service
    db = SessionLocal()
    try:
        results = provider_health_service.probe_all_and_record(db)
        logger.info(
            "[scheduler] provider health probed: %s",
            ",".join(f"{r.provider}={r.status}" for r in results),
        )
    except Exception:
        logger.exception("[scheduler] provider health probe failed")
    finally:
        db.close()


def job_refresh_dashboard_services() -> None:
    """주기: 전체 서비스 카드/모니터링 스냅샷 pre-warm (MLOps detail N+1 → 캐시).

    MLOps(PROXY) 호출이 필요하므로 PROXY_ENABLED 환경에서만 의미. 멀티 워커면 단일 worker에서만 실행 권장.
    """
    from app.services import me_dashboard_service
    db = SessionLocal()
    try:
        n = me_dashboard_service.refresh_all_services_sync(db)
        logger.info("[scheduler] dashboard service snapshots refreshed services=%d", n)
    except Exception:
        logger.exception("[scheduler] dashboard service snapshot refresh failed")
    finally:
        db.close()


def job_reconcile_model_visibility() -> None:
    """주기: MLOps 모델 visibility → gateway is_catalog 캐시 정정 (backstop).

    목록 조회의 read-through 동기화가 1차 수단이고, 이 잡은 게이트웨이를 거치지 않은
    변경(파이프라인 파생 모델, MLOps 재분류)을 흡수한다. MLOps 호출 필요.
    """
    import asyncio

    from app.cruds import model_crud
    from app.services.model_service import ModelService, normalize_visibility

    db = SessionLocal()
    try:
        async def _fetch():
            svc = ModelService()  # 신규 client 인스턴스 (루프 교차 재사용 회피)
            try:
                models = []
                seen_ids = set()
                skip = 0
                page_size = 1000
                while True:
                    page = await svc.get_models(skip=skip, limit=page_size)
                    new_models = [model for model in page if model.id not in seen_ids]
                    models.extend(new_models)
                    seen_ids.update(model.id for model in new_models)
                    if len(page) < page_size or not new_models:
                        return models
                    skip += page_size
            finally:
                await svc.close()

        models = asyncio.run(_fetch())
        vis_map = {
            m.id: v == "CATALOG"
            for m in models
            if (v := normalize_visibility(m.visibility)) is not None
        }
        n = model_crud.sync_visibility_cache(db, vis_map)
        logger.info(
            "[scheduler] model visibility reconciled: upstream=%d, updated=%d",
            len(models), n,
        )
    except Exception:
        logger.exception("[scheduler] model visibility reconcile failed")
    finally:
        db.close()


def job_reconcile_workflow_mappings() -> None:
    """주기: MLOps에서 사라진 워크플로우의 stale 매핑 soft-delete.

    목록 조회 라우트는 원격 장애나 service/status 필터가 만든 빈 결과로 멀쩡한
    매핑을 지울 수 있어 이 작업을 하지 않는다. 여기서는 필터 없는 전체 목록
    (템플릿 포함)을 받아 그 목록에 없는 활성 매핑만 정리한다. MLOps 호출 필요.
    """
    import asyncio

    from app.cruds.workflow import workflow_crud
    from app.services.workflow_service import WorkflowService

    db = SessionLocal()
    try:
        async def _fetch():
            svc = WorkflowService()  # 신규 client 인스턴스 (루프 교차 재사용 회피)
            try:
                return await svc.get_workflows(page=None, page_size=None)
            finally:
                await svc.close()

        external = asyncio.run(_fetch())
        if not external:
            # 빈 응답을 "전부 삭제됨"으로 해석하면 안 된다.
            logger.warning("[scheduler] workflow reconcile skipped (upstream returned no workflows)")
            return

        n = workflow_crud.soft_delete_missing_mappings(
            db=db,
            active_surro_workflow_ids=[w.id for w in external],
            deleted_by="system:workflow-reconcile",
        )
        logger.info(
            "[scheduler] workflow mappings reconciled: upstream=%d, soft_deleted=%d",
            len(external), n,
        )
    except Exception:
        logger.exception("[scheduler] workflow mapping reconcile failed")
    finally:
        db.close()


# ---------- lifecycle ----------

def start_scheduler() -> Optional[BackgroundScheduler]:
    """스케줄러 시작. ENABLE_SCHEDULER=false면 None 반환."""
    global _scheduler
    if not settings.ENABLE_SCHEDULER:
        logger.info("[scheduler] disabled (ENABLE_SCHEDULER=false)")
        return None
    if _scheduler is not None:
        return _scheduler

    sched = BackgroundScheduler(timezone="UTC")

    # 매일 SCHEDULER_TRENDS_HOUR시(UTC)에 daily_stats 재계산
    sched.add_job(
        job_refresh_daily_stats,
        trigger=CronTrigger(hour=settings.SCHEDULER_TRENDS_HOUR, minute=5),
        id="refresh_daily_stats",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )

    # mat view refresh
    sched.add_job(
        job_refresh_daily_stats,  # daily_stats refresh가 mat view까지 갱신
        trigger=IntervalTrigger(minutes=settings.SCHEDULER_MV_REFRESH_MINUTES),
        id="refresh_mv_daily_trends",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )

    # api metrics flush — middleware의 in-process buffer에 의존하므로
    # 별도 worker 프로세스에서는 의미 없음 (빈 버퍼만 flush됨). SCHEDULER_INCLUDE_API_METRICS=false면 건너뜀.
    if settings.SCHEDULER_INCLUDE_API_METRICS:
        sched.add_job(
            job_flush_api_metrics,
            trigger=IntervalTrigger(minutes=settings.SCHEDULER_API_METRICS_FLUSH_MINUTES),
            id="flush_api_metrics",
            replace_existing=True,
            coalesce=True,
            max_instances=1,
        )
    else:
        logger.info("[scheduler] api_metrics flush job skipped (SCHEDULER_INCLUDE_API_METRICS=false)")

    # provider health probe
    sched.add_job(
        job_probe_providers,
        trigger=IntervalTrigger(minutes=settings.SCHEDULER_PROVIDER_HEALTH_MINUTES),
        id="probe_providers",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )

    # 개인 대시보드 서비스 카드/모니터링 pre-warm — MLOps 호출 필요(SCHEDULER_INCLUDE_DASHBOARD).
    # 미사용 시에도 endpoint가 TTL 기반 lazy refresh로 동작하므로 default off.
    if settings.SCHEDULER_INCLUDE_DASHBOARD:
        sched.add_job(
            job_refresh_dashboard_services,
            trigger=IntervalTrigger(minutes=settings.SCHEDULER_DASHBOARD_REFRESH_MINUTES),
            id="refresh_dashboard_services",
            replace_existing=True,
            coalesce=True,
            max_instances=1,
        )
    else:
        logger.info("[scheduler] dashboard pre-warm job skipped (SCHEDULER_INCLUDE_DASHBOARD=false)")

    # 모델 visibility reconcile — MLOps 호출 필요(SCHEDULER_INCLUDE_MODEL_VISIBILITY).
    # 목록 조회 read-through 동기화의 backstop이므로 default off.
    if settings.SCHEDULER_INCLUDE_MODEL_VISIBILITY:
        sched.add_job(
            job_reconcile_model_visibility,
            trigger=IntervalTrigger(minutes=settings.SCHEDULER_MODEL_VISIBILITY_MINUTES),
            id="reconcile_model_visibility",
            replace_existing=True,
            coalesce=True,
            max_instances=1,
        )
    else:
        logger.info(
            "[scheduler] model visibility reconcile job skipped (SCHEDULER_INCLUDE_MODEL_VISIBILITY=false)"
        )

    # 워크플로우 매핑 reconcile — 목록 조회가 stale 매핑을 지우지 않으므로 유일한 정리 주체.
    if settings.SCHEDULER_INCLUDE_WORKFLOW_RECONCILE:
        sched.add_job(
            job_reconcile_workflow_mappings,
            trigger=IntervalTrigger(minutes=settings.SCHEDULER_WORKFLOW_RECONCILE_MINUTES),
            id="reconcile_workflow_mappings",
            replace_existing=True,
            coalesce=True,
            max_instances=1,
        )
    else:
        logger.info(
            "[scheduler] workflow mapping reconcile job skipped (SCHEDULER_INCLUDE_WORKFLOW_RECONCILE=false)"
        )

    sched.start()
    _scheduler = sched
    logger.info("[scheduler] started with %d jobs", len(sched.get_jobs()))
    return sched


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is None:
        return
    try:
        _scheduler.shutdown(wait=False)
        logger.info("[scheduler] stopped")
    except Exception:
        logger.exception("[scheduler] shutdown failed")
    finally:
        _scheduler = None


def get_scheduler() -> Optional[BackgroundScheduler]:
    return _scheduler


if __name__ == "__main__":
    # 운영용 standalone 진입점 — 별도 컨테이너에서 실행
    import time

    from app.logging_config import configure_logging

    configure_logging()
    # 강제로 활성화하지 않음 — env에서 ENABLE_SCHEDULER=true 설정 필요
    if not settings.ENABLE_SCHEDULER:
        logger.error("ENABLE_SCHEDULER=true가 필요합니다.")
        raise SystemExit(1)

    start_scheduler()
    try:
        while True:
            time.sleep(60)
    except (KeyboardInterrupt, SystemExit):
        stop_scheduler()
