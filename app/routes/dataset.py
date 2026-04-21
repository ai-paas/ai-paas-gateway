import logging
from typing import List, Optional, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, status, Query, Path, File, UploadFile, Form
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.cruds import dataset_crud
from app.database import get_db
from app.models import Member
from app.schemas.dataset import (
    DatasetCreateRequest, DatasetUpdateRequest, DatasetReadSchema,
    DatasetListWrapper, DatasetWithMemberInfo, InnoUserInfo,
    DatasetValidationResponse
)
from app.services.dataset_service import dataset_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/datasets", tags=["Datasets"])


def _create_inno_user_info(user: Member) -> InnoUserInfo:
    """Member 객체에서 InnoUserInfo 생성"""
    return InnoUserInfo(
        member_id=user.member_id,
        role=user.role,
        name=user.name
    )


def _create_pagination_response(
        data: List[Any],
        total: int,
        page: int,
        size: int
) -> Dict[str, Any]:
    """페이지네이션 응답 생성"""
    return {
        "data": data,
        "total": total,
        "page": page,
        "size": size
    }


@router.get("", response_model=DatasetListWrapper)
async def get_datasets(
        page: int = Query(1, ge=1, description="페이지 번호 (1부터 시작)"),
        size: int = Query(20, ge=1, le=100, description="페이지당 항목 수"),
        db: Session = Depends(get_db),
        current_user: Member = Depends(get_current_user)
):
    """
    데이터셋 목록 조회

    등록된 데이터셋들의 목록을 페이지네이션하여 조회합니다.

    **Query Parameters**
    - **page** (int, 선택): 페이지 번호 (1부터 시작, 기본값: 1, 최소값: 1)
    - **size** (int, 선택): 페이지당 항목 수 (기본값: 20, 범위: 1-100)

    **Response**
    - **data**: 데이터셋 목록, 각 항목은 다음 정보를 포함:
      - id (int): 데이터셋 고유 ID
      - name (str): 데이터셋 이름
      - description (str, optional): 데이터셋에 대한 상세 설명 (없을 수 있음)
      - dataset_registry (DatasetRegistryReadSchema): 데이터셋 레지스트리 정보
        - id (int): 레지스트리 ID
        - artifact_path (str): MLflow에 저장된 데이터셋의 아티팩트 경로
        - uri (str): MLflow에서 접근 가능한 데이터셋 URI
        - dataset_id (int): 연결된 데이터셋 ID
        - created_at (datetime): 생성 시각
        - updated_at (datetime): 수정 시각
      - created_at (datetime): 데이터셋 생성 시각
      - updated_at (datetime): 데이터셋 수정 시각
    - **total** (int): 전체 데이터셋 수
    - **page** (int): 현재 페이지 번호
    - **size** (int): 현재 페이지 크기

    **Notes**
    - page와 size를 모두 생략하면 전체 데이터를 조회합니다.
    - 페이지네이션 사용 시 page와 size를 모두 제공해야 합니다.

    **Errors**
    - 401: 인증되지 않은 사용자
    - 500: 서버 내부 오류
    """
    try:
        skip = (page - 1) * size

        # 1. 사용자의 전체 데이터셋 매핑 조회 ({surro_dataset_id: created_by})
        all_mappings = dataset_crud.get_dataset_mappings_by_member_id(
            db,
            current_user.member_id,
            skip=0,
            limit=10000
        )

        if not all_mappings:
            return _create_pagination_response([], 0, page, size)

        # 2. 외부 API에서 전체 데이터셋 조회 (페이지네이션 없이)
        all_datasets_response = await dataset_service.get_datasets(
            page=None,
            page_size=None,
            user_info={
                'member_id': current_user.member_id,
                'role': current_user.role,
                'name': current_user.name
            }
        )

        # 3. 매핑과 외부 API 교집합으로 실제 사용 가능한 데이터셋 필터링
        available = [d for d in all_datasets_response.data if d.id in all_mappings]
        total = len(available)

        if total == 0:
            return _create_pagination_response([], 0, page, size)

        # 4. 교집합 결과에 대해 페이지네이션 적용
        paginated = available[skip:skip + size]

        # 5. 사용자 정보 추가 + 로컬 DB의 created_by 매핑
        member_info = _create_inno_user_info(current_user)
        wrapped = []
        for dataset in paginated:
            dataset_dict = dataset.model_dump()
            dataset_dict["member_info"] = member_info.model_dump()
            dataset_dict["created_by"] = all_mappings.get(dataset.id, "")
            wrapped.append(DatasetWithMemberInfo(**dataset_dict))

        return _create_pagination_response(wrapped, total, page, size)

    except Exception as e:
        logger.error(f"Error getting datasets for {current_user.member_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get datasets: {str(e)}"
        )


