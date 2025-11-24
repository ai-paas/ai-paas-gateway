from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from typing import Optional
from app.database import get_db
from app.models.prompt import Prompt  # 마이그레이션용 import 추가
from app.cruds.prompt import prompt_crud
from app.auth import get_current_user, get_current_admin_user
from app.schemas.prompt import (
    PromptCreate,
    PromptUpdate,
    PromptResponse,
    PromptDetailResponse,
    PromptListResponse,
    PromptVariableTypeListSchema
)
from app.services.prompt_service import prompt_service
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/prompts", tags=["prompts"])


@router.get("/variable-types", response_model=PromptVariableTypeListSchema)
async def get_variable_types(
        current_user=Depends(get_current_user)
):
    """프롬프트 변수 가능한 타입 목록 조회"""
    user_info = {
        'member_id': current_user.member_id,
        'role': current_user.role,
        'name': current_user.name
    }

    variable_types = await prompt_service.get_variable_types(user_info)
    return variable_types


@router.post("/", response_model=PromptResponse)
async def create_prompt(
        prompt: PromptCreate,
        db: Session = Depends(get_db),
        current_user=Depends(get_current_user)
):
    """프롬프트 생성"""
    user_info = {
        'member_id': current_user.member_id,
        'role': current_user.role,
        'name': current_user.name
    }

    # 외부 API 호출
    external_prompt = await prompt_service.create_prompt(
        name=prompt.prompt.name,
        content=prompt.prompt.content,
        description=prompt.prompt.description,
        prompt_variable=prompt.prompt_variable,
        user_info=user_info
    )

    # 우리 DB에 저장 (외부 API 응답의 prompt_variable 포함)
    try:
        db_prompt = prompt_crud.create_prompt(
            db=db,
            prompt=prompt,
            created_by=current_user.member_id,
            surro_prompt_id=external_prompt.id,
            external_prompt_variables=external_prompt.prompt_variable  # 외부 API 응답 전달
        )
        logger.info(
            f"Created prompt: surro_id={external_prompt.id}, "
            f"member_id={current_user.member_id}"
        )
    except Exception as mapping_error:
        logger.error(f"Failed to create prompt: {str(mapping_error)}")
        logger.warning(f"Prompt {external_prompt.id} created in external API but DB save failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Prompt created in external API but failed to save: {str(mapping_error)}"
        )

    # 응답: DB 메타정보 + 외부 API 데이터 (상세 정보)
    return PromptResponse(
        id=db_prompt.id,
        surro_prompt_id=db_prompt.surro_prompt_id,
        created_at=db_prompt.created_at,
        updated_at=db_prompt.updated_at,
        created_by=db_prompt.created_by,
        name=external_prompt.name,
        description=external_prompt.description,
        content=external_prompt.content,
        prompt_variable=external_prompt.prompt_variable
    )

