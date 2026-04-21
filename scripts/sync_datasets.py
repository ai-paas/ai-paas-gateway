import asyncio
import json
from typing import Any

from sqlalchemy.orm import Session

from app.cruds.dataset import dataset_crud
from app.database import SessionLocal
from app.models.member import Member
from app.services.dataset_service import dataset_service

ADMIN_MEMBER_ID = "admin"


def _serialize_summary(summary: dict[str, Any]) -> str:
    return json.dumps(summary, ensure_ascii=False, indent=2, default=str)


async def sync_admin_datasets() -> dict[str, Any]:
    db: Session = SessionLocal()
    try:
        admin = db.query(Member).filter(Member.member_id == ADMIN_MEMBER_ID).first()
        if not admin:
            raise RuntimeError(f"Admin member not found: {ADMIN_MEMBER_ID}")

        external_response = await dataset_service.get_datasets(
            page=None,
            page_size=None,
            user_info={
                "member_id": admin.member_id,
                "role": admin.role,
                "name": admin.name,
            },
        )

        external_datasets = external_response.data
        external_ids = [dataset.id for dataset in external_datasets]

        synced = []
        for dataset in external_datasets:
            mapping = dataset_crud.upsert_dataset_mapping(
                db=db,
                surro_dataset_id=dataset.id,
                member_id=admin.member_id,
                dataset_name=dataset.name,
            )
            synced.append(
                {
                    "db_id": mapping.id,
                    "surro_dataset_id": mapping.surro_dataset_id,
                    "name": mapping.name,
                    "created_by": mapping.created_by,
                    "is_active": mapping.is_active,
                }
            )

        soft_deleted_count = dataset_crud.soft_delete_missing_mappings(
            db=db,
            member_id=admin.member_id,
            active_surro_dataset_ids=external_ids,
            deleted_by=admin.member_id,
        )

        remaining_active = dataset_crud.get_dataset_mappings_by_member_id(
            db=db,
            member_id=admin.member_id,
            skip=0,
            limit=10000,
        )

        return {
            "admin_member_id": admin.member_id,
            "external_dataset_count": len(external_datasets),
            "external_dataset_ids": external_ids,
            "synced": synced,
            "soft_deleted_count": soft_deleted_count,
            "remaining_active_dataset_ids": sorted(remaining_active.keys()),
        }
    finally:
        db.close()
        await dataset_service.close()


if __name__ == "__main__":
    result = asyncio.run(sync_admin_datasets())
    print(_serialize_summary(result))
