import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.common.sort import parse_sort, resolve_sort_columns
from app.cruds.prompt import prompt_crud
from app.database import get_db
from app.models import Member
from app.models.prompt import Prompt
from app.schemas.prompt import (
    ExternalPromptResponse,
    PromptCreate,
    PromptDetailResponse,
    PromptListResponse,
    PromptResponse,
    PromptUpdate,
    PromptVariableReadSchema,
    PromptVariableTypeListSchema,
)
from app.services.prompt_service import prompt_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/prompts", tags=["prompts"])

_PROMPT_SORT_FIELDS = {
    "id": Prompt.id,
    "name": Prompt.name,
    "created_at": Prompt.created_at,
    "updated_at": Prompt.updated_at,
    "created_by": Prompt.created_by,
}
_PROMPT_SORT_DEFAULT = [(Prompt.created_at, True)]
_PROMPT_SORT_TIE_BREAKER = Prompt.id


def _user_info(user: Member) -> dict:
    return {
        "member_id": user.member_id,
        "role": user.role,
        "name": user.name,
    }


def _normalize_prompt_variable(raw) -> Optional[List[PromptVariableReadSchema]]:
    if not raw or not isinstance(raw, list):
        return None

    first = raw[0]
    if isinstance(first, PromptVariableReadSchema):
        return list(raw)
    if isinstance(first, dict):
        return [PromptVariableReadSchema(**var) for var in raw if isinstance(var, dict)]
    return None


def _to_prompt_response(db_prompt: Prompt, external: ExternalPromptResponse) -> PromptResponse:
    return PromptResponse(
        id=db_prompt.id,
        surro_prompt_id=db_prompt.surro_prompt_id,
        created_at=db_prompt.created_at,
        updated_at=db_prompt.updated_at,
        created_by=db_prompt.created_by,
        name=external.name,
        description=external.description,
        content=external.content,
        prompt_variable=_normalize_prompt_variable(external.prompt_variable),
    )


def _get_active_admin_member(db: Session) -> Optional[Member]:
    return db.query(Member).filter(
        Member.role == "admin",
        Member.is_active == True,
    ).order_by(Member.id.asc()).first()


def _get_default_mapping_owner(db: Session, current_user: Member) -> Member:
    """미매핑 prompt의 기본 owner를 결정한다.

    - admin 요청이면 현재 admin 사용자를 owner로 사용
    - 일반 사용자 요청이면 활성 admin을 조회해 owner로 사용
    - 활성 admin이 없으면 500 대신 현재 사용자를 fallback owner로 사용
    """
    if current_user.role == "admin":
        return current_user

    admin = _get_active_admin_member(db)
    if admin:
        return admin

    logger.warning(
        "No active admin member found; using current user as fallback prompt mapping owner: %s",
        current_user.member_id,
    )
    return current_user


async def _fetch_external_prompts(current_user: Member) -> List[ExternalPromptResponse]:
    """현재 사용자가 볼 수 있는 external prompt 목록을 조회한다."""
    return await prompt_service.get_prompts(
        page=None,
        page_size=None,
        user_info=_user_info(current_user),
    )


def _sync_external_prompts_to_db(
        db: Session,
        owner: Member,
        external_list: List[ExternalPromptResponse],
) -> None:
    """보이는 external prompt 중 미매핑/soft-deleted 항목을 로컬 DB에 반영한다."""
    for ext in external_list:
        try:
            prompt_crud.create_mapping_from_external(
                db=db,
                surro_prompt_id=ext.id,
                member_id=owner.member_id,
                name=ext.name,
                description=ext.description,
                content=ext.content,
                prompt_variable=ext.prompt_variable,
            )
        except Exception as sync_error:
            logger.warning("Failed to sync external prompt %s: %s", ext.id, sync_error)


async def _sync_prompt_cache(db: Session, current_user: Member) -> List[ExternalPromptResponse]:
    """prompt 캐시 sync.

    - 일반 사용자: 본인이 볼 수 있는 external prompt만 DB에 보정
    - admin 사용자: admin이 볼 수 있는 전체 external prompt 기준으로 보정 + stale soft-delete
    """
    visible_external_list = await _fetch_external_prompts(current_user)
    owner = _get_default_mapping_owner(db, current_user)
    _sync_external_prompts_to_db(db, owner, visible_external_list)

    if current_user.role == "admin":
        prompt_crud.soft_delete_missing_mappings(
            db=db,
            active_surro_prompt_ids=[ext.id for ext in visible_external_list if ext.id is not None],
            deleted_by=current_user.member_id,
        )

    return visible_external_list


