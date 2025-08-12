from fastapi import APIRouter, Request, Response, Depends, HTTPException, status
from fastapi.responses import StreamingResponse, JSONResponse
import json
import httpx
from typing import Optional
from app.config import settings
from app.auth import get_current_user
import logging

# 로거 설정
logger = logging.getLogger(__name__)

router = APIRouter(tags=["Proxy"])


class ProxyService:
    def __init__(self):
        if settings.PROXY_ENABLED:
            self.client = httpx.AsyncClient(
                timeout=httpx.Timeout(
                    timeout=settings.PROXY_TIMEOUT,
                    connect=settings.PROXY_CONNECT_TIMEOUT
                ),
                limits=httpx.Limits(
                    max_keepalive_connections=settings.PROXY_MAX_KEEPALIVE_CONNECTIONS,
                    max_connections=settings.PROXY_MAX_CONNECTIONS
                ),
                follow_redirects=True,
                headers={
                    'Accept': 'application/json, text/plain, */*',
                    'Accept-Charset': 'utf-8',
                    'User-Agent': 'AIPaaS-Gateway/1.0'
                }
            )
        else:
            self.client = None

    async def close(self):
        if self.client:
            await self.client.aclose()

    async def forward_request(
            self,
            request: Request,
            path: str,
            current_user: dict = None
    ):
        """요청을 타겟 서버로 전달"""

        if not settings.PROXY_ENABLED:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Proxy service is disabled"
            )

        if not self.client:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Proxy client not initialized"
            )

        # 요청 헤더 복사 (Authorization 헤더 제외)
        headers = dict(request.headers)

        # 불필요한 헤더 제거
        headers_to_remove = ['authorization', 'host', 'content-length']
        for header in headers_to_remove:
            headers.pop(header, None)

        # 사용자 정보를 헤더에 추가 (ASCII 안전하게)
        if current_user:
            try:
                headers['X-User-ID'] = str(current_user.member_id).encode('ascii', errors='ignore').decode('ascii')
                headers['X-User-Role'] = str(current_user.role).encode('ascii', errors='ignore').decode('ascii')

                # 이름에 한글이 있을 수 있으므로 Base64 인코딩하거나 제외
                if hasattr(current_user, 'name') and current_user.name:
                    import base64
                    name_b64 = base64.b64encode(str(current_user.name).encode('utf-8')).decode('ascii')
                    headers['X-User-Name-B64'] = name_b64

                if current_user.email:
                    headers['X-User-Email'] = str(current_user.email).encode('ascii', errors='ignore').decode('ascii')
            except Exception as ue:
                logger.warning(f"User header encoding error: {ue}")

        # 요청 본문 읽기
        body = None
        if request.method in ['POST', 'PUT', 'PATCH']:
            body = await request.body()

        # 타겟 URL 구성
        target_path = f"{settings.PROXY_TARGET_PATH_PREFIX}/{path}" if path else settings.PROXY_TARGET_PATH_PREFIX
        target_url = f"{settings.PROXY_TARGET_BASE_URL}{target_path}"

        if request.url.query:
            target_url += f"?{request.url.query}"

        logger.info(f"Proxying {request.method} request to: {target_url}")

        # 디버깅: 헤더 내용 확인
        logger.info(f"Request headers: {dict(request.headers)}")
        logger.info(f"User info: member_id={getattr(current_user, 'member_id', 'None')}")

        try:
            # 헤더 인코딩 문제 해결
            safe_headers = {}
            for key, value in headers.items():
                try:
                    # 헤더 값을 안전하게 ASCII로 변환
                    safe_key = str(key).encode('ascii', errors='ignore').decode('ascii')
                    safe_value = str(value).encode('ascii', errors='ignore').decode('ascii')
                    safe_headers[safe_key] = safe_value
                except Exception as he:
                    logger.warning(f"Header encoding issue {key}={value}: {he}")

            logger.info(f"Safe headers prepared: {len(safe_headers)} headers")

            # 타겟 서버로 요청 전달
            response = await self.client.request(
                method=request.method,
                url=target_url,
                headers=safe_headers,  # safe_headers 사용
                content=body
            )

            logger.info(f"Proxy response status: {response.status_code}")
            logger.info(f"Response content type: {response.headers.get('content-type', 'unknown')}")
            logger.info(f"Response content length: {len(response.content)}")

            # 응답 헤더 필터링
            response_headers = {}
            skip_headers = [
                'server', 'date', 'content-encoding', 'transfer-encoding',
                'connection', 'content-length'
            ]

            for name, value in response.headers.items():
                if name.lower() not in skip_headers:
                    try:
                        # 헤더 값이 ASCII가 아닌 경우 처리
                        response_headers[name] = str(value)
                    except UnicodeEncodeError as e:
                        logger.warning(f"Header encoding issue for {name}: {e}")
                        response_headers[name] = value.encode('utf-8', errors='ignore').decode('ascii', errors='ignore')

            try:
                # JSON 응답인 경우 파싱해서 다시 반환
                if 'application/json' in response.headers.get('content-type', ''):
                    json_data = response.json()
                    return JSONResponse(
                        content=json_data,
                        status_code=response.status_code,
                        headers=response_headers
                    )
                else:
                    # JSON이 아닌 경우 바이너리로 처리
                    return Response(
                        content=response.content,
                        status_code=response.status_code,
                        headers=response_headers,
                        media_type=response.headers.get('content-type', 'application/octet-stream')
                    )
            except Exception as parse_error:
                logger.error(f"Response parsing error: {parse_error}")
                # 파싱 실패시 원본 그대로 반환
                return Response(
                    content=response.content,
                    status_code=response.status_code,
                    headers=response_headers
                )

        except httpx.TimeoutException as e:
            logger.error(f"Proxy timeout error: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="Target server timeout"
            )
        except httpx.ConnectError as e:
            logger.error(f"Proxy connection error: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Cannot connect to target server"
            )
        except Exception as e:
            logger.error(f"Proxy error: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Proxy error: {str(e)}"
            )


