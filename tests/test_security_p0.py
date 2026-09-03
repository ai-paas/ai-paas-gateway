import asyncio
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, HTTPException, status
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.auth import get_current_admin_user, get_current_user
from app.routes import any_cloud, hub_connect
from app.routes.member import update_member
from app.schemas.any_cloud import AnyCloudPagedResponse
from app.schemas.member import MemberUpdate


def test_member_self_update_cannot_promote_to_admin(db, sample_member):
    with pytest.raises(HTTPException) as exc_info:
        update_member(
            member_id=sample_member.member_id,
            member_update=MemberUpdate(role="admin"),
            db=db,
            current_user=sample_member,
        )

    assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
    db.refresh(sample_member)
    assert sample_member.role == "user"


def test_member_self_update_cannot_change_admin_only_fields(db, sample_member):
    for payload in (
        {"member_id": "other-user"},
        {"is_active": False},
    ):
        with pytest.raises(HTTPException) as exc_info:
            update_member(
                member_id=sample_member.member_id,
                member_update=MemberUpdate(**payload),
                db=db,
                current_user=sample_member,
            )

        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN

    db.refresh(sample_member)
    assert sample_member.member_id == "testuser"
    assert sample_member.is_active is True


def test_member_admin_can_update_role(db, sample_member, admin_member):
    updated = update_member(
        member_id=sample_member.member_id,
        member_update=MemberUpdate(role="admin"),
        db=db,
        current_user=admin_member,
    )

    assert updated.role == "admin"


def test_member_update_password_uses_create_strength_validator():
    with pytest.raises(ValidationError):
        MemberUpdate(password="weak")


def _any_cloud_client(user) -> TestClient:
    app = FastAPI()
    app.include_router(any_cloud.router_cluster)
    app.include_router(any_cloud.router_package)

    def override_admin_user():
        if user.role != "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admin access required",
            )
        return user

    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_current_admin_user] = override_admin_user
    return TestClient(app)


def _cluster_payload() -> dict:
    # Any Cloud v0.3.0: source discriminator + spec 구조
    return {
        "source": "registered",
        "clusterName": "cluster-001",
        "spec": {
            "provider": "AWS",
            "clusterType": "EKS",
            "description": "test",
        },
    }


def test_any_cloud_cluster_create_requires_admin(sample_member, monkeypatch):
    create_cluster = AsyncMock(return_value={"data": {"id": "cluster-001"}})
    monkeypatch.setattr(any_cloud.any_cloud_service, "create_cluster", create_cluster)

    response = _any_cloud_client(sample_member).post(
        "/any-cloud/system/cluster",
        json=_cluster_payload(),
    )

    assert response.status_code == status.HTTP_403_FORBIDDEN
    create_cluster.assert_not_called()


def test_any_cloud_cluster_create_admin_still_uses_same_body(admin_member, monkeypatch):
    create_cluster = AsyncMock(return_value={"data": {"id": "cluster-001"}})
    monkeypatch.setattr(any_cloud.any_cloud_service, "create_cluster", create_cluster)

    response = _any_cloud_client(admin_member).post(
        "/any-cloud/system/cluster",
        json=_cluster_payload(),
    )

    assert response.status_code == status.HTTP_200_OK
    create_cluster.assert_awaited_once()
    assert create_cluster.await_args.kwargs["data"]["clusterName"] == "cluster-001"


def test_any_cloud_kubernetes_resource_type_blocks_secrets(sample_member, monkeypatch):
    get_resource = AsyncMock()
    monkeypatch.setattr(any_cloud.any_cloud_service, "get_kubernetes_resource", get_resource)

    response = _any_cloud_client(sample_member).get(
        "/any-cloud/kubernetes/secrets",
        params={"clusterName": "cluster-001"},
    )

    assert response.status_code == status.HTTP_403_FORBIDDEN
    get_resource.assert_not_called()


@pytest.mark.parametrize(
    "resource_type",
    ["roles", "roleBindings", "clusterRoles", "clusterRoleBindings"],
)
def test_any_cloud_kubernetes_resource_type_blocks_rbac_resources(
    sample_member,
    monkeypatch,
    resource_type,
):
    get_resource = AsyncMock()
    monkeypatch.setattr(any_cloud.any_cloud_service, "get_kubernetes_resource", get_resource)

    response = _any_cloud_client(sample_member).get(
        f"/any-cloud/kubernetes/{resource_type}",
        params={"clusterName": "cluster-001"},
    )

    assert response.status_code == status.HTTP_403_FORBIDDEN
    get_resource.assert_not_called()


