"""scripts/sync_datasets.py — MLOps 가 빈 목록을 주어도 admin 데이터셋 매핑을 지우지 않는다."""
import asyncio
from types import SimpleNamespace

from app.cruds.dataset import dataset_crud
from scripts import sync_datasets


def test_sync_keeps_mappings_when_upstream_returns_empty(db, admin_member, monkeypatch):
    kept = dataset_crud.create_dataset_mapping(
        db, 5100, admin_member.member_id, dataset_name="kept-dataset"
    )

    async def empty_get_datasets(**kwargs):
        return SimpleNamespace(data=[])

    async def noop_close():
        return None

    # 스크립트는 자체 세션을 열고 닫는다. 테스트 트랜잭션 안에서 돌도록 공용 세션을 넘긴다.
    monkeypatch.setattr(db, "close", lambda: None)
    monkeypatch.setattr(sync_datasets, "SessionLocal", lambda: db)
    monkeypatch.setattr(sync_datasets.dataset_service, "get_datasets", empty_get_datasets)
    monkeypatch.setattr(sync_datasets.dataset_service, "close", noop_close)

    result = asyncio.run(sync_datasets.sync_admin_datasets())

    assert result["soft_deleted_count"] == 0
    db.refresh(kept)
    assert kept.is_active is True
    assert kept.deleted_at is None
