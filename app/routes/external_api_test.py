from fastapi import APIRouter, Depends, HTTPException, status, Query, Path
from typing import List, Optional, Dict, Any
import logging

from app.auth import get_current_user
from app.services.external_api_service import external_api_service
from app.models import Member

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/surro", tags=["Surros"])

# 테스트용 엔드포인트들
@router.get("/connection")
async def test_external_connection(
        current_user: Member = Depends(get_current_user)
):
    """외부 서비스 연결 테스트"""
    try:
        result = await external_api_service.debug_connection()
        return result
    except Exception as e:
        logger.error(f"Connection test failed: {str(e)}")
        return {
            "status": "error",
            "error": str(e),
            "connection_success": False
        }


@router.post("/endpoint")
async def test_external_endpoint(
        path: Optional[str] = Query(None, description="테스트할 추가 경로 (예: workflows, models, prompt ..."),
        parameters: Optional[Dict[str, Any]] = None,
        current_user: Member = Depends(get_current_user)
):
    """외부 API 엔드포인트 테스트"""
    try:
        user_info = {
            'member_id': current_user.member_id,
            'name': current_user.name,
            'role': current_user.role,
            'email': current_user.email
        }

        result = await external_api_service.test_api_endpoint(
            path=path,
            parameters=parameters,
            user_info=user_info
        )

        return result

    except Exception as e:
        logger.error(f"Endpoint test failed: {str(e)}")
        return {
            "status": "error",
            "error": str(e),
            "success": False
        }


@router.get("/settings")
async def get_proxy_settings(
        current_user: Member = Depends(get_current_user)
):
    """현재 프록시 설정 확인 (관리자만)"""
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )

    from app.config import settings

    return {
        "PROXY_ENABLED": getattr(settings, 'PROXY_ENABLED', False),
        "PROXY_TARGET_BASE_URL": getattr(settings, 'PROXY_TARGET_BASE_URL', 'Not set'),
        "PROXY_TARGET_PATH_PREFIX": getattr(settings, 'PROXY_TARGET_PATH_PREFIX', 'Not set'),
        "PROXY_TIMEOUT": getattr(settings, 'PROXY_TIMEOUT', 'Not set'),
        "PROXY_CONNECT_TIMEOUT": getattr(settings, 'PROXY_CONNECT_TIMEOUT', 'Not set'),
    }