def _ensure_prompt_mapping(
        db: Session,
        current_user: Member,
        external: ExternalPromptResponse,
) -> Prompt:
    """외부 prompt 기준 로컬 매핑을 보정하고 최신 캐시 row를 반환한다."""
    owner = _get_default_mapping_owner(db, current_user)
    prompt_crud.create_mapping_from_external(
        db=db,
        surro_prompt_id=external.id,
        member_id=owner.member_id,
        name=external.name,
        description=external.description,
        content=external.content,
        prompt_variable=external.prompt_variable,
    )
    prompt_crud.backfill_cache_if_changed(
        db=db,
        surro_prompt_id=external.id,
        name=external.name,
        description=external.description,
        content=external.content,
        prompt_variable=external.prompt_variable,
    )

    db_prompt = prompt_crud.get_prompt_by_surro_id(db=db, surro_prompt_id=external.id)
    if not db_prompt:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Prompt mapping sync failed",
        )
    return db_prompt


@router.get("/variable-types", response_model=PromptVariableTypeListSchema)
async def get_variable_types(
        current_user=Depends(get_current_user)
):
    """
    프롬프트 변수 가능한 타입 목록 조회

    프롬프트에서 사용할 수 있는 변수 타입 목록을 조회합니다.

    ## Response (200) — `PromptVariableTypeListSchema`

    | 필드 | 타입 | 설명 |
    |------|------|------|
    | `available_types` | List[string] | 사용 가능한 변수 타입 목록 |

    ## Errors
    - 401: 인증되지 않은 사용자
    - 500: 서버 내부 오류
    """
    return await prompt_service.get_variable_types(user_info=_user_info(current_user))


@router.post("/", response_model=PromptResponse)
async def create_prompt(
        prompt: PromptCreate,
        db: Session = Depends(get_db),
        current_user=Depends(get_current_user)
):
    """
    프롬프트 생성

    새로운 프롬프트와 프롬프트 변수를 생성합니다.

    ## Request Body (application/json) — `PromptCreate`

    - **prompt** (PromptBaseSchema, required): 프롬프트 기본 정보
      - **name** (str, required): 프롬프트 이름
      - **description** (str, optional): 프롬프트 설명
      - **content** (str, required): 프롬프트 내용
    - **prompt_variable** (List[str], optional): 프롬프트 변수 이름 목록

    ## Response (200) — `PromptResponse`

    | 필드 | 타입 | 설명 |
    |------|------|------|
    | `id` | integer | 게이트웨이 내부 프롬프트 ID |
    | `surro_prompt_id` | integer | 외부 프롬프트 ID |
    | `created_at` | datetime | 생성 시각 |
    | `updated_at` | datetime | 최종 수정 시각 |
    | `created_by` | string | 생성자 식별자 |
    | `name` | string | 프롬프트 이름 |
    | `description` | string or null | 프롬프트 설명 |
    | `content` | string | 프롬프트 내용 |
    | `prompt_variable` | List[PromptVariableReadSchema] or null | 프롬프트 변수 목록 |

    ## Errors
    - 400: 유효하지 않은 요청
    - 401: 인증되지 않은 사용자
    - 500: 서버 내부 오류
    """
    external_prompt = await prompt_service.create_prompt(
        name=prompt.prompt.name,
        content=prompt.prompt.content,
        description=prompt.prompt.description,
        prompt_variable=prompt.prompt_variable,
        user_info=_user_info(current_user),
    )

    try:
        db_prompt = prompt_crud.create_prompt(
            db=db,
            prompt=prompt,
            created_by=current_user.member_id,
            surro_prompt_id=external_prompt.id,
            external_prompt_variables=external_prompt.prompt_variable,
        )
    except Exception as mapping_error:
        logger.error("Failed to create prompt mapping: %s", mapping_error)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Prompt created in external API but failed to save: {mapping_error}",
        )

    return _to_prompt_response(db_prompt, external_prompt)