@router.get("/", response_model=PromptListResponse)
async def get_prompts(
        page: Optional[int] = Query(None, ge=1, description="페이지 번호 (1부터 시작)"),
        size: Optional[int] = Query(None, ge=1, le=1000, description="페이지당 항목 수"),
        search: Optional[str] = Query(None, description="검색어 (이름, 설명, 내용)"),
        db: Session = Depends(get_db),
        current_user=Depends(get_current_user)
):
    """프롬프트 목록 조회 (우리 DB 기준)

    - **page**: 페이지 번호 (선택)
    - **size**: 페이지당 항목 수 (선택)
    - **search**: 검색어 (선택)

    페이지네이션을 사용하려면 page와 size를 모두 제공해야 합니다.
    생략 시 전체 데이터를 조회합니다 (최대 10000개).
    """
    skip = None
    limit = None

    # page와 size가 모두 있을 때만 페이지네이션 적용
    if page is not None and size is not None:
        skip = (page - 1) * size
        limit = size

    # DB에서 조회 (실제 데이터 포함)
    prompts, total = prompt_crud.get_prompts(
        db=db,
        skip=skip,
        limit=limit,
        search=search
    )

    # prompt_variable 정규화
    response_data = []
    for db_prompt in prompts:
        # prompt_variable 처리
        prompt_vars = None
        if db_prompt.prompt_variable:
            # JSON 데이터가 문자열 리스트인 경우
            if isinstance(db_prompt.prompt_variable, list):
                # 문자열 리스트는 None으로 처리하거나 빈 리스트로 처리
                # (PromptVariableReadSchema는 id, name, prompt_id가 필요하므로)
                prompt_vars = None
            # 딕셔너리 리스트인 경우 (외부 API 응답 형식)
            elif isinstance(db_prompt.prompt_variable, list) and len(db_prompt.prompt_variable) > 0:
                if isinstance(db_prompt.prompt_variable[0], dict):
                    from app.schemas.prompt import PromptVariableReadSchema
                    prompt_vars = [PromptVariableReadSchema(**var) for var in db_prompt.prompt_variable]

        response_data.append(PromptResponse(
            id=db_prompt.id,
            surro_prompt_id=db_prompt.surro_prompt_id,
            created_at=db_prompt.created_at,
            updated_at=db_prompt.updated_at,
            created_by=db_prompt.created_by,
            name=db_prompt.name,
            description=db_prompt.description,
            content=db_prompt.content,
            prompt_variable=prompt_vars  # None 또는 PromptVariableReadSchema 리스트
        ))

    return PromptListResponse(
        data=response_data,
        total=total,
        page=page,
        size=size
    )


@router.get("/{surro_prompt_id}", response_model=PromptDetailResponse)
async def get_prompt(
        surro_prompt_id: int,
        db: Session = Depends(get_db),
        current_user=Depends(get_current_user)
):
    """프롬프트 상세 정보 조회 (우리 DB 기준)"""
    # DB에서 조회
    db_prompt = prompt_crud.get_prompt_by_surro_id(db=db, surro_prompt_id=surro_prompt_id)
    if not db_prompt:
        raise HTTPException(status_code=404, detail="Prompt not found")

    # prompt_variable 정규화
    prompt_vars = db_prompt.prompt_variable
    if prompt_vars and isinstance(prompt_vars, list):
        if len(prompt_vars) > 0 and isinstance(prompt_vars[0], dict):
            # 딕셔너리 리스트를 PromptVariableReadSchema로 변환
            from app.schemas.prompt import PromptVariableReadSchema
            prompt_vars = [PromptVariableReadSchema(**var) if isinstance(var, dict) else var
                           for var in prompt_vars]

    # 응답 생성
    response = PromptDetailResponse(
        id=db_prompt.id,
        surro_prompt_id=db_prompt.surro_prompt_id,
        created_at=db_prompt.created_at,
        updated_at=db_prompt.updated_at,
        created_by=db_prompt.created_by,
        name=db_prompt.name,
        description=db_prompt.description,
        content=db_prompt.content,
        prompt_variable=prompt_vars
    )

    return response


