import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.cruds.service import service_crud
from app.database import get_db
from app.schemas.service import (
    ServiceCreate,
    ServiceUpdate,
    ServiceResponse,
    ServiceDetailResponse,
    ServiceListResponse
)
from app.services.service_service import service_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/services", tags=["services"])


@router.post("/", response_model=ServiceResponse)
async def create_service(
        service: ServiceCreate,
        db: Session = Depends(get_db),
        current_user=Depends(get_current_user)
):
    """
    새로운 서비스 생성

    서비스는 워크플로우를 그룹화하고 모니터링하는 최상위 단위입니다.
    하나의 서비스에 여러 워크플로우를 연결하여 통합 관리할 수 있습니다.

    ## Request Body (application/json) — `ServiceCreateRequest`

    | 필드 | 타입 | 필수 | 설명 |
    |------|------|------|------|
    | `name` | string | ✅ | 서비스 이름 (1-255자, 고유값) |
    | `description` | string | — | 서비스에 대한 상세 설명 |
    | `tags` | List[string] | — | 서비스 분류/검색용 태그 리스트 |

    ## Response (200) — `ServiceResponse`

    | 필드 | 타입 | 설명 |
    |------|------|------|
    | `id` | integer | 게이트웨이 내부 서비스 ID |
    | `name` | string | 서비스 이름 |
    | `description` | string \\| null | 서비스 설명 |
    | `tags` | List[string] | 서비스 태그 목록 |
    | `created_at` | datetime | 생성 시각 |
    | `updated_at` | datetime | 최종 수정 시각 |
    | `created_by` | string | 생성자 식별자 |
    | `surro_service_id` | string | 외부 서비스 ID (UUID) |

    ## Errors
    - 400: 이미 존재하는 서비스 이름이거나 유효하지 않은 요청
    - 401: 인증되지 않은 사용자
    - 500: 서버 내부 오류
    """
    user_info = {
        'member_id': current_user.member_id,
        'role': current_user.role,
        'name': current_user.name
    }

    # 외부 API 호출
    external_service = await service_service.create_service(
        name=service.name,
        description=service.description,
        tags=service.tags,
        user_info=user_info
    )

    # 우리 DB에 저장 (Model과 동일한 패턴)
    try:
        db_service = service_crud.create_service(
            db=db,
            service=service,
            created_by=current_user.member_id,
            surro_service_id=external_service.id
        )
        logger.info(
            f"Created service mapping: surro_id={external_service.id}, "
            f"member_id={current_user.member_id}"
        )
    except Exception as mapping_error:
        logger.error(f"Failed to create service mapping: {str(mapping_error)}")
        # 매핑 저장에 실패해도 외부 API에는 이미 생성됨
        logger.warning(f"Service {external_service.id} created in external API but mapping failed")
        # 여기서 어떻게 할지 결정 - 에러를 던질지, 부분 성공으로 처리할지
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Service created in external API but failed to save mapping: {str(mapping_error)}"
        )

    return db_service


@router.get("/", response_model=ServiceListResponse)
async def get_services(
        page: int = Query(1, ge=1, description="페이지 번호 (1부터 시작)"),
        size: int = Query(20, ge=1, le=100, description="페이지당 항목 수"),
        search: Optional[str] = Query(None, description="검색어 (이름, 설명)"),
        db: Session = Depends(get_db),
        current_user=Depends(get_current_user)
):
    """
    서비스 목록 조회

    등록된 서비스들의 목록을 페이지네이션하여 조회합니다.
    각 서비스의 기본 정보를 페이지네이션하여 제공합니다.

    ## Query Parameters

    | 필드 | 타입 | 필수 | 기본값 | 설명 |
    |------|------|------|--------|------|
    | `page` | integer | — | 1 | 페이지 번호 (1부터 시작) |
    | `size` | integer | — | 20 | 페이지당 항목 수 (1-100) |
    | `search` | string | — | — | 검색어 (이름, 설명) |

    ## Response (200) — `ServiceListResponse`

    | 필드 | 타입 | 설명 |
    |------|------|------|
    | `data` | List[ServiceResponse] | 서비스 목록 |
    | `total` | integer | 조건에 맞는 전체 서비스 수 |
    | `page` | integer | 현재 페이지 번호 |
    | `size` | integer | 페이지당 항목 수 |

    ## Errors
    - 401: 인증되지 않은 사용자
    - 500: 서버 내부 오류
    """
    skip = (page - 1) * size
    services, total = service_crud.get_services(
        db=db,
        skip=skip,
        limit=size,
        search=search
    )

    return ServiceListResponse(
        data=services,
        total=total,
        page=page,
        size=size
    )


