import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional

import httpx
from fastapi import HTTPException, status

from app.config import settings
from app.schemas.hub_connect import (
    HubModelResponse, ModelListParams, ModelListResponse,
    ModelFileInfo, ModelFilesResponse, ExtendedHubModelResponse,
    TagListParams, TagListResponse, TagGroupResponse, TagGroupAllResponse, TagItem,
    DatasetListParams, DatasetListResponse, HubDatasetItem,
    DatasetInfoResponse, DatasetFileInfo, DatasetFilesResponse,
)

logger = logging.getLogger(__name__)


class HubConnectService:
    """허브 연결 서비스 - 외부 모델 허브 API 라우팅 게이트웨이"""

    def __init__(self):
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(
                timeout=settings.PROXY_TIMEOUT,
                connect=settings.PROXY_CONNECT_TIMEOUT
            ),
            limits=httpx.Limits(
                max_keepalive_connections=settings.PROXY_MAX_KEEPALIVE_CONNECTIONS,
                max_connections=settings.PROXY_MAX_CONNECTIONS
            ),
            follow_redirects=True
        )
        # 외부 허브 API URL
        self.base_url = f"{settings.HUB_CONNECT_TARGET_BASE_URL}{settings.HUB_CONNECT_TARGET_PATH_PREFIX}"

        # 인증 관련 설정
        self.auth_username = settings.HUB_CONNECT_API_USERNAME
        self.auth_password = settings.HUB_CONNECT_API_PASSWORD
        self.access_token = None
        self.token_expires_at = None
        self._auth_lock = asyncio.Lock()

    async def close(self):
        """HTTP 클라이언트 종료"""
        await self.client.aclose()

    async def _authenticate(self) -> str:
        """외부 허브 API 인증 토큰 획득"""
        try:
            auth_url = f"{self.base_url}/auth/login"

            # OAuth2 password flow용 form data
            auth_data = {
                "grant_type": "password",
                "username": self.auth_username,
                "password": self.auth_password,
                "scope": "",
                "client_id": "string",
                "client_secret": "string"
            }

            headers = {
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json"
            }

            logger.info(f"Authenticating with hub API at: {auth_url}")

            response = await self.client.post(
                auth_url,
                data=auth_data,
                headers=headers
            )

            if response.status_code == 200:
                token_data = response.json()
                access_token = token_data.get("access_token")
                expires_in = token_data.get("expires_in", 3600)  # 기본 1시간

                if access_token:
                    # 토큰 만료 시간 설정 (여유 시간 5분 차감)
                    self.token_expires_at = datetime.now() + timedelta(seconds=expires_in - 300)
                    logger.info("Successfully authenticated with hub API")
                    return access_token
                else:
                    raise ValueError("No access_token in response")
            else:
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"Hub authentication failed: {response.text}"
                )

        except httpx.TimeoutException as e:
            logger.error(f"Timeout during hub authentication: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="Hub authentication service timeout"
            )
        except Exception as e:
            logger.error(f"Hub authentication error: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Hub authentication failed: {str(e)}"
            )

    async def _get_valid_token(self) -> str:
        """유효한 인증 토큰 반환 (필요시 갱신)"""
        async with self._auth_lock:
            # 토큰이 없거나 만료된 경우 새로 발급
            if (not self.access_token or
                    not self.token_expires_at or
                    datetime.now() >= self.token_expires_at):
                logger.info("Hub token expired or missing, refreshing...")
                self.access_token = await self._authenticate()

            return self.access_token

    def _get_headers(self, user_info: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        """요청 헤더 생성"""
        headers = {
            'Accept': 'application/json',
            'User-Agent': 'AIPaaS-Hub-Gateway/1.0'
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

    async def _make_authenticated_request(
            self,
            method: str,
            url: str,
            user_info: Optional[Dict[str, str]] = None,
            **kwargs
    ) -> httpx.Response:
        """인증된 요청 실행"""
        # 유효한 토큰 획득
        token = await self._get_valid_token()

        # 헤더 설정
        headers = self._get_headers(user_info)
        headers['Authorization'] = f"Bearer {token}"

        # 기존 헤더와 병합
        if 'headers' in kwargs:
            kwargs['headers'].update(headers)
        else:
            kwargs['headers'] = headers

        # 요청 실행
        response = await getattr(self.client, method.lower())(url, **kwargs)

        # 토큰이 만료된 경우 재시도
        if response.status_code == 401:
            logger.warning("Hub token expired during request, retrying with new token")
            # 토큰 강제 갱신
            self.access_token = None
            token = await self._get_valid_token()
            kwargs['headers']['Authorization'] = f"Bearer {token}"
            response = await getattr(self.client, method.lower())(url, **kwargs)

        return response

    async def get_models(
            self,
            params: ModelListParams,
            user_info: Optional[Dict[str, str]] = None
    ) -> ModelListResponse:
        """허브에서 모델 목록 조회"""
        try:
            url = f"{self.base_url}/models/"

            # 쿼리 파라미터 구성
            query_params = {
                "include_parameters": "true"  # 파라미터 정보 포함
            }
            if params.market:
                query_params["market"] = params.market
            if params.sort:
                query_params["sort"] = params.sort
            if params.page:
                query_params["page"] = params.page
            if params.limit:
                query_params["limit"] = params.limit
            if params.num_parameters_min:
                query_params["num_parameters_min"] = params.num_parameters_min
            if params.num_parameters_max:
                query_params["num_parameters_max"] = params.num_parameters_max
            # 검색 파라미터 변환: search -> query (외부 API 형식)
            if hasattr(params, 'search') and params.search:
                query_params["query"] = params.search  # 외부 API는 'query' 사용

            # 추가 필터 파라미터들 (task -> pipeline_tag로 매핑)
            if params.task:
                query_params["pipeline_tag"] = params.task  # task를 pipeline_tag로 매핑
            if params.license:
                query_params["license"] = params.license

            # 배열 파라미터들 (httpx는 리스트를 자동으로 여러 쿼리 파라미터로 변환)
            if params.library:
                query_params["library"] = params.library
            if params.language:
                query_params["language"] = params.language
            if params.apps:
                query_params["apps"] = params.apps
            if params.inference_provider:
                query_params["inference_provider"] = params.inference_provider
            if params.other:
                query_params["other"] = params.other

            logger.info(f"Getting hub models from: {url}")
            logger.info(f"Parameters: {query_params}")

            response = await self._make_authenticated_request(
                "GET", url, user_info=user_info, params=query_params
            )

            if response.status_code == 200:
                external_data = response.json()

                # 외부 API 응답에서 models 배열 추출
                models_data = []
                if isinstance(external_data, dict):
                    models_data = external_data.get('models', [])
                elif isinstance(external_data, list):
                    models_data = external_data

                # HubModelResponse 리스트로 변환
                models = []
                for model_dict in models_data:
                    try:
                        model = HubModelResponse(**model_dict)
                        models.append(model)
                    except Exception as e:
                        logger.warning(f"Failed to parse hub model: {e}")
                        continue

                # total 및 Kaggle 페이지네이션 메타 추출
                if isinstance(external_data, dict):
                    total = external_data.get('total')
                    has_more = external_data.get('has_more')
                    total_is_exact = external_data.get('total_is_exact')
                    applied_filters = external_data.get('applied_filters')
                else:
                    total = len(models)
                    has_more = None
                    total_is_exact = None
                    applied_filters = None

                return ModelListResponse(
                    data=models,
                    total=total,
                    page=params.page or 1,
                    limit=params.limit or len(models),
                    has_more=has_more,
                    total_is_exact=total_is_exact,
                    applied_filters=applied_filters,
                )

            else:
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"Failed to get hub models: {response.text}"
                )

        except httpx.TimeoutException as e:
            logger.error(f"Timeout getting hub models: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="Hub service timeout"
            )
        except httpx.ConnectError as e:
            logger.error(f"Connection error getting hub models: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Hub service unavailable"
            )
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error getting hub models: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Internal error: {str(e)}"
            )

    async def get_model_detail(
            self,
            model_id: str,
            market: str,
            user_info: Optional[Dict[str, str]] = None
    ) -> Optional[HubModelResponse]:
        """특정 모델 상세 정보 조회"""
        try:
            url = f"{self.base_url}/models/{model_id}"
            params = {"market": market}

            logger.info(f"Getting hub model detail from: {url}")

            response = await self._make_authenticated_request(
                "GET", url, user_info=user_info, params=params
            )

            if response.status_code == 200:
                model_data = response.json()
                return ExtendedHubModelResponse(**model_data)
            elif response.status_code == 404:
                return None
            else:
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"Failed to get hub model detail: {response.text}"
                )

        except httpx.TimeoutException as e:
            logger.error(f"Timeout getting hub model {model_id}: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="Hub service timeout"
            )
        except httpx.ConnectError as e:
            logger.error(f"Connection error getting hub model {model_id}: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Hub service unavailable"
            )
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error getting hub model {model_id}: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Internal error: {str(e)}"
            )

    async def get_model_files(
            self,
            model_id: str,
            market: str,
            user_info: Optional[Dict[str, str]] = None
    ) -> ModelFilesResponse:
        """모델 파일 목록 조회"""
        try:
            url = f"{self.base_url}/models/{model_id}/files"
            params = {"market": market}

            logger.info(f"Getting model files from: {url}")

            response = await self._make_authenticated_request(
                "GET", url, user_info=user_info, params=params
            )

            if response.status_code == 200:
                files_data = response.json()

                # 파일 목록 추출
                file_list = []
                if isinstance(files_data, dict):
                    file_list = files_data.get('files', files_data.get('data', []))
                elif isinstance(files_data, list):
                    file_list = files_data

                # ModelFileInfo 리스트로 변환
                files = []
                for file_dict in file_list:
                    try:
                        file_info = ModelFileInfo(**file_dict)
                        files.append(file_info)
                    except Exception as e:
                        logger.warning(f"Failed to parse file info: {e}")
                        continue

                return ModelFilesResponse(
                    data=files
                )

            else:
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"Failed to get model files: {response.text}"
                )

        except httpx.TimeoutException as e:
            logger.error(f"Timeout getting model files {model_id}: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="Hub service timeout"
            )
        except httpx.ConnectError as e:
            logger.error(f"Connection error getting model files {model_id}: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Hub service unavailable"
            )
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error getting model files {model_id}: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Internal error: {str(e)}"
            )

    async def download_model_file(
            self,
            model_id: str,
            filename: str,
            market: str,
            download_dir: Optional[str] = None,
            user_info: Optional[Dict[str, str]] = None
    ) -> Any:
        """모델 파일 다운로드"""
        try:
            url = f"{self.base_url}/models/{model_id}/download"
            params = {
                "filename": filename,
                "market": market
            }
            if download_dir:
                params["download_dir"] = download_dir

            logger.info(f"Downloading model file from: {url}")

            response = await self._make_authenticated_request(
                "GET", url, user_info=user_info, params=params
            )

            if response.status_code == 200:
                content_type = response.headers.get("content-type", "")
                if "application/json" in content_type:
                    return response.json()
                return response

            raise HTTPException(
                status_code=response.status_code,
                detail=f"Failed to download model file: {response.text}"
            )

        except httpx.TimeoutException as e:
            logger.error(f"Timeout downloading model file {model_id}/{filename}: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="Hub service timeout"
            )
        except httpx.ConnectError as e:
            logger.error(f"Connection error downloading model file {model_id}/{filename}: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Hub service unavailable"
            )
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error downloading model file {model_id}/{filename}: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Internal error: {str(e)}"
            )

    async def get_all_tags(self, market: str, user_info: Optional[Dict[str, str]] = None) -> TagListResponse:
        """전체 태그 목록 조회"""
        try:
            url = f"{self.base_url}/tags/"
            params = {"market": market}

            logger.info(f"Getting all tags from: {url} with market: {market}")

            response = await self._make_authenticated_request(
                "GET", url, user_info=user_info, params=params
            )

            if response.status_code == 200:
                tags_data = response.json()

                # pipeline_tag 키를 task로 변경
                if "pipeline_tag" in tags_data:
                    tags_data["task"] = tags_data.pop("pipeline_tag")
                    # 각 태그 아이템의 type 필드도 변경
                    for tag_item in tags_data["task"]:
                        if tag_item.get("type") == "pipeline_tag":
                            tag_item["type"] = "task"

                # TagListParams로 검증 및 변환
                tag_params = TagListParams(**tags_data)
                all_categories = tag_params.get_all_categories()

                # data 배열로 래핑 (단일 딕셔너리를 배열의 첫 번째 요소로)
                return TagListResponse(
                    data=[all_categories]
                )

            else:
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"Failed to get tags: {response.text}"
                )

        except httpx.TimeoutException as e:
            logger.error(f"Timeout getting tags: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="Tag service timeout"
            )
        except httpx.ConnectError as e:
            logger.error(f"Connection error getting tags: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Tag service unavailable"
            )
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error getting tags: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Internal error: {str(e)}"
            )

    async def get_all_tags_by_group(
            self,
            group: str,
            market: str,
            user_info: Optional[Dict[str, str]] = None
    ) -> TagGroupAllResponse:
        """특정 그룹의 전체 태그 목록 조회"""
        try:
            external_group = "pipeline_tag" if group == "task" else group
            url = f"{self.base_url}/tags/{external_group}/all"
            params = {"market": market}

            logger.info(
                f"Getting all tags for group '{group}' (external: '{external_group}') from: {url} with market: {market}"
            )

            response = await self._make_authenticated_request(
                "GET", url, user_info=user_info, params=params
            )

            if response.status_code == 200:
                group_data = response.json()
                data_list = group_data.get('data', []) if isinstance(group_data, dict) else group_data

                tag_items = []
                for item_dict in data_list:
                    try:
                        if item_dict.get("type") == "pipeline_tag":
                            item_dict["type"] = "task"
                        tag_item = TagItem(**item_dict)
                        tag_items.append(tag_item)
                    except Exception as e:
                        logger.warning(f"Failed to parse tag item: {e}")
                        continue

                return TagGroupAllResponse(data=tag_items)

            raise HTTPException(
                status_code=response.status_code,
                detail=f"Failed to get all tags for group '{group}': {response.text}"
            )

        except httpx.TimeoutException as e:
            logger.error(f"Timeout getting all tags for group '{group}': {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="Tag service timeout"
            )
        except httpx.ConnectError as e:
            logger.error(f"Connection error getting all tags for group '{group}': {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Tag service unavailable"
            )
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error getting all tags for group '{group}': {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Internal error: {str(e)}"
            )

    async def get_tags_by_group(self, group: str, market: str, user_info: Optional[Dict[str, str]] = None) -> TagGroupResponse:
        """특정 그룹의 태그 목록 조회"""
        try:
            # 사용자가 'task'를 요청하면 외부 API에는 'pipeline_tag'로 매핑
            external_group = "pipeline_tag" if group == "task" else group
            url = f"{self.base_url}/tags/{external_group}"
            params = {"market": market}

            logger.info(f"Getting tags for group '{group}' (external: '{external_group}') from: {url} with market: {market}")

            response = await self._make_authenticated_request(
                "GET", url, user_info=user_info, params=params
            )

            if response.status_code == 200:
                group_data = response.json()

                # 응답 구조: {"data": [...], "remaining_count": 0}
                tag_items = []
                if isinstance(group_data, dict):
                    data_list = group_data.get('data', [])
                    remaining_count = group_data.get('remaining_count', 0)

                    for item_dict in data_list:
                        try:
                            # pipeline_tag 타입을 task로 변경
                            if item_dict.get("type") == "pipeline_tag":
                                item_dict["type"] = "task"
                            tag_item = TagItem(**item_dict)
                            tag_items.append(tag_item)
                        except Exception as e:
                            logger.warning(f"Failed to parse tag item: {e}")
                            continue
                else:
                    # 만약 직접 리스트가 온다면
                    remaining_count = 0
                    for item_dict in group_data:
                        try:
                            # pipeline_tag 타입을 task로 변경
                            if item_dict.get("type") == "pipeline_tag":
                                item_dict["type"] = "task"
                            tag_item = TagItem(**item_dict)
                            tag_items.append(tag_item)
                        except Exception as e:
                            logger.warning(f"Failed to parse tag item: {e}")
                            continue

                return TagGroupResponse(
                    data=tag_items,
                    remaining_count=remaining_count
                )

            elif response.status_code == 404:
                # 그룹이 없는 경우 빈 응답 반환
                return TagGroupResponse(
                    data=[],
                    remaining_count=0
                )
            else:
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"Failed to get tags for group '{group}': {response.text}"
                )

        except httpx.TimeoutException as e:
            logger.error(f"Timeout getting tags for group '{group}': {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="Tag service timeout"
            )
        except httpx.ConnectError as e:
            logger.error(f"Connection error getting tags for group '{group}': {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Tag service unavailable"
            )
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error getting tags for group '{group}': {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Internal error: {str(e)}"
            )


    # ===== Datasets =====

    async def get_datasets(
            self,
            params: DatasetListParams,
            user_info: Optional[Dict[str, str]] = None
    ) -> DatasetListResponse:
        """데이터셋 목록 조회 (공개 page/size → 업스트림 page/limit 내부 변환)"""
        try:
            url = f"{self.base_url}/datasets/"

            query_params: Dict[str, Any] = {}
            if params.market:
                query_params["market"] = params.market
            if params.query:
                query_params["query"] = params.query
            if params.sort:
                query_params["sort"] = params.sort
            if params.page:
                query_params["page"] = params.page
            if params.size:
                query_params["limit"] = params.size  # 공개: size → 업스트림: limit

            logger.info(f"Getting hub datasets from: {url}")

            response = await self._make_authenticated_request(
                "GET", url, user_info=user_info, params=query_params
            )

            if response.status_code == 200:
                external_data = response.json()

                datasets_data = []
                if isinstance(external_data, dict):
                    datasets_data = external_data.get('datasets', external_data.get('data', []))
                elif isinstance(external_data, list):
                    datasets_data = external_data

                datasets: List[HubDatasetItem] = []
                for item in datasets_data:
                    try:
                        datasets.append(HubDatasetItem(**item))
                    except Exception as e:
                        logger.warning(f"Failed to parse hub dataset item: {e}")
                        continue

                if isinstance(external_data, dict):
                    total = external_data.get('total')
                    has_more = external_data.get('has_more')
                    total_is_exact = external_data.get('total_is_exact')
                else:
                    total = len(datasets)
                    has_more = None
                    total_is_exact = None

                return DatasetListResponse(
                    data=datasets,
                    total=total,
                    page=params.page or 1,
                    size=params.size or len(datasets),
                    has_more=has_more,
                    total_is_exact=total_is_exact,
                )

            raise HTTPException(
                status_code=response.status_code,
                detail=f"Failed to get hub datasets: {response.text}"
            )

        except httpx.TimeoutException as e:
            logger.error(f"Timeout getting hub datasets: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="Hub service timeout"
            )
        except httpx.ConnectError as e:
            logger.error(f"Connection error getting hub datasets: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Hub service unavailable"
            )
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error getting hub datasets: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Internal error: {str(e)}"
            )

    async def get_dataset_info(
            self,
            repo_id: str,
            market: str,
            user_info: Optional[Dict[str, str]] = None
    ) -> DatasetInfoResponse:
        """데이터셋 상세 조회"""
        try:
            url = f"{self.base_url}/datasets/{repo_id}/info"
            params = {"market": market}

            logger.info(f"Getting hub dataset info from: {url}")

            response = await self._make_authenticated_request(
                "GET", url, user_info=user_info, params=params
            )

            if response.status_code == 200:
                return DatasetInfoResponse(**response.json())

            raise HTTPException(
                status_code=response.status_code,
                detail=f"Failed to get hub dataset info: {response.text}"
            )

        except httpx.TimeoutException as e:
            logger.error(f"Timeout getting hub dataset info {repo_id}: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="Hub service timeout"
            )
        except httpx.ConnectError as e:
            logger.error(f"Connection error getting hub dataset info {repo_id}: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Hub service unavailable"
            )
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error getting hub dataset info {repo_id}: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Internal error: {str(e)}"
            )

    async def get_dataset_files(
            self,
            repo_id: str,
            market: str,
            user_info: Optional[Dict[str, str]] = None
    ) -> DatasetFilesResponse:
        """데이터셋 파일 목록 조회"""
        try:
            url = f"{self.base_url}/datasets/{repo_id}/files"
            params = {"market": market}

            logger.info(f"Getting hub dataset files from: {url}")

            response = await self._make_authenticated_request(
                "GET", url, user_info=user_info, params=params
            )

            if response.status_code == 200:
                files_data = response.json()
                file_list = []
                if isinstance(files_data, dict):
                    file_list = files_data.get('files', files_data.get('data', []))
                elif isinstance(files_data, list):
                    file_list = files_data

                files: List[DatasetFileInfo] = []
                for file_dict in file_list:
                    try:
                        files.append(DatasetFileInfo(**file_dict))
                    except Exception as e:
                        logger.warning(f"Failed to parse dataset file info: {e}")
                        continue

                return DatasetFilesResponse(data=files)

            raise HTTPException(
                status_code=response.status_code,
                detail=f"Failed to get hub dataset files: {response.text}"
            )

        except httpx.TimeoutException as e:
            logger.error(f"Timeout getting hub dataset files {repo_id}: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="Hub service timeout"
            )
        except httpx.ConnectError as e:
            logger.error(f"Connection error getting hub dataset files {repo_id}: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Hub service unavailable"
            )
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error getting hub dataset files {repo_id}: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Internal error: {str(e)}"
            )

    async def download_dataset_snapshot(
            self,
            repo_id: str,
            market: str,
            download_dir: Optional[str] = None,
            allow_patterns: Optional[List[str]] = None,
            ignore_patterns: Optional[List[str]] = None,
            user_info: Optional[Dict[str, str]] = None,
    ) -> Any:
        """데이터셋 스냅샷 다운로드 (download_dir 지정 시 JSON, 미지정 시 바이너리 응답)"""
        try:
            url = f"{self.base_url}/datasets/{repo_id}/download"
            params: Dict[str, Any] = {"market": market}
            if download_dir:
                params["download_dir"] = download_dir
            if allow_patterns:
                params["allow_patterns"] = allow_patterns
            if ignore_patterns:
                params["ignore_patterns"] = ignore_patterns

            logger.info(f"Downloading dataset snapshot from: {url}")

            response = await self._make_authenticated_request(
                "GET", url, user_info=user_info, params=params
            )

            if response.status_code == 200:
                content_type = response.headers.get("content-type", "")
                if "application/json" in content_type:
                    return response.json()
                return response

            raise HTTPException(
                status_code=response.status_code,
                detail=f"Failed to download dataset snapshot: {response.text}"
            )

        except httpx.TimeoutException as e:
            logger.error(f"Timeout downloading dataset snapshot {repo_id}: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="Hub service timeout"
            )
        except httpx.ConnectError as e:
            logger.error(f"Connection error downloading dataset snapshot {repo_id}: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Hub service unavailable"
            )
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error downloading dataset snapshot {repo_id}: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Internal error: {str(e)}"
            )

    async def download_dataset_file(
            self,
            repo_id: str,
            filename: str,
            market: str,
            user_info: Optional[Dict[str, str]] = None,
    ) -> Any:
        """데이터셋 파일 단건 다운로드"""
        try:
            url = f"{self.base_url}/datasets/{repo_id}/download/{filename}"
            params = {"market": market}

            logger.info(f"Downloading dataset file from: {url}")

            response = await self._make_authenticated_request(
                "GET", url, user_info=user_info, params=params
            )

            if response.status_code == 200:
                content_type = response.headers.get("content-type", "")
                if "application/json" in content_type:
                    return response.json()
                return response

            raise HTTPException(
                status_code=response.status_code,
                detail=f"Failed to download dataset file: {response.text}"
            )

        except httpx.TimeoutException as e:
            logger.error(f"Timeout downloading dataset file {repo_id}/{filename}: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="Hub service timeout"
            )
        except httpx.ConnectError as e:
            logger.error(f"Connection error downloading dataset file {repo_id}/{filename}: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Hub service unavailable"
            )
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error downloading dataset file {repo_id}/{filename}: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Internal error: {str(e)}"
            )


# 싱글톤 인스턴스
hub_connect_service = HubConnectService()