@router.get("/{dataset_id}", response_model=DatasetReadSchema)
async def get_dataset(
        dataset_id: int = Path(..., description="조회할 데이터셋 ID"),
        db: Session = Depends(get_db),
        current_user: Member = Depends(get_current_user)
):
    """
    데이터셋 상세정보 조회

    특정 데이터셋의 상세 정보를 조회합니다.
    데이터셋 레지스트리 정보를 포함하여 반환합니다.

    **Path Parameters**
    - **dataset_id** (int): 조회할 데이터셋 ID

    **Response (DatasetReadSchema)**
    - **id** (int): 데이터셋 고유 ID
    - **name** (str): 데이터셋 이름
    - **description** (str, optional): 데이터셋 설명 (없을 수 있음)
    - **dataset_registry** (DatasetRegistryReadSchema): 데이터셋 레지스트리 정보
      - id (int): 레지스트리 ID
      - artifact_path (str): MLflow에 저장된 데이터셋의 아티팩트 경로
      - uri (str): MLflow에서 접근 가능한 데이터셋 URI
      - dataset_id (int): 연결된 데이터셋 ID
      - created_at (datetime): 생성 시각
      - updated_at (datetime): 수정 시각
    - **created_at** (datetime): 데이터셋 생성 시각
    - **updated_at** (datetime): 데이터셋 수정 시각

    **Errors**
    - 401: 인증되지 않은 사용자
    - 404: 데이터셋을 찾을 수 없음
    - 500: 서버 내부 오류
    """
    try:
        # 1. 사용자가 해당 데이터셋을 소유하고 있는지 확인
        if not dataset_crud.check_dataset_ownership(db, dataset_id, current_user.member_id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Dataset {dataset_id} not found or access denied"
            )

        # 2. 외부 API에서 데이터셋 상세 정보 조회
        dataset = await dataset_service.get_dataset(
            dataset_id=dataset_id,
            user_info={
                'member_id': current_user.member_id,
                'role': current_user.role,
                'name': current_user.name
            }
        )

        if not dataset:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Dataset {dataset_id} not found"
            )

        db_dataset = dataset_crud.get_dataset_by_surro_id(
            db=db,
            surro_dataset_id=dataset_id,
            member_id=current_user.member_id
        )
        if db_dataset:
            dataset.created_by = db_dataset.created_by or ""

        return dataset

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting dataset {dataset_id} for user {current_user.member_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get dataset: {str(e)}"
        )


@router.put("/{dataset_id}", response_model=DatasetReadSchema)
async def update_dataset(
        dataset_id: int = Path(..., description="수정할 데이터셋 ID"),
        dataset_data: DatasetUpdateRequest = None,
        db: Session = Depends(get_db),
        current_user: Member = Depends(get_current_user)
):
    """
    데이터셋 정보 수정

    데이터셋의 이름(name)과 설명(description)을 수정합니다.

    **Path Parameters**
    - **dataset_id** (int): 수정할 데이터셋 ID

    **Request Body (DatasetUpdateSchema)**
    - **name** (str, 선택): 새로운 데이터셋 이름 (수정하지 않으려면 전달하지 않음)
    - **description** (str, 선택): 새로운 데이터셋 설명 (수정하지 않으려면 전달하지 않음)

    **Response (DatasetReadSchema)**
    - **id** (int): 데이터셋 고유 ID
    - **name** (str): 수정된 데이터셋 이름
    - **description** (str, optional): 수정된 데이터셋 설명
      - 데이터셋에 대한 상세 설명 (없을 수 있음)
    - **dataset_registry** (DatasetRegistryReadSchema): 데이터셋 레지스트리 정보
      - id (int): 레지스트리 ID
      - artifact_path (str): MLflow에 저장된 데이터셋의 아티팩트 경로
      - uri (str): MLflow에서 접근 가능한 데이터셋 URI
      - dataset_id (int): 연결된 데이터셋 ID
      - created_at (datetime): 생성 시각
      - updated_at (datetime): 수정 시각
    - **created_at** (datetime): 데이터셋 생성 시각
    - **updated_at** (datetime): 데이터셋 수정 시각

    **Notes**
    - name과 description 중 하나만 수정하거나 둘 다 수정할 수 있습니다
    - 수정하지 않을 필드는 요청에서 생략하면 됩니다

    **Errors**
    - 400: 유효하지 않은 요청
    - 401: 인증되지 않은 사용자
    - 404: 데이터셋을 찾을 수 없음
    - 500: 서버 내부 오류
    """
    try:
        # 1. 소유권 확인
        if not dataset_crud.check_dataset_ownership(db, dataset_id, current_user.member_id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Dataset {dataset_id} not found or access denied"
            )

        # 2. 외부 API에 데이터셋 수정
        updated_dataset = await dataset_service.update_dataset(
            dataset_id=dataset_id,
            dataset_data=dataset_data,
            user_info={
                'member_id': current_user.member_id,
                'role': current_user.role,
                'name': current_user.name
            }
        )

        # 3. 로컬 DB 매핑 이름 동기화
        if dataset_data and dataset_data.name:
            try:
                dataset_crud.update_dataset_cache(
                    db=db,
                    surro_dataset_id=dataset_id,
                    member_id=current_user.member_id,
                    dataset_name=dataset_data.name
                )
                logger.info(
                    f"Updated dataset mapping name: surro_id={dataset_id}, "
                    f"new_name={dataset_data.name}"
                )
            except Exception as cache_error:
                logger.error(f"Failed to update dataset cache: {str(cache_error)}")

        # 4. created_by를 로컬 DB 값으로 설정
        db_dataset = dataset_crud.get_dataset_by_surro_id(
            db=db, surro_dataset_id=dataset_id, member_id=current_user.member_id
        )
        if db_dataset:
            updated_dataset.created_by = db_dataset.created_by or ""

        return updated_dataset

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating dataset {dataset_id} for user {current_user.member_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update dataset: {str(e)}"
        )