@router.put("/{surro_prompt_id}", response_model=PromptResponse)
async def update_prompt(
        surro_prompt_id: int,
        prompt_update: PromptUpdate,
        db: Session = Depends(get_db),
        current_user=Depends(get_current_user)
):
    """프롬프트 정보 수정 (외부 API만 수정)

    - **surro_prompt_id**: 외부 API의 프롬프트 ID
    """
    # UUID로 우리 DB에서 기존 프롬프트 조회 (권한 확인용)
    existing_prompt = prompt_crud.get_prompt_by_surro_id(db=db, surro_prompt_id=surro_prompt_id)
    if not existing_prompt:
        raise HTTPException(status_code=404, detail="Prompt not found")

    # 권한 확인
    if current_user.role != "admin" and existing_prompt.created_by != current_user.member_id:
        raise HTTPException(status_code=403, detail="Permission denied")

    # 외부 API 업데이트
    user_info = {
        'member_id': current_user.member_id,
        'role': current_user.role,
        'name': current_user.name
    }

    try:
        # 기존 prompt 조회하여 현재 prompt_variable 확인
        current_prompt = await prompt_service.get_prompt(surro_prompt_id, user_info)

        logger.info(f"Current prompt_variable: {current_prompt.prompt_variable if current_prompt else None}")
        logger.info(f"Update request prompt_variable: {prompt_update.prompt_variable}")

        # prompt_variable 처리
        # 1. 업데이트 요청에 prompt_variable이 없으면 기존 값 유지 (None 전달)
        # 2. 있으면 해당 값 전달
        # 3. 빈 리스트면 빈 리스트 전달 (변수 제거)
        prompt_variable_to_send = prompt_update.prompt_variable

        logger.info(f"Sending prompt_variable: {prompt_variable_to_send}")

        updated_external = await prompt_service.update_prompt(
            prompt_id=surro_prompt_id,
            name=prompt_update.name,
            description=prompt_update.description,
            content=prompt_update.content,
            prompt_variable=prompt_variable_to_send,
            user_info=user_info
        )

        if not updated_external:
            raise HTTPException(status_code=404, detail="Prompt not found in external service")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update external prompt: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to update external prompt: {str(e)}"
        )

    # 외부 API에서 최신 데이터 다시 조회하여 DB 업데이트
    try:
        latest_external = await prompt_service.get_prompt(
            surro_prompt_id,
            user_info
        )

        if latest_external:
            # DB의 실제 데이터 업데이트
            existing_prompt.name = latest_external.name
            existing_prompt.description = latest_external.description
            existing_prompt.content = latest_external.content

            # prompt_variable도 외부 API 응답으로 업데이트
            if latest_external.prompt_variable:
                existing_prompt.prompt_variable = [
                    {
                        "id": var.id,
                        "name": var.name,
                        "prompt_id": var.prompt_id
                    }
                    for var in latest_external.prompt_variable
                ]
            else:
                existing_prompt.prompt_variable = None

            db.commit()
            db.refresh(existing_prompt)
    except Exception as e:
        logger.error(f"Failed to sync DB with external API: {str(e)}")

    # 응답: DB 메타정보 + 외부 API 업데이트된 데이터
    return PromptResponse(
        id=existing_prompt.id,
        surro_prompt_id=existing_prompt.surro_prompt_id,
        created_at=existing_prompt.created_at,
        updated_at=existing_prompt.updated_at,
        created_by=existing_prompt.created_by,
        name=updated_external.name,
        description=updated_external.description,
        content=updated_external.content,
        prompt_variable=updated_external.prompt_variable
    )


@router.delete("/{surro_prompt_id}", status_code=204)
async def delete_prompt(
        surro_prompt_id: int,
        db: Session = Depends(get_db),
        current_user=Depends(get_current_user)
):
    """프롬프트 삭제

    - **surro_prompt_id**: 외부 API의 프롬프트 ID
    """
    # 외부 ID로 우리 DB에서 기존 프롬프트 조회
    existing_prompt = prompt_crud.get_prompt_by_surro_id(db=db, surro_prompt_id=surro_prompt_id)
    if not existing_prompt:
        raise HTTPException(status_code=404, detail="Prompt not found")

    # 권한 확인
    if current_user.role != "admin" and existing_prompt.created_by != current_user.member_id:
        raise HTTPException(status_code=403, detail="Permission denied")

    # 외부 API 삭제
    user_info = {
        'member_id': current_user.member_id,
        'role': current_user.role,
        'name': current_user.name
    }

    try:
        await prompt_service.delete_prompt(
            surro_prompt_id,
            user_info
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to delete external prompt: {str(e)}"
        )

    # 우리 DB 삭제
    success = prompt_crud.delete_prompt_by_surro_id(db=db, surro_prompt_id=surro_prompt_id)
    if not success:
        raise HTTPException(status_code=404, detail="Prompt not found")

    return None  # 204 No Content