@router.get("/{surro_service_id}", response_model=ServiceDetailResponse)
async def get_service(
        surro_service_id: str,
        db: Session = Depends(get_db),
        current_user=Depends(get_current_user)
):
    """
    서비스 상세정보 조회

    특정 서비스의 상세 정보를 조회합니다.
    연결된 모든 워크플로우 정보와 최근 1시간의 모니터링 메트릭을 포함합니다.

    ## Path Parameters

    | 필드 | 타입 | 설명 |
    |------|------|------|
    | `surro_service_id` | string | 조회할 서비스의 고유 ID (UUID) |

    ## Response (200) — `ServiceDetailResponse`

    | 필드 | 타입 | 설명 |
    |------|------|------|
    | `id` | integer | 게이트웨이 내부 서비스 ID |
    | `name` | string | 서비스 이름 |
    | `description` | string \\| null | 서비스 설명 |
    | `tags` | List[string] | 서비스 태그 목록 |
    | `created_at` | datetime | 생성 시각 |
    | `updated_at` | datetime | 최종 수정 시각 |
    | `created_by` | string | 생성자 식별자 |
    | `surro_service_id` | string | 외부 서비스 ID (UUID) |
    | `workflow_count` | integer | 연결된 워크플로우 수 |
    | `workflows` | List[WorkflowBaseSchema] | 연결된 워크플로우 목록 |
    | `monitoring_data` | ServiceMonitoringData \\| null | 모니터링 데이터 |

    ### monitoring_data.total_metrics (MonitoringMetrics)

    | 필드 | 타입 | 설명 |
    |------|------|------|
    | `message_count` | integer | 최근 1시간 총 메시지 수 |
    | `active_users` | integer | 최근 1시간 활성 사용자 수 |
    | `token_usage` | integer | 최근 1시간 토큰 사용량 |
    | `avg_interaction_count` | float | 최근 1시간 평균 사용자 상호작용 수 |
    | `response_time_ms` | float | 평균 응답 시간(ms) |
    | `error_count` | integer | 최근 1시간 오류 수 |
    | `success_rate` | float | 최근 1시간 성공률(%) |

    ## Errors
    - 401: 인증되지 않은 사용자
    - 404: 서비스를 찾을 수 없음
    - 500: 서버 내부 오류
    """
    # 1. 내부 DB 조회
    db_service = service_crud.get_service_by_surro_id(db=db, surro_service_id=surro_service_id)
    if not db_service:
        raise HTTPException(status_code=404, detail="Service not found")

    # 2. 외부 API 조회
    user_info = {
        'member_id': current_user.member_id,
        'role': current_user.role,
        'name': current_user.name
    }

    try:
        logger.info(f"Fetching external service data for UUID: {surro_service_id}")
        external_data = await service_service.get_service(
            surro_service_id,
            user_info
        )
        logger.info(f"External data fetched successfully: {external_data is not None}")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to fetch external service data for {surro_service_id}: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to fetch service detail from external API: {str(e)}"
        )

    if not external_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Service {surro_service_id} not found in external API"
        )

    # 3. 최종 응답 = 내부 DB + 외부 API 데이터 병합
    response = ServiceDetailResponse(
        id=db_service.id,
        name=db_service.name,
        description=db_service.description,
        tags=db_service.tags,
        created_at=db_service.created_at,
        updated_at=db_service.updated_at,
        created_by=db_service.created_by,
        surro_service_id=db_service.surro_service_id,

        # 외부 API 데이터 병합
        workflow_count=getattr(external_data, "workflow_count", 0),
        workflows=getattr(external_data, "workflows", []),
        monitoring_data=getattr(external_data, "monitoring_data", None)
    )

    return response


