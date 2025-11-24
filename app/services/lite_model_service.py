from http.client import responses

import httpx
import logging
import asyncio
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List
from fastapi import HTTPException, status
from app.config import settings

logger = logging.getLogger(__name__)


class LiteModelService:
    """최적화 모델 연결 서비스"""

    def __init__(self):
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(
                timeout=settings.LITE_MODEL_TIMEOUT,
                connect=settings.LITE_MODEL_CONNECT_TIMEOUT
            ),
            limits=httpx.Limits(
                max_keepalive_connections=settings.LITE_MODEL_MAX_KEEPALIVE_CONNECTIONS,
                max_connections=settings.LITE_MODEL_MAX_CONNECTIONS
            ),
            follow_redirects=True
        )
        # 외부 Lite Model API URL
        self.base_url = settings.LITE_MODEL_TARGET_BASE_URL

    async def close(self):
        """HTTP 클라이언트 종료"""
        await self.client.aclose()

    def _get_headers(self, user_info: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        """요청 헤더 생성"""
        headers = {
            'Accept': 'application/json',
            'Content-Type': 'application/json',
            'User-Agent': 'AIPaaS-AnyCloud-Gateway/1.0'
        }

        # 사용자 정보 추가
        if user_info:
            if user_info.get('member_id'):
                headers['X-User-ID'] = str(user_info['member_id'])
            if user_info.get('role'):
                headers['X-User-Role'] = str(user_info['role'])
            if user_info.get('name'):
                import base64
                name_b64 = base64.b64encode(str(user_info['name']).encode('utf-8')).decode('ascii')
                headers['X-User-Name-B64'] = name_b64

        return headers

    async def _make_request(
            self,
            method: str,
            path: str,
            user_info: Optional[Dict[str, str]] = None,
            **kwargs
    ) -> Dict[str, Any]:
        """Lite Model API 요청 실행 및 응답을 data로 래핑"""
        try:
            url = f"{self.base_url}{path}"

            # 헤더 설정
            headers = self._get_headers(user_info)

            # 기존 헤더와 병합
            if 'headers' in kwargs:
                kwargs['headers'].update(headers)
            else:
                kwargs['headers'] = headers

            logger.info(f"Making {method} request to Lite Model: {url}")
            if kwargs.get('params'):
                logger.info(f"Parameters: {kwargs['params']}")

            # 요청 실행
            response = await getattr(self.client, method.lower())(url, **kwargs)

            if response.status_code == 200:
                response_data = response.json()
                # 응답을 data로 래핑
                return {"data": response_data}
            else:
                logger.error(f"Lite Model API error: {response.status_code} - {response.text}")
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"ALite Model API request failed: {response.text}"
                )

        except httpx.TimeoutException as e:
            logger.error(f"Timeout calling Lite Model API {path}: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="Lite Model service timeout"
            )
        except httpx.ConnectError as e:
            logger.error(f"Connection error calling Lite Model API {path}: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Lite Model service unavailable"
            )
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error calling Lite Model API {path}: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Internal error: {str(e)}"
            )

    async def generic_get_unwrapped(
            self,
            path: str,
            user_info: Optional[Dict[str, str]] = None,
            **query_params
    ) -> Any:
        """범용 GET 요청 (data 래핑 제거) - 단일 조회용"""
        response = await self._make_request(
            "GET", path, user_info=user_info, params=query_params
        )

        # data 필드가 있으면 data 내용만 반환, 없으면 전체 응답 반환
        if isinstance(response, dict) and "data" in response:
            return response["data"]
        return response

    async def generic_get(
            self,
            path: str,
            user_info: Optional[Dict[str, str]] = None,
            **query_params
    ) -> Dict[str, Any]:
        """범용 GET 요청 (동적 엔드포인트 지원) - 전체 조회용"""
        filtered_params = {
            k: v for k, v in query_params.items()
            if v is not None and v != ""
        }

        return await self._make_request(
            "GET", path, user_info=user_info, params=filtered_params
        )

    async def generic_post(
            self,
            path: str,
            data: Dict[str, Any],
            user_info: Optional[Dict[str, str]] = None,
            **query_params
    ) -> Dict[str, Any]:
        """범용 POST 요청 (동적 엔드포인트 지원) - data 래핑 없이 그대로 반환"""
        response = await self._make_request(
            "POST", path, user_info=user_info, json=data, params=query_params
        )
        # data 필드가 있으면 data 내용만 반환, 없으면 전체 응답 반환
        if isinstance(response, dict) and "data" in response:
            return response["data"]
        return response

    async def simple_post(
            self,
            path: str,
            user_info: Optional[Dict[str, str]] = None,
            **query_params
    ) -> Dict[str, Any]:
        """데이터 없는 단순 POST 요청 (트리거/액션용)"""
        response = await self._make_request(
            "POST", path, user_info=user_info, params=query_params
        )
        # data 필드가 있으면 data 내용만 반환, 없으면 전체 응답 반환
        if isinstance(response, dict) and "data" in response:
            return response["data"]
        return response

    async def generic_patch(
            self,
            path: str,
            data: Dict[str, Any],
            user_info: Optional[Dict[str, str]] = None,
            **query_params
    ) -> Dict[str, Any]:
        """범용 PATCH 요청 (동적 엔드포인트 지원)"""
        response = await self._make_request(
            "PATCH", path, user_info=user_info, json=data, params=query_params
        )
        # data 필드가 있으면 data 내용만 반환, 없으면 전체 응답 반환
        if isinstance(response, dict) and "data" in response:
            return response["data"]
        return response

    async def get_models(self, user_info: dict, page_num: int, page_size: int, name: str, optimizer_id: int) -> dict:
        """
        모델 목록 조회 전용 메소드
        """
        return await self.generic_get(
            path="/checked/model",  # 고정된 경로
            user_info=user_info,
            page_num=page_num,
            page_size=page_size,
            name=name,
            optimizer_id=optimizer_id
        )

    async def get_model(self, user_info: dict, model_id: int) -> dict:
        """
        모델 상세 조회 전용 메소드
        """
        return await self.generic_get(
            path=f"/checked/model/{model_id}",  # 고정된 경로
            user_info=user_info,
            model_id=model_id
        )

    async def get_optimizers(self, user_info: dict, page_num: int, page_size: int, name: str, model_id: int) -> dict:
        """
        Optimizer 목록 조회 전용 메소드
        """
        return await self.generic_get(
            path="/checked/optimizer",  # 고정된 경로
            user_info=user_info,
            page_num=page_num,
            page_size=page_size,
            name=name,
            model_id=model_id
        )

    async def get_optimizer(self, user_info: dict, optimizer_id: int) -> dict:
        """
        Optimizer 상세 조회 전용 메소드
        """
        return await self.generic_get(
            path=f"/checked/optimizer/{optimizer_id}",  # 고정된 경로
            user_info=user_info,
            optimizer_id=optimizer_id
        )

    async def execute_optimize(self, user_info: dict, optimizer_id: int, optimize_data: dict) -> dict:
        return await self.generic_post(
            path=f"/optimize/optimize/{optimizer_id}",
            data=optimize_data,
            user_info=user_info
        )

    async def get_tasks(self, user_info: dict, page_num: int, page_size: int, model_name_query: str, optimizer_name_query: str, task_status: str) -> dict:
        """
        task 목록 조회 전용 메소드
        """
        return await self.generic_get(
            path="/tasks",  # 고정된 경로
            user_info=user_info,
            page_num=page_num,
            page_size=page_size,
            model_name_query=model_name_query,
            optimizer_name_query=optimizer_name_query,
            task_status=task_status
        )

    async def get_task(self, user_info: dict, task_id: str) -> dict:
        """
        task 상세 조회 전용 메소드
        """
        return await self.generic_get(
            path=f"/tasks/{task_id}",  # 고정된 경로
            user_info=user_info,
            task_id=task_id
        )

    async def patch_task(self, user_info: dict, task_id: str, task_data: dict) -> dict:
        """
        task 상태 업데이트 메서드
        """
        return await self.generic_patch(
            path=f"/tasks/{task_id}",
            data=task_data,
            user_info=user_info
        )

    async def model_tensorrt(self, user_info: dict, optimize_data: dict) -> dict:
        return await self.generic_post(
            path="/models/bert/optimizers/tensorrt",
            data=optimize_data,
            user_info=user_info
        )

    async def model_openvino(self, user_info: dict, optimize_data: dict) -> dict:
        return await self.generic_post(
            path="/models/bert/optimizers/openvino",
            data=optimize_data,
            user_info=user_info
        )

    async def model_owlv2(self, user_info: dict, optimize_data: dict) -> dict:
        return await self.generic_post(
            path="/models/owlv2/optimizers/ptq",
            data=optimize_data,
            user_info=user_info
        )

    async def model_detr(self, user_info: dict, optimize_data: dict) -> dict:
        return await self.generic_post(
            path="/models/detr-resnet50/optimizers/ptq",
            data=optimize_data,
            user_info=user_info
        )
# 싱글톤 인스턴스
lite_model_service = LiteModelService()