def test_any_cloud_kubernetes_resource_type_allows_pods(sample_member, monkeypatch):
    get_resource = AsyncMock(
        return_value=AnyCloudPagedResponse.create(data=[], total=0, page=1, size=20)
    )
    monkeypatch.setattr(any_cloud.any_cloud_service, "get_kubernetes_resource", get_resource)

    response = _any_cloud_client(sample_member).get(
        "/any-cloud/kubernetes/pods",
        params={"clusterName": "cluster-001"},
    )

    assert response.status_code == status.HTTP_200_OK
    get_resource.assert_awaited_once()


def test_any_cloud_kubernetes_test_connection_uses_static_route(sample_member, monkeypatch):
    get_kubernetes_test = AsyncMock(return_value={"ok": True})
    get_resource = AsyncMock()
    monkeypatch.setattr(any_cloud.any_cloud_service, "get_kubernetes_test", get_kubernetes_test)
    monkeypatch.setattr(any_cloud.any_cloud_service, "get_kubernetes_resource", get_resource)

    response = _any_cloud_client(sample_member).get(
        "/any-cloud/kubernetes/test-connection",
        params={"clusterName": "cluster-001"},
    )

    assert response.status_code == status.HTTP_200_OK
    get_kubernetes_test.assert_awaited_once()
    get_resource.assert_not_called()


def test_any_cloud_kubernetes_delete_requires_admin(sample_member, monkeypatch):
    delete_resource = AsyncMock(return_value={"deleted": True})
    monkeypatch.setattr(any_cloud.any_cloud_service, "delete_kubernetes_resource", delete_resource)

    response = _any_cloud_client(sample_member).delete(
        "/any-cloud/kubernetes/pods/pod-001",
        params={"clusterName": "cluster-001"},
    )

    assert response.status_code == status.HTTP_403_FORBIDDEN
    delete_resource.assert_not_called()


def test_any_cloud_kubernetes_delete_admin_calls_delete_service(admin_member, monkeypatch):
    delete_resource = AsyncMock(return_value={"deleted": True})
    monkeypatch.setattr(any_cloud.any_cloud_service, "delete_kubernetes_resource", delete_resource)

    response = _any_cloud_client(admin_member).delete(
        "/any-cloud/kubernetes/pods/pod-001",
        params={"clusterName": "cluster-001"},
    )

    assert response.status_code == status.HTTP_200_OK
    delete_resource.assert_awaited_once()


def test_hub_model_download_rejects_absolute_download_dir(sample_member):
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            hub_connect.download_hub_model_file(
                model_id="owner/repo",
                filename="config.json",
                market="huggingface",
                download_dir="C:/Windows",
                current_user=sample_member,
            )
        )

    assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST


def test_hub_model_download_rejects_windows_backslash_download_dir(sample_member):
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            hub_connect.download_hub_model_file(
                model_id="owner/repo",
                filename="config.json",
                market="huggingface",
                download_dir=r"safe\..\outside",
                current_user=sample_member,
            )
        )

    assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST


def test_hub_dataset_file_rejects_traversal_repo_id(sample_member):
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            hub_connect.download_hub_dataset_file(
                repo_id="../repo",
                filename="data/train.csv",
                market="huggingface",
                current_user=sample_member,
            )
        )

    assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST


def test_hub_dataset_file_rejects_traversal_filename(sample_member):
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            hub_connect.download_hub_dataset_file(
                repo_id="owner/repo",
                filename="../secret.txt",
                market="huggingface",
                current_user=sample_member,
            )
        )

    assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST


def test_hub_dataset_snapshot_rejects_traversal_download_dir(sample_member):
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            hub_connect.download_hub_dataset_snapshot(
                repo_id="owner/repo",
                market="huggingface",
                download_dir="../outside",
                current_user=sample_member,
            )
        )

    assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST


def test_hub_model_download_allows_safe_relative_download_dir(sample_member, monkeypatch):
    download_model_file = AsyncMock(
        return_value={
            "download_type": "server_path",
            "file_path": "safe/models/config.json",
            "file_size": 12,
            "filename": "config.json",
            "model_id": "owner/repo",
        }
    )
    monkeypatch.setattr(hub_connect.hub_connect_service, "download_model_file", download_model_file)

    result = asyncio.run(
        hub_connect.download_hub_model_file(
            model_id="owner/repo",
            filename="config.json",
            market="huggingface",
            download_dir="safe/models",
            current_user=sample_member,
        )
    )

    assert result.download_type == "server_path"
    download_model_file.assert_awaited_once()
    assert download_model_file.await_args.args[3] == "safe/models"