@router.get("/{surro_service_id}/resource-usages")
async def get_service_resource_usages(
        surro_service_id: str,
        db: Session = Depends(get_db),
        current_user=Depends(get_current_user)
):
    """
    서비스 리소스 사용량 조회

    서비스에 속한 워크플로우의 배포된 모델들의 리소스 사용량을 조회합니다.
    k8s metrics API를 사용하여 CPU, Memory, GPU 사용량을 가져옵니다.

    ## Path Parameters

    | 필드 | 타입 | 설명 |
    |------|------|------|
    | `surro_service_id` | string | 조회할 서비스의 고유 ID (UUID) |

    ## Response (200) — `ServiceResourceUsageResponse`

    | 필드 | 타입 | 설명 |
    |------|------|------|
    | `service_id` | string | 서비스 고유 ID (UUID) |
    | `service_name` | string | 서비스 이름 |
    | `deployments` | List[DeploymentResourceUsage] | 배포별 리소스 사용량 목록 |
    | `total_cpu_usage_millicores` | float \\| null | 전체 CPU 사용량 (밀리코어 단위) |
    | `total_memory_usage_bytes` | integer \\| null | 전체 메모리 사용량 (바이트 단위) |
    | `total_gpu_usage_percent` | float \\| null | 전체 GPU 사용률 (%) |

    ### deployments[].pods[].resource_usage (ResourceUsage)

    | 필드 | 타입 | 설명 |
    |------|------|------|
    | `cpu_usage_millicores` | float \\| null | CPU 사용량 (밀리코어 단위) |
    | `cpu_request_millicores` | float \\| null | CPU 요청량 (밀리코어 단위) |
    | `cpu_limit_millicores` | float \\| null | CPU 제한량 (밀리코어 단위) |
    | `memory_usage_bytes` | integer \\| null | 메모리 사용량 (바이트 단위) |
    | `memory_request_bytes` | integer \\| null | 메모리 요청량 (바이트 단위) |
    | `memory_limit_bytes` | integer \\| null | 메모리 제한량 (바이트 단위) |
    | `gpu_usage_percent` | float \\| null | GPU 사용률 (%) |
    | `gpu_memory_usage_bytes` | integer \\| null | GPU 메모리 사용량 (바이트 단위) |

    ## Notes
    - Metrics Server가 설치되어 있어야 실제 사용량을 조회할 수 있습니다.
    - Metrics Server가 없는 경우 리소스 요청/제한 정보만 반환됩니다.
    - GPU 사용량은 별도의 메트릭 수집기(dcgm-exporter 등)가 필요합니다.

    ## Errors
    - 401: 인증되지 않은 사용자
    - 404: 서비스를 찾을 수 없음
    - 500: 서버 내부 오류 또는 Kubernetes API 접근 실패
    """
    # 내부 DB에서 서비스 존재 확인
    db_service = service_crud.get_service_by_surro_id(db=db, surro_service_id=surro_service_id)
    if not db_service:
        raise HTTPException(status_code=404, detail="Service not found")

    user_info = {
        'member_id': current_user.member_id,
        'role': current_user.role,
        'name': current_user.name
    }

    result = await service_service.get_resource_usages(
        service_id=surro_service_id,
        user_info=user_info
    )
    return result