@router.get("/", response_model=PromptListResponse)
async def get_prompts(
        page: Optional[int] = Query(None, ge=1, description="페이지 번호 (1부터 시작)"),
        size: Optional[int] = Query(None, ge=1, le=1000, description="페이지당 항목 수"),
        search: Optional[str] = Query(None, description="검색어 (이름, 설명, 내용)"),
        sort: Optional[str] = Query(
            None,
            description=(
                "정렬 기준. `,` 로 다중 키, `-` 접두사는 내림차순(DESC). "
                "미지정 시 `-created_at`. 허용 필드: "
                "`id`, `name`, `created_at`, `updated_at`, `created_by`."
            ),
            openapi_examples={
                "default": {"summary": "최신순 (기본)", "value": "-created_at"},
                "name_asc": {"summary": "이름 오름차순", "value": "name"},
                "name_desc": {"summary": "이름 내림차순", "value": "-name"},
                "multi": {"summary": "작성자 ASC + 최신순", "value": "created_by,-created_at"},
            },
        ),
        db: Session = Depends(get_db),
        current_user=Depends(get_current_user)
):
    """
    프롬프트 목록 조회

    현재 사용자가 조회 가능한 프롬프트 목록을 페이지네이션하여 반환합니다.
    조회 시 external MLOps 데이터를 기준으로 로컬 캐시를 보정합니다.

    ## Query Parameters

    | 필드 | 타입 | 필수 | 설명 |
    |------|------|------|------|
    | `page` | integer | — | 페이지 번호 (1부터 시작, 생략 시 전체 데이터 조회) |
    | `size` | integer | — | 페이지당 항목 수 (1-1000, 생략 시 전체 데이터 조회) |
    | `search` | string | — | 검색어 (이름, 설명, 내용) |
    | `sort` | string | — | 정렬. `,`로 다중 키, `-` 접두사=DESC. 기본 `-created_at` |

    ## Response (200) — `PromptListResponse`

    | 필드 | 타입 | 설명 |
    |------|------|------|
    | `data` | List[PromptResponse] | 프롬프트 목록 |
    | `total` | integer | 전체 프롬프트 수 |
    | `page` | integer or null | 현재 페이지 번호 |
    | `size` | integer or null | 페이지당 항목 수 |

    ## Notes
    - page와 size를 모두 생략하면 전체 데이터를 조회합니다.
    - admin 호출 시 external 전체 목록 기준으로 stale 로컬 매핑을 soft-delete 처리합니다.
    - 로컬에 없는 external prompt는 기본적으로 active admin 소유로 매핑됩니다.

    ## Errors
    - 401: 인증되지 않은 사용자
    - 422: 허용되지 않은 sort 필드
    - 500: 서버 내부 오류
    """
    try:
        skip = None
        limit = None
        if page is not None and size is not None:
            skip = (page - 1) * size
            limit = size

        visible_external_list = await _sync_prompt_cache(db, current_user)
        detail_by_external_id = {
            ext.id: ext for ext in visible_external_list if ext.id is not None
        }
        valid_external_ids = set(detail_by_external_id.keys())

        order_by = resolve_sort_columns(
            parsed=parse_sort(sort),
            allowed=_PROMPT_SORT_FIELDS,
            default=_PROMPT_SORT_DEFAULT,
            tie_breaker=_PROMPT_SORT_TIE_BREAKER,
        )

        prompts, total = prompt_crud.get_prompts(
            db=db,
            skip=skip,
            limit=limit,
            search=search,
            order_by=order_by,
            valid_surro_ids=valid_external_ids,
        )
        if not prompts:
            return PromptListResponse(data=[], total=total, page=page, size=size)

        response_data = []
        for db_prompt in prompts:
            ext = detail_by_external_id.get(db_prompt.surro_prompt_id)
            if ext is None:
                continue
            prompt_crud.backfill_cache_if_changed(
                db=db,
                surro_prompt_id=db_prompt.surro_prompt_id,
                name=ext.name,
                description=ext.description,
                content=ext.content,
                prompt_variable=ext.prompt_variable,
            )
            response_data.append(_to_prompt_response(db_prompt, ext))

        return PromptListResponse(
            data=response_data,
            total=total,
            page=page,
            size=size,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error listing prompts for user %s: %s", current_user.member_id, e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list prompts: {e}",
        )


@router.get("/{surro_prompt_id}", response_model=PromptDetailResponse)
async def get_prompt(
        surro_prompt_id: int,
        db: Session = Depends(get_db),
        current_user=Depends(get_current_user)
):
    """
    프롬프트 상세 조회

    특정 프롬프트의 상세 정보를 조회합니다.
    external MLOps 데이터가 존재하면 로컬 캐시도 함께 보정합니다.

    ## Path Parameters

    | 필드 | 타입 | 설명 |
    |------|------|------|
    | `surro_prompt_id` | integer | 조회할 프롬프트 ID |

    ## Response (200) — `PromptDetailResponse`

    | 필드 | 타입 | 설명 |
    |------|------|------|
    | `id` | integer | 게이트웨이 내부 프롬프트 ID |
    | `surro_prompt_id` | integer | 외부 프롬프트 ID |
    | `created_at` | datetime | 생성 시각 |
    | `updated_at` | datetime | 최종 수정 시각 |
    | `created_by` | string | 생성자 식별자 |
    | `name` | string | 프롬프트 이름 |
    | `description` | string or null | 프롬프트 설명 |
    | `content` | string | 프롬프트 내용 |
    | `prompt_variable` | List[PromptVariableReadSchema] or null | 프롬프트 변수 목록 |

    ## Errors
    - 401: 인증되지 않은 사용자
    - 404: 프롬프트를 찾을 수 없음
    - 500: 서버 내부 오류
    """
    external = await prompt_service.get_prompt(surro_prompt_id, user_info=_user_info(current_user))
    if external is None:
        raise HTTPException(status_code=404, detail="Prompt not found in external service")

    db_prompt = _ensure_prompt_mapping(db, current_user, external)
    return PromptDetailResponse(**_to_prompt_response(db_prompt, external).model_dump())