@router.delete("/{dataset_id}")
async def delete_dataset(
        dataset_id: int = Path(..., description="삭제할 데이터셋 ID"),
        db: Session = Depends(get_db),
        current_user: Member = Depends(get_current_user)
):
    """
    데이터셋 삭제

    데이터셋을 삭제합니다. MLflow에 저장된 정보와 S3에 저장된 파일도 함께 삭제됩니다.

    **Path Parameters**
    - **dataset_id** (int): 삭제할 데이터셋 ID

    **Response**
    - **success** (bool): 삭제 성공 여부
    - **message** (str): 삭제 결과 메시지

    **Notes**
    - 데이터셋 삭제 시 다음 항목들이 함께 삭제됩니다:
      - 데이터베이스의 데이터셋 레코드
      - 데이터베이스의 데이터셋 레지스트리 레코드
      - MLflow에 저장된 run 및 artifacts
      - S3에 저장된 데이터셋 파일들
    - 삭제 작업은 원자적으로 수행되며, 중간에 실패하면 모든 변경사항이 롤백됩니다
    - 로컬 DB의 사용자-데이터셋 매핑은 소프트 삭제 처리됩니다

    **Errors**
    - 401: 인증되지 않은 사용자
    - 404: 데이터셋을 찾을 수 없음
    - 500: 데이터셋 삭제 중 서버 내부 오류
    """
    try:
        # 1. 소유권 확인
        if not dataset_crud.check_dataset_ownership(db, dataset_id, current_user.member_id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Dataset {dataset_id} not found or access denied"
            )

        # 2. 외부 API에서 데이터셋 삭제
        await dataset_service.delete_dataset(
            dataset_id=dataset_id,
            user_info={
                'member_id': current_user.member_id,
                'role': current_user.role,
                'name': current_user.name
            }
        )

        # 3. 로컬 DB 매핑 소프트 삭제
        try:
            dataset_crud.delete_dataset_mapping(
                db=db,
                surro_dataset_id=dataset_id,
                member_id=current_user.member_id
            )
            logger.info(
                f"Deleted dataset mapping: surro_id={dataset_id}, "
                f"member_id={current_user.member_id}"
            )
        except Exception as mapping_error:
            logger.error(f"Failed to delete dataset mapping: {str(mapping_error)}")

        return {"message": f"Dataset {dataset_id} deleted successfully"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting dataset {dataset_id} for user {current_user.member_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete dataset: {str(e)}"
        )


@router.post("/validate", response_model=DatasetValidationResponse)
async def validate_dataset(
        file: UploadFile = File(..., description="검증할 데이터셋 ZIP 파일. COCO128 형식 구조여야 합니다"),
        current_user: Member = Depends(get_current_user)
):
    """
    데이터셋 파일 유효성 검증

    업로드된 데이터셋 파일의 형식과 구조를 검증합니다.
    COCO128 형식의 데이터셋 구조를 기준으로 검증을 수행합니다.

    **Request Body**
    - **file** (UploadFile, 필수): 검증할 데이터셋 ZIP 파일
      - COCO128 형식의 데이터셋이 ZIP으로 압축된 파일
      - 필수 구조:
        - `annotations/instances_train2017.json`
        - `annotations/instances_val2017.json`
        - `train2017/` (이미지 폴더)
        - `val2017/` (이미지 폴더)

    **Response (DatasetValidationResponse)**
    - **is_valid** (bool): 검증 성공 여부
      - true: 검증 통과
      - false: 검증 실패
    - **message** (str): 검증 결과 메시지
      - 성공 시: "데이터셋 파일이 유효합니다."
      - 실패 시: 오류 원인 설명
    - **details** (dict, optional): 상세 오류 정보
      - 검증 실패 시에만 제공
      - errors (List[str]): 오류 목록

    **Notes**
    - 파일 검증은 실제 데이터셋 등록 전에 수행하는 것을 권장합니다
    - 검증 실패 시 details 필드에서 구체적인 오류 원인을 확인할 수 있습니다
    - ZIP 파일 형식이 아니거나 COCO128 구조를 따르지 않으면 검증이 실패합니다

    **Errors**
    - 400: 파일 형식 오류 또는 데이터셋 구조 검증 실패
    - 401: 인증되지 않은 사용자
    - 500: 서버 내부 오류
    """
    try:
        validation_result = await dataset_service.validate_dataset(
            file=file,
            user_info={
                'member_id': current_user.member_id,
                'role': current_user.role,
                'name': current_user.name
            }
        )

        return validation_result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error validating dataset for user {current_user.member_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to validate dataset: {str(e)}"
        )


@router.post("", response_model=DatasetReadSchema)
async def create_dataset(
        name: str = Form(..., description="데이터셋을 식별하기 위한 이름"),
        description: Optional[str] = Form(None, description="데이터셋에 대한 상세 설명"),
        file: UploadFile = File(..., description="데이터셋 ZIP 파일. COCO128 형식의 데이터셋이 ZIP으로 압축된 파일"),
        db: Session = Depends(get_db),
        current_user: Member = Depends(get_current_user)
):
    """
    데이터셋 등록

    Dataset Registry에 데이터셋을 등록합니다.
    업로드된 파일을 검증하고 MLflow에 등록한 후 데이터베이스에 메타데이터를 저장합니다.

    **Request Body (multipart/form-data)**
    - **name** (str, 필수): 데이터셋을 식별하기 위한 이름 (Form 필드로 전달)
    - **description** (str, 선택): 데이터셋에 대한 상세 설명 (Form 필드로 전달, 생략 가능, 기본값: None)
    - **file** (UploadFile, 필수): 데이터셋 ZIP 파일
      - COCO128 형식의 데이터셋이 ZIP으로 압축된 파일 (최대 1GB)
      - 파일 검증은 `/datasets/validate` API를 먼저 호출하여 수행하는 것을 권장합니다

    **Response (DatasetReadSchema)**
    - **id** (int): 데이터셋 고유 ID
    - **name** (str): 데이터셋 이름
    - **description** (str, optional): 데이터셋 설명 (없을 수 있음)
    - **dataset_registry** (DatasetRegistryReadSchema): 데이터셋 레지스트리 정보
      - id (int): 레지스트리 ID
      - artifact_path (str): MLflow에 저장된 데이터셋의 아티팩트 경로
      - uri (str): MLflow에서 접근 가능한 데이터셋 URI
      - dataset_id (int): 연결된 데이터셋 ID
      - created_at (datetime): 생성 시각
      - updated_at (datetime): 수정 시각
    - **created_at** (datetime): 데이터셋 생성 시각
    - **updated_at** (datetime): 데이터셋 수정 시각

    **Notes**
    - 파일 검증은 `/datasets/validate` API를 먼저 호출하여 수행하는 것을 권장합니다
    - 데이터셋은 MLflow에 자동으로 등록되며, artifact_path와 uri가 생성됩니다
    - 등록된 데이터셋은 실험(Experiment) 생성 시 사용할 수 있습니다

    **Errors**
    - 400: 데이터셋 검증 실패 또는 유효하지 않은 요청
    - 401: 인증되지 않은 사용자
    - 500: 데이터셋 등록 중 서버 내부 오류
    """
    try:
        # 데이터셋 생성 요청 데이터 구성
        dataset_data = DatasetCreateRequest(
            name=name,
            description=description
        )

        # 1. 외부 API를 통해 데이터셋 생성
        created_dataset = await dataset_service.create_dataset(
            dataset_data=dataset_data,
            file=file,
            user_info={
                'member_id': current_user.member_id,
                'role': current_user.role,
                'name': current_user.name
            }
        )

        # 2. Inno DB에 사용자-데이터셋 매핑 저장
        try:
            dataset_crud.create_dataset_mapping(
                db=db,
                surro_dataset_id=created_dataset.id,
                member_id=current_user.member_id,
                dataset_name=created_dataset.name
            )
            logger.info(
                f"Created dataset mapping: surro_id={created_dataset.id}, "
                f"member_id={current_user.member_id}"
            )
        except Exception as mapping_error:
            logger.error(f"Failed to create dataset mapping: {str(mapping_error)}")
            # 매핑 저장에 실패해도 외부 API에는 이미 생성되었으므로, 경고만 로그
            logger.warning(
                f"Dataset {created_dataset.id} created in external API but mapping failed"
            )

        return created_dataset

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating dataset for user {current_user.member_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create dataset: {str(e)}"
        )
