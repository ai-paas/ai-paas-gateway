"""[임시] Kaggle 마켓 연동 공인시험용 우회 경로 — 시험 종료 후 이 파일과 routes/model.py 의 호출부를 함께 제거한다.

MLOps 가 Kaggle 모델 등록을 지원하지 않아, Kaggle provider 로 들어온 모델 생성 요청은
MLOps 를 거치지 않고 hub-connect 서버에 파일을 내려받은 뒤 게이트웨이 DB `models` 행에만 기록한다.

- 행 구분: `metadatas` JSON 의 `temp_kaggle_demo` 키, `surro_model_id` 는 MLOps ID 와 겹치지 않는
  DEMO_ID_BASE 이상 대역. `GET /models`·`/model-catalog` 는 MLOps 목록을 기준으로 DB 를 대조하므로
  이 행들은 별도 처리 없이 빠진다(서빙·워크플로우 모델 선택에 나타나지 않음).
- 파일: hub 의 Kaggle 단건 다운로드는 모델 버전을 압축 해제 없이(untar=False) 받아, 어떤 filename 을
  주든 모델 전체 압축 파일 하나를 download_dir 에 저장한다. 그래서 한 번만 호출하고 실제로 저장된 파일을
  파일 목록으로 기록한다. 생성 요청이 다운로드 완료까지 기다리므로 작은 모델로만 시연해야 한다.
- 파일 다운로드: 기존 계약대로 download-url 이 5분짜리 절대 URL 을 주고 브라우저가 인증 헤더 없이 이동한다.
  게이트웨이는 hub 서버 디스크를 읽을 수 없으므로, 서명 토큰으로 보호한 게이트웨이 경로가 hub 다운로드
  응답(download_dir 없이 호출하면 같은 압축 파일을 파일 응답으로 준다)을 스트림으로 중계한다.
"""
import hashlib
import hmac
import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import quote, urlencode

import httpx
from fastapi import HTTPException, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from app.config import settings
from app.models.model import Model
from app.schemas.model import (
    ModelCreateResponse,
    ModelFileDownloadUrlResponse,
    ModelFileEntry,
    ModelResponse,
)
from app.services.hub_connect_service import hub_connect_service
from app.services.model_service import model_service

logger = logging.getLogger(__name__)

DEMO_KEY = "temp_kaggle_demo"
DEMO_ID_BASE = 900_000_000
KAGGLE_PROVIDER_NAME = "kaggle"
KAGGLE_MARKET = "kaggle"
# hub-connect 컨테이너 기준 경로 (docker-compose 에서 ./data:/app/data 로 마운트됨)
DOWNLOAD_ROOT = os.getenv("TEMP_KAGGLE_DEMO_DOWNLOAD_DIR", "/app/data/kaggle-demo")
# hub 의 KAGGLE_DOWNLOAD_TIMEOUT 기본값(300초)에 맞춤. 게이트웨이 기본 PROXY_TIMEOUT 으로는 부족하다.
DOWNLOAD_TIMEOUT = float(os.getenv("TEMP_KAGGLE_DEMO_DOWNLOAD_TIMEOUT", "330"))
SIGNED_URL_TTL_SECONDS = 300
# 프런트가 게이트웨이를 다른 주소(리버스 프록시 등)로 부르면 요청 Host 로 만든 URL 에 브라우저가 닿지 못한다.
# 그때 브라우저 기준 게이트웨이 주소(예: https://aipaas.example.com)를 지정한다.
PUBLIC_BASE_URL = os.getenv("TEMP_KAGGLE_DEMO_PUBLIC_BASE_URL", "")


def is_demo_id(model_id: int) -> bool:
    return model_id >= DEMO_ID_BASE


def _extract_list(payload: Any) -> List[Dict[str, Any]]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        return payload.get("data", []) or []
    return []


def _find_by_id(items: List[Dict[str, Any]], item_id: int, kind: str) -> Dict[str, Any]:
    for item in items:
        if item.get("id") == item_id:
            return {"id": item["id"], "name": item.get("name", ""), "description": item.get("description")}
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unknown {kind}_id: {item_id}")