@router.put("/{surro_service_id}", response_model=ServiceResponse)
async def update_service(
        surro_service_id: str,  # int -> str (UUID)
        service_update: ServiceUpdate,
        db: Session = Depends(get_db),
        current_user=Depends(get_current_user)
):
    """
    서비스 정보 수정

    기존 서비스의 정보를 부분적으로 또는 전체적으로 수정합니다.
    제공된 필드만 업데이트되며, 생략된 필드는 기존 값이 유지됩니다.

    ## Path Parameters

    | 필드 | 타입 | 설명 |
    |------|------|------|
    | `surro_service_id` | string | 수정할 서비스의 고유 ID (UUID) |

    ## Request Body (application/json) — `ServiceUpdateRequest`

    | 필드 | 타입 | 필수 | 설명 |
    |------|------|------|------|
    | `name` | string | — | 새로운 서비스 이름 (1-255자, 다른 서비스와 중복 불가) |
    | `description` | string | — | 새로운 서비스 설명 (null 값으로 설명 제거 가능) |
    | `tags` | List[string] | — | 새로운 태그 목록 (기존 태그를 완전히 대체, 빈 리스트로 모든 태그 제거 가능) |

    ## Response (200) — `ServiceResponse`

    수정된 서비스 정보를 반환합니다. (create_service 응답과 동일한 구조)

    ## Notes
    - 서비스 이름 변경 시 중복 검사 수행
    - 연결된 워크플로우는 영향받지 않음

    ## Errors
    - 400: 중복된 서비스 이름 또는 유효하지 않은 요청
    - 401: 인증되지 않은 사용자
    - 403: 권한 없음
    - 404: 서비스를 찾을 수 없음
    - 500: 서버 내부 오류
    """
    # UUID로 우리 DB에서 기존 서비스 조회
    existing_service = service_crud.get_service_by_surro_id(db=db, surro_service_id=surro_service_id)
    if not existing_service:
        raise HTTPException(status_code=404, detail="Service not found")

    # 권한 확인
    if current_user.role != "admin" and existing_service.created_by != current_user.member_id:
        raise HTTPException(status_code=403, detail="Permission denied")

    # 외부 API 업데이트
    user_info = {
        'member_id': current_user.member_id,
        'role': current_user.role,
        'name': current_user.name
    }

    try:
        await service_service.update_service(
            service_id=surro_service_id,  # UUID 사용
            name=service_update.name,
            description=service_update.description,
            tags=service_update.tags,
            user_info=user_info
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to update external service: {str(e)}"
        )

    # 우리 DB 업데이트
    updated_service = service_crud.update_service_by_surro_id(
        db=db,
        surro_service_id=surro_service_id,
        service_update=service_update
    )

    return updated_service


@router.delete("/{surro_service_id}", status_code=204)
async def delete_service(
        surro_service_id: str,  # int -> str (UUID)
        db: Session = Depends(get_db),
        current_user=Depends(get_current_user)
):
    """
    서비스 삭제

    서비스를 삭제합니다. 연결된 워크플로우가 있는 경우 연결만 해제되며,
    워크플로우 자체는 삭제되지 않고 독립적으로 유지됩니다.

    ## Path Parameters

    | 필드 | 타입 | 설명 |
    |------|------|------|
    | `surro_service_id` | string | 삭제할 서비스의 고유 ID (UUID) |

    ## Response
    - **Status Code**: 204 No Content (성공 시 응답 본문 없음)

    ## Side Effects
    - 서비스와 연결된 모든 워크플로우의 service_id가 null로 설정됨
    - 서비스 관련 모니터링 데이터는 보존됨 (향후 분석용)
    - 서비스 정보는 데이터베이스에서 완전히 삭제됨

    ## Notes
    - 삭제는 되돌릴 수 없는 작업입니다
    - 워크플로우를 삭제하려면 별도로 워크플로우 삭제 API를 호출해야 함

    ## Errors
    - 401: 인증되지 않은 사용자
    - 403: 권한 없음
    - 404: 서비스를 찾을 수 없음
    - 500: 서버 내부 오류
    """
    # UUID로 우리 DB에서 기존 서비스 조회
    existing_service = service_crud.get_service_by_surro_id(db=db, surro_service_id=surro_service_id)
    if not existing_service:
        raise HTTPException(status_code=404, detail="Service not found")

    # 권한 확인
    if current_user.role != "admin" and existing_service.created_by != current_user.member_id:
        raise HTTPException(status_code=403, detail="Permission denied")

    # 외부 API 삭제
    user_info = {
        'member_id': current_user.member_id,
        'role': current_user.role,
        'name': current_user.name
    }

    try:
        await service_service.delete_service(
            surro_service_id,  # UUID 사용
            user_info
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to delete external service: {str(e)}"
        )

    # 우리 DB 삭제
    success = service_crud.delete_service_by_surro_id(db=db, surro_service_id=surro_service_id)
    if not success:
        raise HTTPException(status_code=404, detail="Service not found")

    return None  # 204 No Content
