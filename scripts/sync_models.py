"""MLOps 모델과 gateway 모델 매핑을 검증·보정한다.

규칙:
  1) MLOps visibility가 CATALOG/CUSTOM이면 gateway is_catalog 캐시도 동일하게 갱신
  2) 활성 gateway 매핑이 없는 모델만 admin 소유로 생성
  3) visibility 누락 시 기존 카탈로그 이력이 있으면 CATALOG, 아니면 admin CUSTOM

기본 실행은 검증만 수행한다. 실제 반영에는 ``--apply``가 필요하다.

실행:
    python -m scripts.sync_models
    python -m scripts.sync_models --apply
"""

import argparse
import asyncio
import json
from collections import Counter, defaultdict
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.member import Member
from app.models.model import Model
from app.services.model_service import model_service, normalize_visibility


ADMIN_MEMBER_ID = "admin"
PAGE_SIZE = 1000


def _serialize_summary(summary: dict[str, Any]) -> str:
    return json.dumps(summary, ensure_ascii=False, indent=2, default=str)


def _validated_visibility(model: Any) -> Optional[str]:
    raw = getattr(model, "visibility", None)
    normalized = normalize_visibility(raw)
    if normalized is not None:
        return normalized
    if raw is None or not str(raw).strip():
        return None
    raise ValueError(
        f"Unsupported visibility for model {getattr(model, 'id', None)}: {raw}"
    )


def _build_reconciliation_plan(
        external_models: list[Any],
        mapping_rows: list[Model],
) -> dict[str, Any]:
    """외부 모델과 기존 매핑으로 변경 계획을 계산한다. DB는 변경하지 않는다."""
    rows_by_id: dict[int, list[Model]] = defaultdict(list)
    active_rows_by_id: dict[int, list[Model]] = defaultdict(list)
    for row in mapping_rows:
        rows_by_id[row.surro_model_id].append(row)
        if row.deleted_at is None and row.is_active:
            active_rows_by_id[row.surro_model_id].append(row)

    creates: list[dict[str, Any]] = []
    updates: list[dict[str, Any]] = []
    visibility_counts: Counter[str] = Counter()
    missing_visibility_ids: list[int] = []

    for model in external_models:
        visibility = _validated_visibility(model)
        historical_rows = rows_by_id.get(model.id, [])
        if visibility is None:
            missing_visibility_ids.append(model.id)
            cached_catalog = any(row.is_catalog for row in historical_rows)
            resolved_visibility = "CATALOG" if cached_catalog else "CUSTOM"
            visibility_counts["MISSING"] += 1
        else:
            resolved_visibility = visibility
            visibility_counts[visibility] += 1
            desired_is_catalog = visibility == "CATALOG"
            for row in historical_rows:
                if row.is_catalog != desired_is_catalog:
                    updates.append({
                        "row": row,
                        "surro_model_id": model.id,
                        "from_is_catalog": row.is_catalog,
                        "to_is_catalog": desired_is_catalog,
                    })

        if active_rows_by_id.get(model.id):
            continue

        # ponytail: upstream visibility 누락 모델은 admin CUSTOM으로 임시 보정한다.
        # MLOps가 visibility를 필수 응답으로 보장하면 이 fallback과 temporary 표식을 제거한다.
        creates.append({
            "surro_model_id": model.id,
            "model_name": getattr(model, "name", None),
            "is_catalog": resolved_visibility == "CATALOG",
            "temporary": visibility is None and resolved_visibility == "CUSTOM",
        })

    return {
        "creates": creates,
        "updates": updates,
        "visibility_counts": dict(sorted(visibility_counts.items())),
        "missing_visibility_ids": sorted(missing_visibility_ids),
    }


async def _fetch_external_models(admin: Member) -> list[Any]:
    user_info = {
        "member_id": admin.member_id,
        "role": admin.role,
        "name": admin.name,
    }
    external_models: list[Any] = []
    seen_ids: set[int] = set()
    skip = 0
    while True:
        batch = await model_service.get_models(
            skip=skip,
            limit=PAGE_SIZE,
            user_info=user_info,
        )
        new_models = [model for model in batch if model.id not in seen_ids]
        external_models.extend(new_models)
        seen_ids.update(model.id for model in new_models)
        if len(batch) < PAGE_SIZE or not new_models:
            return external_models
        skip += PAGE_SIZE


async def sync_admin_models(apply: bool = False) -> dict[str, Any]:
    db: Session = SessionLocal()
    try:
        admin = db.query(Member).filter(Member.member_id == ADMIN_MEMBER_ID).first()
        if not admin:
            raise RuntimeError(f"Admin member not found: {ADMIN_MEMBER_ID}")

        external_models = await _fetch_external_models(admin)
        external_ids = [model.id for model in external_models]
        mapping_rows = (
            db.query(Model).filter(Model.surro_model_id.in_(external_ids)).all()
            if external_ids else []
        )
        plan = _build_reconciliation_plan(external_models, mapping_rows)

        if apply:
            try:
                for update in plan["updates"]:
                    row = update["row"]
                    row.is_catalog = update["to_is_catalog"]
                    row.updated_by = "visibility-sync"

                for create in plan["creates"]:
                    metadata = None
                    if create["temporary"]:
                        metadata = json.dumps({
                            "visibility_source": "missing",
                            "temporary_admin_custom": True,
                        })
                    db.add(Model(
                        surro_model_id=create["surro_model_id"],
                        created_by=admin.member_id,
                        updated_by=admin.member_id,
                        name=create["model_name"],
                        is_catalog=create["is_catalog"],
                        metadatas=metadata,
                    ))
                db.commit()
            except Exception:
                db.rollback()
                raise

        active_mapping_count = db.query(Model).filter(
            Model.deleted_at.is_(None),
            Model.is_active.is_(True),
        ).count()
        creates = plan["creates"]
        updates = plan["updates"]
        return {
            "applied": apply,
            "admin_member_id": admin.member_id,
            "external_model_count": len(external_models),
            "external_visibility_counts": plan["visibility_counts"],
            "missing_visibility_ids": plan["missing_visibility_ids"],
            "planned_mapping_count": len(creates),
            "planned_catalog_mapping_ids": sorted(
                item["surro_model_id"] for item in creates if item["is_catalog"]
            ),
            "planned_custom_mapping_ids": sorted(
                item["surro_model_id"] for item in creates if not item["is_catalog"]
            ),
            "temporary_custom_mapping_ids": sorted(
                item["surro_model_id"] for item in creates if item["temporary"]
            ),
            "planned_cache_updates": [
                {
                    "surro_model_id": item["surro_model_id"],
                    "from_is_catalog": item["from_is_catalog"],
                    "to_is_catalog": item["to_is_catalog"],
                }
                for item in updates
            ],
            "active_gateway_mapping_count": active_mapping_count,
        }
    finally:
        db.close()
        await model_service.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="검증된 변경 계획을 gateway DB에 반영",
    )
    args = parser.parse_args()
    result = asyncio.run(sync_admin_models(apply=args.apply))
    print(_serialize_summary(result))