async def get_kaggle_provider(provider_id: int, user_info: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """provider_id 가 Kaggle provider 면 그 정보를, 아니면 None. 숫자 ID 는 환경마다 달라 이름으로 판별한다.

    모든 모델 생성 요청이 이 조회를 거치므로, 조회 실패가 Kaggle 이 아닌 기존 생성 경로를 막지 않도록 None 으로 넘긴다.
    """
    try:
        providers = _extract_list(await model_service.get_model_providers(user_info=user_info))
    except Exception as e:
        logger.warning("[temp-kaggle-demo] provider lookup failed, falling back to MLOps path: %r", e)
        return None
    for provider in providers:
        if provider.get("id") == provider_id and str(provider.get("name", "")).lower() == KAGGLE_PROVIDER_NAME:
            return {"id": provider["id"], "name": provider["name"], "description": provider.get("description")}
    return None


def _load_meta(row: Model) -> Optional[Dict[str, Any]]:
    if not row.metadatas:
        return None
    try:
        return json.loads(row.metadatas).get(DEMO_KEY)
    except (ValueError, AttributeError):
        return None


def _next_demo_id(db: Session) -> int:
    current = db.query(func.max(Model.surro_model_id)).filter(Model.surro_model_id >= DEMO_ID_BASE).scalar()
    return (current or DEMO_ID_BASE - 1) + 1


async def _download_files(repo_id: str, target_dir: str, user_info: Dict[str, Any]) -> List[Dict[str, Any]]:
    listing = await hub_connect_service.get_model_files(repo_id, KAGGLE_MARKET, user_info=user_info)
    if not listing.data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"No files in Kaggle model: {repo_id}")

    try:
        response = await hub_connect_service._make_authenticated_request(
            "GET",
            f"{hub_connect_service.base_url}/models/{repo_id}/download",
            user_info=user_info,
            params={"filename": listing.data[0].name, "market": KAGGLE_MARKET, "download_dir": target_dir},
            timeout=DOWNLOAD_TIMEOUT,
        )
    except httpx.TimeoutException:
        raise HTTPException(status_code=status.HTTP_504_GATEWAY_TIMEOUT, detail=f"Kaggle download timeout: {repo_id}")
    except httpx.RequestError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Hub request failed: {e!r}")
    if response.status_code != 200:
        raise HTTPException(
            status_code=response.status_code,
            detail=f"Failed to download Kaggle model {repo_id}: {response.text}",
        )
    result = response.json()
    logger.info("[temp-kaggle-demo] downloaded %s -> %s", repo_id, result.get("file_path"))
    return [{
        "name": result.get("filename") or os.path.basename(result.get("file_path") or ""),
        "size_bytes": int(result.get("file_size") or 0),
        "file_path": result.get("file_path"),
        # 사용자 다운로드 때 hub 에 다시 넘길 filename (hub 는 이 값과 무관하게 같은 압축 파일을 준다)
        "hub_filename": listing.data[0].name,
    }]


def _to_response_dict(row: Model, meta: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": row.surro_model_id,
        "name": row.name,
        "description": row.description,
        "repo_id": meta.get("repo_id"),
        "provider_info": meta.get("provider_info"),
        "type_info": meta.get("type_info"),
        "format_info": meta.get("format_info"),
        "task": meta.get("task"),
        "parameter": meta.get("parameter"),
        "sample_code": meta.get("sample_code"),
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "created_by": row.created_by,
        "learning_enable_yn": False,
        "opt_enable_yn": False,
        "visibility": "CUSTOM",
    }


async def create_demo_model(
        db: Session,
        *,
        provider_info: Dict[str, Any],
        name: str,
        repo_id: Optional[str],
        description: Optional[str],
        type_id: int,
        format_id: int,
        task: Optional[str],
        parameter: Optional[str],
        sample_code: Optional[str],
        member_id: str,
        user_info: Dict[str, Any],
) -> ModelCreateResponse:
    if not repo_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="repo_id is required for Kaggle models")

    type_info = _find_by_id(_extract_list(await model_service.get_model_types(user_info=user_info)), type_id, "type")
    format_info = _find_by_id(
        _extract_list(await model_service.get_model_formats(user_info=user_info)), format_id, "format"
    )

    demo_id = _next_demo_id(db)
    target_dir = f"{DOWNLOAD_ROOT.rstrip('/')}/{demo_id}"
    files = await _download_files(repo_id, target_dir, user_info)

    meta = {
        "repo_id": repo_id,
        "provider_info": provider_info,
        "type_info": type_info,
        "format_info": format_info,
        "task": task,
        "parameter": parameter,
        "sample_code": sample_code,
        "download_dir": target_dir,
        "downloaded_at": datetime.now(timezone.utc).isoformat(),
        "files": files,
    }
    row = Model(
        surro_model_id=demo_id,
        name=name,
        description=description,
        is_catalog=False,
        created_by=member_id,
        updated_by=member_id,
        metadatas=json.dumps({DEMO_KEY: meta}, ensure_ascii=False),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    logger.info("[temp-kaggle-demo] created model id=%s repo_id=%s files=%d", demo_id, repo_id, len(files))
    return ModelCreateResponse(**_to_response_dict(row, meta))


def list_demo_models(db: Session, member_id: str) -> List[ModelResponse]:
    rows = db.query(Model).filter(
        Model.created_by == member_id,
        Model.surro_model_id >= DEMO_ID_BASE,
        Model.deleted_at.is_(None),
        Model.is_active == True,
    ).order_by(Model.created_at.desc()).all()
    result = []
    for row in rows:
        meta = _load_meta(row)
        if meta is not None:
            result.append(ModelResponse(**_to_response_dict(row, meta)))
    return result


def _get_owned_row(db: Session, model_id: int, member_id: str):
    row = db.query(Model).filter(
        Model.surro_model_id == model_id,
        Model.created_by == member_id,
        Model.deleted_at.is_(None),
        Model.is_active == True,
    ).first()
    meta = _load_meta(row) if row else None
    if meta is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Model {model_id} not found or access denied",
        )
    return row, meta