# 전역 ProxyService 인스턴스
proxy_service = ProxyService()

# 프록시 상태 확인
@router.get("/proxy/status")
async def proxy_status():
    """프록시 서비스 상태 확인"""
    return {
        "enabled": settings.PROXY_ENABLED,
        "target_url": settings.PROXY_TARGET_BASE_URL if settings.PROXY_ENABLED else None,
        "target_path_prefix": settings.PROXY_TARGET_PATH_PREFIX if settings.PROXY_ENABLED else None,
        "timeout": settings.PROXY_TIMEOUT if settings.PROXY_ENABLED else None
    }


# GET 요청 프록시
@router.get("/proxy/{path:path}")
async def proxy_all_paths(
        path: str,
        request: Request,
        current_user=Depends(get_current_user)
):
    """모든 경로 프록시"""
    return await proxy_service.forward_request(request, path, current_user)

# POST 요청 프록시
@router.post("/proxy/{path:path}")
async def proxy_post(
        path: str,
        request: Request,
        current_user=Depends(get_current_user)
):
    """POST 요청 프록시"""
    return await proxy_service.forward_request(request, path, current_user)


# PUT 요청 프록시
@router.put("/proxy/{path:path}")
async def proxy_put(
        path: str,
        request: Request,
        current_user=Depends(get_current_user)
):
    """PUT 요청 프록시"""
    return await proxy_service.forward_request(request, path, current_user)


# PATCH 요청 프록시
@router.patch("/proxy/{path:path}")
async def proxy_patch(
        path: str,
        request: Request,
        current_user=Depends(get_current_user)
):
    """PATCH 요청 프록시"""
    return await proxy_service.forward_request(request, path, current_user)


# DELETE 요청 프록시
@router.delete("/proxy/{path:path}")
async def proxy_delete(
        path: str,
        request: Request,
        current_user=Depends(get_current_user)
):
    """DELETE 요청 프록시"""
    return await proxy_service.forward_request(request, path, current_user)


# 애플리케이션 종료시 클린업 함수
async def cleanup_proxy():
    """프록시 서비스 정리"""
    await proxy_service.close()
    logger.info("Proxy service cleaned up")