@router.put("/{surro_prompt_id}", response_model=PromptResponse)
async def update_prompt(
        surro_prompt_id: int,
        prompt_update: PromptUpdate,
        db: Session = Depends(get_db),
        current_user=Depends(get_current_user)
):
    """
    프롬프트 수정

    기존 프롬프트의 정보를 수정합니다.
    external 수정 성공 후 로컬 캐시를 동기화합니다.

    ## Path Parameters

    | 필드 | 타입 | 설명 |
    |------|------|------|
    | `surro_prompt_id` | integer | 수정할 프롬프트 ID |

    ## Request Body (application/json) — `PromptUpdate`

    | 필드 | 타입 | 필수 | 설명 |
    |------|------|------|------|
    | `name` | string | — | 프롬프트 이름 |
    | `description` | string | — | 프롬프트 설명 |
    | `content` | string | — | 프롬프트 내용 |
    | `prompt_variable` | List[string] | — | 프롬프트 변수 이름 목록 |

    ## Response (200) — `PromptResponse`

    | 필드 | 타입 | 설명 |
    |------|------|------|
    | `id` | integer | 게이트웨이 내부 프롬프트 ID |
    | `surro_prompt_id` | integer | 외부 프롬프트 ID |
    | `created_at` | datetime | 생성 시각 |
    | `updated_at` | datetime | 최종 수정 시각 |
    | `created_by` | string | 생성자 식별자 |
    | `name` | string | 프롬프트 이름 |
    | `description` | string or null | 프롬프트 설명 |
    | `content` | string | 프롬프트 내용 |
    | `prompt_variable` | List[PromptVariableReadSchema] or null | 프롬프트 변수 목록 |

    ## Errors
    - 400: 유효하지 않은 요청
    - 401: 인증되지 않은 사용자
    - 404: 프롬프트를 찾을 수 없음
    - 500: 서버 내부 오류
    """
    current_prompt = await prompt_service.get_prompt(surro_prompt_id, user_info=_user_info(current_user))
    if current_prompt is None:
        raise HTTPException(status_code=404, detail="Prompt not found in external service")

    _ensure_prompt_mapping(db, current_user, current_prompt)

    try:
        updated_external = await prompt_service.update_prompt(
            prompt_id=surro_prompt_id,
            name=prompt_update.name,
            description=prompt_update.description,
            content=prompt_update.content,
            prompt_variable=prompt_update.prompt_variable,
            user_info=_user_info(current_user),
        )
        if not updated_external:
            raise HTTPException(status_code=404, detail="Prompt not found in external service")
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to update external prompt %s: %s", surro_prompt_id, e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update external prompt: {e}",
        )

    db_prompt = _ensure_prompt_mapping(db, current_user, updated_external)
    return _to_prompt_response(db_prompt, updated_external)


@router.delete("/{surro_prompt_id}", status_code=204)
async def delete_prompt(
        surro_prompt_id: int,
        db: Session = Depends(get_db),
        current_user=Depends(get_current_user)
):
    """
    프롬프트 삭제

    external 프롬프트를 삭제하고, 로컬 매핑은 soft-delete 처리합니다.

    ## Path Parameters

    | 필드 | 타입 | 설명 |
    |------|------|------|
    | `surro_prompt_id` | integer | 삭제할 프롬프트 ID |

    ## Response
    - 204: 삭제 성공 (응답 본문 없음)

    ## Errors
    - 401: 인증되지 않은 사용자
    - 404: 프롬프트를 찾을 수 없음
    - 500: 서버 내부 오류
    """
    external = await prompt_service.get_prompt(surro_prompt_id, user_info=_user_info(current_user))
    if external is None:
        raise HTTPException(status_code=404, detail="Prompt not found in external service")

    _ensure_prompt_mapping(db, current_user, external)

    try:
        deleted = await prompt_service.delete_prompt(
            surro_prompt_id,
            user_info=_user_info(current_user),
        )
        if not deleted:
            raise HTTPException(status_code=404, detail="Prompt not found in external service")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete external prompt: {e}",
        )

    prompt_crud.delete_prompt_by_surro_id(
        db=db,
        surro_prompt_id=surro_prompt_id,
        deleted_by=current_user.member_id,
    )
    return None