def get_demo_model(db: Session, model_id: int, member_id: str) -> ModelResponse:
    row, meta = _get_owned_row(db, model_id, member_id)
    return ModelResponse(**_to_response_dict(row, meta))


def get_demo_model_files(db: Session, model_id: int, member_id: str) -> List[ModelFileEntry]:
    _, meta = _get_owned_row(db, model_id, member_id)
    downloaded_at = datetime.fromisoformat(meta["downloaded_at"])
    return [
        ModelFileEntry(
            name=f["name"],
            size_bytes=f["size_bytes"],
            last_modified=downloaded_at,
            download_url=f"{settings.API_V1_STR}/models/{model_id}/files/download-url?{urlencode({'name': f['name']})}",
        )
        for f in meta.get("files", [])
    ]


def _sign(model_id: int, expires: int) -> str:
    message = f"{DEMO_KEY}:{model_id}:{expires}".encode()
    return hmac.new(settings.JWT_SECRET_KEY.encode(), message, hashlib.sha256).hexdigest()


def _public_base_url(request: Request) -> str:
    if PUBLIC_BASE_URL:
        return PUBLIC_BASE_URL.rstrip("/")
    proto = request.headers.get("x-forwarded-proto") or request.url.scheme
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc
    return f"{proto.split(',')[0].strip()}://{host.split(',')[0].strip()}"


def issue_download_url(
        db: Session, model_id: int, name: str, member_id: str, request: Request,
) -> ModelFileDownloadUrlResponse:
    _, meta = _get_owned_row(db, model_id, member_id)
    file = next((f for f in meta.get("files", []) if f["name"] == name), None)
    if file is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"File not found: {name}")

    expires = int(time.time()) + SIGNED_URL_TTL_SECONDS
    query = urlencode({"expires": expires, "sig": _sign(model_id, expires)})
    return ModelFileDownloadUrlResponse(
        model_id=model_id,
        name=name,
        size_bytes=file["size_bytes"],
        download_url=(
            f"{_public_base_url(request)}{settings.API_V1_STR}"
            f"/models/{model_id}/files/temp-kaggle-download?{query}"
        ),
        expires_at=datetime.fromtimestamp(expires, timezone.utc),
    )


async def stream_download(db: Session, model_id: int, expires: int, sig: str) -> StreamingResponse:
    """서명이 맞으면 hub 다운로드 응답을 그대로 흘려보낸다. 인증 헤더 없는 브라우저 이동용이라 서명이 유일한 보호다."""
    if expires < time.time() or not hmac.compare_digest(sig, _sign(model_id, expires)):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid or expired download link")

    row = db.query(Model).filter(
        Model.surro_model_id == model_id,
        Model.deleted_at.is_(None),
        Model.is_active == True,
    ).first()
    meta = _load_meta(row) if row else None
    if not meta or not meta.get("files"):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Model {model_id} not found")
    file = meta["files"][0]

    token = await hub_connect_service._get_valid_token()
    hub_request = hub_connect_service.client.build_request(
        "GET",
        f"{hub_connect_service.base_url}/models/{meta['repo_id']}/download",
        params={"filename": file.get("hub_filename") or file["name"], "market": KAGGLE_MARKET},
        headers={"Authorization": f"Bearer {token}"},
        timeout=DOWNLOAD_TIMEOUT,
    )
    try:
        hub_response = await hub_connect_service.client.send(hub_request, stream=True)
    except httpx.TimeoutException:
        raise HTTPException(status_code=status.HTTP_504_GATEWAY_TIMEOUT, detail="Kaggle download timeout")
    except httpx.RequestError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Hub request failed: {e!r}")
    if hub_response.status_code != 200:
        body = await hub_response.aread()
        await hub_response.aclose()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Hub download failed ({hub_response.status_code}): {body[:500].decode(errors='replace')}",
        )

    headers = {"Content-Disposition": f"attachment; filename*=UTF-8''{quote(file['name'])}"}
    if "content-length" in hub_response.headers:
        headers["Content-Length"] = hub_response.headers["content-length"]
    logger.info("[temp-kaggle-demo] streaming download model_id=%s file=%s", model_id, file["name"])
    return StreamingResponse(
        hub_response.aiter_bytes(),
        media_type="application/octet-stream",
        headers=headers,
        background=BackgroundTask(hub_response.aclose),
    )


def delete_demo_model(db: Session, model_id: int, member_id: str) -> None:
    """DB 행만 soft-delete 한다. hub 서버의 내려받은 파일은 시험 후 원상복구 때 디렉터리째 정리한다."""
    row, _ = _get_owned_row(db, model_id, member_id)
    now = datetime.utcnow()
    row.deleted_at = now
    row.deleted_by = member_id
    row.is_active = False
    row.updated_by = member_id
    row.updated_at = now
    db.commit()
