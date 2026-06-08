"""MLOps 모델 목록을 admin 계정으로 동기화한다.

기존 `sync_datasets.py`와 동일한 3단계 패턴:
  1) MLOps `GET /models`로 외부 모델 전체 조회
  2) admin 계정 기준으로 upsert (visibility=CATALOG → is_catalog=True)
  3) 외부에 없는 활성 매핑은 soft-delete

실행:
    python scripts/sync_models.py
"""

import asyncio
import json
from typing import Any

from sqlalchemy.orm import Session

from app.cruds.model import model_crud
from app.database import SessionLocal
from app.models.member import Member
from app.services.model_service import model_service

ADMIN_MEMBER_ID = "admin"
# MLOps `GET /models`의 page_size 상한 (서버측 제약: <= 1000)
PAGE_SIZE = 1000
# 로컬 DB 조회 시 활성 매핑을 넉넉히 가져오기 위한 상한
LOCAL_FETCH_LIMIT = 100000


def _serialize_summary(summary: dict[str, Any]) -> str:
    return json.dumps(summary, ensure_ascii=False, indent=2, default=str)


async def sync_admin_models() -> dict[str, Any]:
    db: Session = SessionLocal()
    try:
        admin = db.query(Member).filter(Member.member_id == ADMIN_MEMBER_ID).first()
        if not admin:
            raise RuntimeError(f"Admin member not found: {ADMIN_MEMBER_ID}")

        user_info = {
            "member_id": admin.member_id,
            "role": admin.role,
            "name": admin.name,
        }

        external_models = []
        skip = 0
        while True:
            batch = await model_service.get_models(
                skip=skip,
                limit=PAGE_SIZE,
                user_info=user_info,
            )
            if not batch:
                break
            external_models.extend(batch)
            if len(batch) < PAGE_SIZE:
                break
            skip += PAGE_SIZE

        external_ids = [model.id for model in external_models]

        synced = []
        for model in external_models:
            is_catalog = (getattr(model, "visibility", None) == "CATALOG")
            mapping = model_crud.upsert_model_mapping(
                db=db,
                surro_model_id=model.id,
                member_id=admin.member_id,
                model_name=model.name,
                is_catalog=is_catalog,
            )
            synced.append(
                {
                    "db_id": mapping.id,
                    "surro_model_id": mapping.surro_model_id,
                    "name": mapping.name,
                    "visibility": getattr(model, "visibility", None),
                    "is_catalog": mapping.is_catalog,
                    "created_by": mapping.created_by,
                    "is_active": mapping.is_active,
                }
            )

        soft_deleted_count = model_crud.soft_delete_missing_mappings(
            db=db,
            member_id=admin.member_id,
            active_surro_model_ids=external_ids,
            deleted_by=admin.member_id,
        )

        remaining_active_ids = model_crud.get_models_by_member_id(
            db=db,
            member_id=admin.member_id,
            skip=0,
            limit=LOCAL_FETCH_LIMIT,
        )

        return {
            "admin_member_id": admin.member_id,
            "external_model_count": len(external_models),
            "external_model_ids": external_ids,
            "synced": synced,
            "soft_deleted_count": soft_deleted_count,
            "remaining_active_model_ids": sorted(remaining_active_ids),
        }
    finally:
        db.close()
        await model_service.close()


if __name__ == "__main__":
    result = asyncio.run(sync_admin_models())
    print(_serialize_summary(result))
