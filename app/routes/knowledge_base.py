import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.common.sort import parse_sort, resolve_sort_columns
from app.cruds.knowledge_base import knowledge_base_crud
from app.database import get_db
from app.models.knowledge_base import KnowledgeBase
from app.schemas.knowledge_base import (
    ChunkTypeListResponse,
    KnowledgeBaseDetailResponse,
    KnowledgeBaseListResponse,
    KnowledgeBaseResponse,
    KnowledgeBaseSearchRecord,
    KnowledgeBaseSearchRequest,
    KnowledgeBaseSearchResponse,
    KnowledgeBaseUpdate,
    LanguageListResponse,
    SearchMethodListResponse,
)
from app.services.knowledge_base_service import knowledge_base_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/knowledge-bases", tags=["Knowledge Bases"])

_KB_SORT_FIELDS = {
    "id": KnowledgeBase.id,
    "name": KnowledgeBase.name,
    "collection_name": KnowledgeBase.collection_name,
    "created_at": KnowledgeBase.created_at,
    "updated_at": KnowledgeBase.updated_at,
}
_KB_SORT_DEFAULT = [(KnowledgeBase.created_at, True)]
_KB_SORT_TIE_BREAKER = KnowledgeBase.id

CHUNK_TYPES_DESCRIPTION = """
청크 타입 목록 조회

사용 가능한 모든 청크 타입 목록을 조회합니다.

## Response
- **data** (List[ChunkTypeReadSchema]): 청크 타입 목록
    - id (int): 청크 타입 ID
    - name (str): 청크 타입 이름 (예: "RecursiveTextSplitter", "RecursiveCharacterSplitter")
    - description (str, optional): 청크 타입 설명
- **total** (int): 전체 항목 수
- **page** (int): 현재 페이지 번호
- **size** (int): 페이지당 항목 수

## Errors
- 401: 인증되지 않은 사용자
- 500: 서버 내부 오류
"""

LANGUAGES_DESCRIPTION = """
언어 목록 조회

사용 가능한 모든 언어 목록을 조회합니다.

## Response
- **data** (List[LanguageReadSchema]): 언어 목록
    - id (int): 언어 ID
    - name (str): 언어 코드 (예: "KO", "EN")
    - description (str, optional): 언어 설명 (예: "한국어", "영어")
- **total** (int): 전체 항목 수
- **page** (int): 현재 페이지 번호
- **size** (int): 페이지당 항목 수

## Errors
- 401: 인증되지 않은 사용자
- 500: 서버 내부 오류
"""

SEARCH_METHODS_DESCRIPTION = """
검색 방법 목록 조회

사용 가능한 모든 검색 방법 목록을 조회합니다.

## Response
- **data** (List[SearchMethodReadSchema]): 검색 방법 목록
    - id (int): 검색 방법 ID
    - name (str): 검색 방법 이름 (예: "vector")
    - description (str, optional): 검색 방법 설명
- **total** (int): 전체 항목 수
- **page** (int): 현재 페이지 번호
- **size** (int): 페이지당 항목 수

## Errors
- 401: 인증되지 않은 사용자
- 500: 서버 내부 오류
"""

CREATE_KNOWLEDGE_BASE_DESCRIPTION = """
Knowledge Base 생성

문서 파일을 업로드하여 Knowledge Base를 생성합니다.
파일은 청크로 분할되고 임베딩되어 Milvus에 저장됩니다.

## Request Body (multipart/form-data)
- **name** (str, required): Knowledge Base 이름
- **description** (str, optional): Knowledge Base 설명
- **language_id** (int, required): 언어 ID
    - `GET /api/v1/knowledge-bases/languages` API로 조회 가능
- **embedding_model_id** (int, required): 임베딩 모델 ID
    - `GET /api/v1/models?model_type_id={embedding_type_id}` API로 조회 가능
- **chunk_size** (int, required): 청크 크기
- **chunk_overlap** (int, required): 청크 오버랩 크기
- **chunk_type_id** (int, required): 청크 타입 ID
    - `GET /api/v1/knowledge-bases/chunk-types` API로 조회 가능
- **search_method_id** (int, required): 검색 방법 ID
    - `GET /api/v1/knowledge-bases/search-methods` API로 조회 가능
- **top_k** (int, required): 검색 시 반환할 상위 k개 결과 수
- **threshold** (float, required): 검색 임계값 (0.0 ~ 1.0)
- **file** (UploadFile, required): 업로드할 문서 파일
    - **지원 파일 타입**:
      - PDF: `.pdf`
      - Word: `.doc`, `.docx`
      - Excel: `.xls`, `.xlsx`
      - PowerPoint: `.ppt`, `.pptx`
      - CSV: `.csv`
    - 지원되지 않는 파일 타입 업로드 시 400 오류 발생

## Response (KnowledgeBaseReadSchema)
- **id** (int): Gateway Knowledge Base ID
- **surro_knowledge_id** (int): 외부 Knowledge Base ID
- **name** (str): Knowledge Base 이름
- **description** (str, optional): Knowledge Base 설명
- **collection_name** (str): Milvus Collection 이름
- 기타 필드들...

## Errors
- 400: 유효하지 않은 요청 또는 필수 파라미터 누락
- 401: 인증되지 않은 사용자
- 500: Knowledge Base 생성 중 서버 내부 오류
"""

LIST_KNOWLEDGE_BASES_DESCRIPTION = """
Knowledge Base 목록 조회

등록된 Knowledge Base 목록을 페이지네이션하여 조회합니다.

## Query Parameters
- **page** (int, optional): 페이지 번호 (1부터 시작)
    - 기본값: 1
    - 최소값: 1
- **size** (int, optional): 페이지당 항목 수
    - 기본값: 10
    - 범위: 1-1000
- **search** (str, optional): 검색어 (이름, 설명, collection_name)
- **sort** (str, optional): 정렬 기준
    - 기본값: `-created_at`
    - 허용 필드: `id`, `name`, `collection_name`, `created_at`, `updated_at`
    - `,`로 다중 정렬 가능, `-` 접두어는 내림차순

## Response (KnowledgeBaseListResponse)
- **data** (List[KnowledgeBaseBriefReadSchema]): Knowledge Base 목록
- **total** (int): 전체 항목 수
- **page** (int): 현재 페이지 번호
- **size** (int): 페이지당 항목 수

## Errors
- 401: 인증되지 않은 사용자
- 500: 서버 내부 오류
"""

GET_KNOWLEDGE_BASE_DESCRIPTION = """
Knowledge Base 상세 조회

특정 Knowledge Base의 상세 정보를 조회합니다.

## Path Parameters
- **knowledge_base_id** (int): 조회할 Knowledge Base ID

## Response (KnowledgeBaseReadSchema)
- Knowledge Base 상세 정보 및 파일 목록

## Errors
- 401: 인증되지 않은 사용자
- 404: Knowledge Base를 찾을 수 없음
- 500: 서버 내부 오류
"""

UPDATE_KNOWLEDGE_BASE_DESCRIPTION = """
Knowledge Base 수정

Knowledge Base의 이름과 설명만 수정할 수 있습니다.

## Path Parameters
- **knowledge_base_id** (int): 수정할 Knowledge Base ID

## Request Body
- **name** (str, optional): 수정할 이름
- **description** (str, optional): 수정할 설명

## Response (KnowledgeBaseReadSchema)
- 수정된 Knowledge Base 정보

## Errors
- 400: 유효하지 않은 요청 또는 수정할 데이터 없음
- 401: 인증되지 않은 사용자
- 404: Knowledge Base를 찾을 수 없음
- 500: 수정 중 서버 내부 오류
"""

DELETE_KNOWLEDGE_BASE_DESCRIPTION = """
Knowledge Base 삭제

Knowledge Base를 삭제합니다.
DB에서 Knowledge Base 정보를 삭제하고, Milvus에서 Collection을 삭제합니다.

## Path Parameters
- **knowledge_base_id** (int): 삭제할 Knowledge Base ID

## Errors
- 401: 인증되지 않은 사용자
- 404: Knowledge Base를 찾을 수 없음
- 500: 삭제 중 서버 내부 오류
"""

ADD_FILE_DESCRIPTION = """
Knowledge Base에 파일 추가

기존 Knowledge Base에 문서 파일을 추가합니다.
파일은 청크로 분할되고 임베딩되어 Milvus의 동일한 Collection에 Partition으로 추가됩니다.

## Path Parameters
- **knowledge_base_id** (int): Knowledge Base ID

## Request Body (multipart/form-data)
- **file** (UploadFile, required): 추가할 문서 파일

## Response (KnowledgeBaseReadSchema)
- 업데이트된 Knowledge Base 정보

## Errors
- 400: 유효하지 않은 요청 또는 파일 처리 실패
- 401: 인증되지 않은 사용자
- 404: Knowledge Base를 찾을 수 없음
- 500: 파일 추가 중 서버 내부 오류
"""

DELETE_FILE_DESCRIPTION = """
Knowledge Base에서 파일 삭제

Knowledge Base에서 특정 파일을 삭제합니다.
DB에서 파일 정보를 삭제하고, Milvus에서 해당 Partition을 삭제합니다.

## Path Parameters
- **knowledge_base_id** (int): Knowledge Base ID
- **file_id** (int): 삭제할 파일 ID

## Response (KnowledgeBaseReadSchema)
- 업데이트된 Knowledge Base 정보

## Errors
- 400: 유효하지 않은 요청
- 401: 인증되지 않은 사용자
- 404: Knowledge Base 또는 파일을 찾을 수 없음
- 500: 파일 삭제 중 서버 내부 오류
"""

SEARCH_KNOWLEDGE_BASE_DESCRIPTION = """
Knowledge Base 검색 테스트

Knowledge Base에 저장된 문서를 검색합니다.
Knowledge Base의 설정된 검색 방법(search_method), top_k, threshold를 사용하여 검색을 수행합니다.

## Path Parameters
- **knowledge_base_id** (int): 검색할 Knowledge Base ID

## Request Body
- **text** (str, required): 검색할 쿼리 텍스트

## Response (KnowledgeBaseSearchResponseSchema)
- **results** (List[SearchResultItemSchema]): 검색 결과 목록
    - **text** (str): 검색된 문서 텍스트
    - **score** (float): 검색 점수 (유사도)
    - **distance** (float, optional): 거리 값
- **total** (int): 검색 결과 총 개수
- **search_method** (str): 사용된 검색 방법 (dense/sparse/hybrid)

## Errors
- 400: 유효하지 않은 요청 또는 Knowledge Base를 찾을 수 없음
- 401: 인증되지 않은 사용자
- 404: Knowledge Base를 찾을 수 없음
- 500: 검색 중 서버 내부 오류
"""

SEARCH_RECORDS_DESCRIPTION = """
Knowledge Base 검색 기록 조회

특정 Knowledge Base에 대한 검색 기록을 조회합니다.

## Path Parameters
- **knowledge_base_id** (int): 조회할 Knowledge Base ID

## Response (List[KnowledgeBaseSearchRecordReadSchema])
- **id** (int): 검색 기록 ID
- **knowledge_base_id** (int): Knowledge Base ID
- **source** (str): Collection 이름
- **text** (str): 검색 쿼리 텍스트
- **created_at** (datetime): 검색 기록 생성 시간

## Errors
- 401: 인증되지 않은 사용자
- 404: Knowledge Base를 찾을 수 없음
- 500: 서버 내부 오류
"""


def _user_info(current_user) -> dict:
    return {
        "member_id": current_user.member_id,
        "role": current_user.role,
        "name": current_user.name,
    }


@router.get(
    "/chunk-types",
    response_model=ChunkTypeListResponse,
    summary="Get Chunk Types",
    description=CHUNK_TYPES_DESCRIPTION,
)
async def get_chunk_types(
    page: int = Query(1, ge=1, description="페이지 번호 (기본값: 1)"),
    size: int = Query(100, ge=1, le=1000, description="페이지당 항목 수 (기본값: 100)"),
    current_user=Depends(get_current_user),
):
    """청크 타입 목록 조회 (페이징)"""
    all_chunk_types = await knowledge_base_service.get_chunk_types(_user_info(current_user))

    total = len(all_chunk_types)
    start = (page - 1) * size
    end = start + size
    chunk_types = all_chunk_types[start:end]

    return ChunkTypeListResponse(data=chunk_types, total=total, page=page, size=size)


@router.get(
    "/languages",
    response_model=LanguageListResponse,
    summary="Get Languages",
    description=LANGUAGES_DESCRIPTION,
)
async def get_languages(
    page: int = Query(1, ge=1, description="페이지 번호 (기본값: 1)"),
    size: int = Query(100, ge=1, le=1000, description="페이지당 항목 수 (기본값: 100)"),
    current_user=Depends(get_current_user),
):
    """언어 목록 조회 (페이징)"""
    all_languages = await knowledge_base_service.get_languages(_user_info(current_user))

    total = len(all_languages)
    start = (page - 1) * size
    end = start + size
    languages = all_languages[start:end]

    return LanguageListResponse(data=languages, total=total, page=page, size=size)


@router.get(
    "/search-methods",
    response_model=SearchMethodListResponse,
    summary="Get Search Methods",
    description=SEARCH_METHODS_DESCRIPTION,
)
async def get_search_methods(
    page: int = Query(1, ge=1, description="페이지 번호 (기본값: 1)"),
    size: int = Query(100, ge=1, le=1000, description="페이지당 항목 수 (기본값: 100)"),
    current_user=Depends(get_current_user),
):
    """검색 방법 목록 조회 (페이징)"""
    all_search_methods = await knowledge_base_service.get_search_methods(_user_info(current_user))

    total = len(all_search_methods)
    start = (page - 1) * size
    end = start + size
    search_methods = all_search_methods[start:end]

    return SearchMethodListResponse(data=search_methods, total=total, page=page, size=size)


@router.post(
    "",
    response_model=KnowledgeBaseResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create Knowledge Base",
    description=CREATE_KNOWLEDGE_BASE_DESCRIPTION,
)
async def create_knowledge_base(
    name: str = Form(..., description="Knowledge Base 이름"),
    description: Optional[str] = Form(None, description="Knowledge Base 설명"),
    language_id: int = Form(..., description="언어 ID"),
    embedding_model_id: int = Form(..., description="임베딩 모델 ID"),
    chunk_size: int = Form(..., description="청크 크기"),
    chunk_overlap: int = Form(..., description="청크 오버랩 크기"),
    chunk_type_id: int = Form(..., description="청크 타입 ID"),
    search_method_id: int = Form(..., description="검색 방법 ID"),
    top_k: int = Form(..., description="검색 시 반환할 상위 k개 결과 수"),
    threshold: float = Form(..., ge=0.0, le=1.0, description="검색 임계값 (0.0 ~ 1.0)"),
    file: UploadFile = File(..., description="업로드할 문서 파일"),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """지식베이스 생성 (파일 업로드)"""
    user_info = _user_info(current_user)

    external_kb = await knowledge_base_service.create_knowledge_base(
        name=name,
        description=description,
        file=file,
        language_id=language_id,
        embedding_model_id=embedding_model_id,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        chunk_type_id=chunk_type_id,
        search_method_id=search_method_id,
        top_k=top_k,
        threshold=threshold,
        user_info=user_info,
    )

    try:
        db_kb = knowledge_base_crud.create_knowledge_base(
            db=db,
            name=external_kb.name,
            description=external_kb.description,
            created_by=current_user.member_id,
            surro_knowledge_id=external_kb.id,
            collection_name=external_kb.collection_name,
        )
        logger.info(
            f"Created knowledge base: surro_id={external_kb.id}, "
            f"member_id={current_user.member_id}"
        )
    except Exception as mapping_error:
        logger.error(f"Failed to create knowledge base: {str(mapping_error)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Knowledge base created in external API but failed to save: {str(mapping_error)}",
        )

    return KnowledgeBaseResponse(
        id=db_kb.id,
        surro_knowledge_id=db_kb.surro_knowledge_id,
        created_at=db_kb.created_at,
        updated_at=db_kb.updated_at,
        created_by=db_kb.created_by,
        name=db_kb.name,
        description=db_kb.description,
        collection_name=db_kb.collection_name,
        chunk_size=external_kb.chunk_size,
        chunk_overlap=external_kb.chunk_overlap,
        top_k=external_kb.top_k,
        threshold=external_kb.threshold,
    )


@router.get(
    "",
    response_model=KnowledgeBaseListResponse,
    summary="Get Knowledge Bases",
    description=LIST_KNOWLEDGE_BASES_DESCRIPTION,
)
async def get_knowledge_bases(
    page: int = Query(1, ge=1, description="페이지 번호 (기본값: 1)"),
    size: int = Query(10, ge=1, le=1000, description="페이지당 항목 수 (기본값: 10)"),
    search: Optional[str] = Query(None, description="검색어 (이름, 설명, collection_name)"),
    sort: Optional[str] = Query(
        None,
        description=(
            "정렬 기준. `,`로 다중 정렬 가능, `-` 접두어는 내림차순(DESC). "
            "미지정 시 `-created_at`. 허용 필드: "
            "`id`, `name`, `collection_name`, `created_at`, `updated_at`."
        ),
        openapi_examples={
            "default": {"summary": "최신순(기본)", "value": "-created_at"},
            "name_asc": {"summary": "이름 오름차순", "value": "name"},
            "name_desc": {"summary": "이름 내림차순", "value": "-name"},
            "collection": {"summary": "collection 이름 ASC + 최신순", "value": "collection_name,-created_at"},
        },
    ),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """지식베이스 목록 조회 (페이징)"""
    skip = (page - 1) * size
    limit = size

    order_by = resolve_sort_columns(
        parsed=parse_sort(sort),
        allowed=_KB_SORT_FIELDS,
        default=_KB_SORT_DEFAULT,
        tie_breaker=_KB_SORT_TIE_BREAKER,
    )

    knowledge_bases, total = knowledge_base_crud.get_knowledge_bases(
        db=db,
        skip=skip,
        limit=limit,
        search=search,
        member_id=current_user.member_id,
        order_by=order_by,
    )

    try:
        external_kbs = await knowledge_base_service.get_knowledge_bases(user_info=_user_info(current_user))
        external_kb_map = {kb.id: kb for kb in external_kbs}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to fetch external knowledge bases: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to fetch knowledge base data from external API: {str(e)}",
        )

    response_data = []
    for kb in knowledge_bases:
        external_kb = external_kb_map.get(kb.surro_knowledge_id)
        response_data.append(
            KnowledgeBaseResponse(
                id=kb.id,
                surro_knowledge_id=kb.surro_knowledge_id,
                created_at=kb.created_at,
                updated_at=kb.updated_at,
                created_by=kb.created_by,
                name=kb.name,
                description=kb.description,
                collection_name=kb.collection_name,
                chunk_size=external_kb.chunk_size if external_kb else None,
                chunk_overlap=external_kb.chunk_overlap if external_kb else None,
                top_k=external_kb.top_k if external_kb else None,
                threshold=external_kb.threshold if external_kb else None,
            )
        )

    return KnowledgeBaseListResponse(data=response_data, total=total, page=page, size=size)


@router.get(
    "/{knowledge_base_id}",
    response_model=KnowledgeBaseDetailResponse,
    summary="Get Knowledge Base",
    description=GET_KNOWLEDGE_BASE_DESCRIPTION,
)
async def get_knowledge_base(
    knowledge_base_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """지식베이스 상세 정보 조회"""
    surro_knowledge_id = knowledge_base_id
    db_kb = knowledge_base_crud.get_active_knowledge_base_by_surro_id(
        db=db,
        surro_knowledge_id=surro_knowledge_id,
    )
    if not db_kb:
        raise HTTPException(status_code=404, detail="Knowledge base not found")

    if current_user.role != "admin" and db_kb.created_by != current_user.member_id:
        raise HTTPException(status_code=403, detail="Permission denied")

    external_kb = await knowledge_base_service.get_knowledge_base(surro_knowledge_id, _user_info(current_user))
    if not external_kb:
        raise HTTPException(status_code=404, detail="Knowledge base not found in external service")

    return KnowledgeBaseDetailResponse(
        id=db_kb.id,
        surro_knowledge_id=db_kb.surro_knowledge_id,
        created_at=db_kb.created_at,
        updated_at=db_kb.updated_at,
        created_by=db_kb.created_by,
        name=external_kb.name,
        description=external_kb.description,
        collection_name=external_kb.collection_name,
        embedding_model_id=external_kb.embedding_model_id,
        language_id=external_kb.language_id,
        chunk_size=external_kb.chunk_size,
        chunk_overlap=external_kb.chunk_overlap,
        chunk_type_id=external_kb.chunk_type_id,
        search_method_id=external_kb.search_method_id,
        top_k=external_kb.top_k,
        threshold=external_kb.threshold,
        files=external_kb.files,
    )


@router.put(
    "/{knowledge_base_id}",
    response_model=KnowledgeBaseResponse,
    summary="Update Knowledge Base",
    description=UPDATE_KNOWLEDGE_BASE_DESCRIPTION,
)
async def update_knowledge_base(
    knowledge_base_id: int,
    knowledge_base_update: KnowledgeBaseUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """지식베이스 정보 수정"""
    surro_knowledge_id = knowledge_base_id
    existing_kb = knowledge_base_crud.get_active_knowledge_base_by_surro_id(
        db=db,
        surro_knowledge_id=surro_knowledge_id,
    )
    if not existing_kb:
        raise HTTPException(status_code=404, detail="Knowledge base not found")

    if current_user.role != "admin" and existing_kb.created_by != current_user.member_id:
        raise HTTPException(status_code=403, detail="Permission denied")

    try:
        updated_external = await knowledge_base_service.update_knowledge_base(
            knowledge_base_id=surro_knowledge_id,
            name=knowledge_base_update.name,
            description=knowledge_base_update.description,
            user_info=_user_info(current_user),
        )
        if not updated_external:
            raise HTTPException(status_code=404, detail="Knowledge base not found in external service")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update external knowledge base: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to update external knowledge base: {str(e)}")

    try:
        knowledge_base_crud.update_knowledge_base_by_surro_id(
            db=db,
            surro_knowledge_id=surro_knowledge_id,
            name=updated_external.name,
            description=updated_external.description,
            collection_name=updated_external.collection_name,
            updated_by=current_user.member_id,
        )
        db.refresh(existing_kb)
    except Exception as e:
        logger.error(f"Failed to sync DB with external API: {str(e)}")

    return KnowledgeBaseResponse(
        id=existing_kb.id,
        surro_knowledge_id=existing_kb.surro_knowledge_id,
        created_at=existing_kb.created_at,
        updated_at=existing_kb.updated_at,
        created_by=existing_kb.created_by,
        name=updated_external.name,
        description=updated_external.description,
        collection_name=updated_external.collection_name,
        chunk_size=updated_external.chunk_size,
        chunk_overlap=updated_external.chunk_overlap,
        top_k=updated_external.top_k,
        threshold=updated_external.threshold,
    )


@router.delete(
    "/{knowledge_base_id}",
    status_code=204,
    summary="Delete Knowledge Base",
    description=DELETE_KNOWLEDGE_BASE_DESCRIPTION,
)
async def delete_knowledge_base(
    knowledge_base_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """지식베이스 삭제"""
    surro_knowledge_id = knowledge_base_id
    existing_kb = knowledge_base_crud.get_active_knowledge_base_by_surro_id(
        db=db,
        surro_knowledge_id=surro_knowledge_id,
    )
    if not existing_kb:
        raise HTTPException(status_code=404, detail="Knowledge base not found")

    if current_user.role != "admin" and existing_kb.created_by != current_user.member_id:
        raise HTTPException(status_code=403, detail="Permission denied")

    try:
        await knowledge_base_service.delete_knowledge_base(surro_knowledge_id, _user_info(current_user))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete external knowledge base: {str(e)}")

    try:
        knowledge_base_crud.delete_knowledge_base_by_surro_id(
            db=db,
            surro_knowledge_id=surro_knowledge_id,
            deleted_by=current_user.member_id,
        )
        logger.info(
            f"Soft-deleted knowledge base mapping: surro_id={surro_knowledge_id}, "
            f"member_id={current_user.member_id}"
        )
    except Exception as mapping_error:
        logger.error(f"Failed to soft-delete knowledge base mapping: {str(mapping_error)}")

    return None


@router.post(
    "/{knowledge_base_id}/files",
    response_model=KnowledgeBaseDetailResponse,
    summary="Add File To Knowledge Base",
    description=ADD_FILE_DESCRIPTION,
)
async def add_file_to_knowledge_base(
    knowledge_base_id: int,
    file: UploadFile = File(..., description="추가할 문서 파일"),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """지식베이스에 파일 추가"""
    surro_knowledge_id = knowledge_base_id
    existing_kb = knowledge_base_crud.get_active_knowledge_base_by_surro_id(
        db=db,
        surro_knowledge_id=surro_knowledge_id,
    )
    if not existing_kb:
        raise HTTPException(status_code=404, detail="Knowledge base not found")

    if current_user.role != "admin" and existing_kb.created_by != current_user.member_id:
        raise HTTPException(status_code=403, detail="Permission denied")

    external_kb = await knowledge_base_service.add_file(surro_knowledge_id, file, _user_info(current_user))

    return KnowledgeBaseDetailResponse(
        id=existing_kb.id,
        surro_knowledge_id=existing_kb.surro_knowledge_id,
        created_at=existing_kb.created_at,
        updated_at=existing_kb.updated_at,
        created_by=existing_kb.created_by,
        name=external_kb.name,
        description=external_kb.description,
        collection_name=external_kb.collection_name,
        embedding_model_id=external_kb.embedding_model_id,
        language_id=external_kb.language_id,
        chunk_size=external_kb.chunk_size,
        chunk_overlap=external_kb.chunk_overlap,
        chunk_type_id=external_kb.chunk_type_id,
        search_method_id=external_kb.search_method_id,
        top_k=external_kb.top_k,
        threshold=external_kb.threshold,
        files=external_kb.files,
    )


@router.delete(
    "/{knowledge_base_id}/files/{file_id}",
    response_model=KnowledgeBaseDetailResponse,
    summary="Delete File From Knowledge Base",
    description=DELETE_FILE_DESCRIPTION,
)
async def delete_file_from_knowledge_base(
    knowledge_base_id: int,
    file_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """지식베이스에서 파일 삭제"""
    surro_knowledge_id = knowledge_base_id
    existing_kb = knowledge_base_crud.get_active_knowledge_base_by_surro_id(
        db=db,
        surro_knowledge_id=surro_knowledge_id,
    )
    if not existing_kb:
        raise HTTPException(status_code=404, detail="Knowledge base not found")

    if current_user.role != "admin" and existing_kb.created_by != current_user.member_id:
        raise HTTPException(status_code=403, detail="Permission denied")

    external_kb = await knowledge_base_service.delete_file(
        surro_knowledge_id,
        file_id,
        _user_info(current_user),
    )

    return KnowledgeBaseDetailResponse(
        id=existing_kb.id,
        surro_knowledge_id=existing_kb.surro_knowledge_id,
        created_at=existing_kb.created_at,
        updated_at=existing_kb.updated_at,
        created_by=existing_kb.created_by,
        name=external_kb.name,
        description=external_kb.description,
        collection_name=external_kb.collection_name,
        embedding_model_id=external_kb.embedding_model_id,
        language_id=external_kb.language_id,
        chunk_size=external_kb.chunk_size,
        chunk_overlap=external_kb.chunk_overlap,
        chunk_type_id=external_kb.chunk_type_id,
        search_method_id=external_kb.search_method_id,
        top_k=external_kb.top_k,
        threshold=external_kb.threshold,
        files=external_kb.files,
    )


@router.post(
    "/{knowledge_base_id}/search",
    response_model=KnowledgeBaseSearchResponse,
    summary="Search Knowledge Base",
    description=SEARCH_KNOWLEDGE_BASE_DESCRIPTION,
)
async def search_knowledge_base(
    knowledge_base_id: int,
    search_request: KnowledgeBaseSearchRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """지식베이스 검색"""
    surro_knowledge_id = knowledge_base_id
    existing_kb = knowledge_base_crud.get_active_knowledge_base_by_surro_id(
        db=db,
        surro_knowledge_id=surro_knowledge_id,
    )
    if not existing_kb:
        raise HTTPException(status_code=404, detail="Knowledge base not found")

    if current_user.role != "admin" and existing_kb.created_by != current_user.member_id:
        raise HTTPException(status_code=403, detail="Permission denied")

    return await knowledge_base_service.search_knowledge_base(
        surro_knowledge_id,
        search_request.text,
        _user_info(current_user),
    )


@router.get(
    "/{knowledge_base_id}/search-records",
    response_model=List[KnowledgeBaseSearchRecord],
    summary="Get Knowledge Base Search Records",
    description=SEARCH_RECORDS_DESCRIPTION,
)
async def get_search_records(
    knowledge_base_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """지식베이스 검색 기록 조회"""
    surro_knowledge_id = knowledge_base_id
    existing_kb = knowledge_base_crud.get_active_knowledge_base_by_surro_id(
        db=db,
        surro_knowledge_id=surro_knowledge_id,
    )
    if not existing_kb:
        raise HTTPException(status_code=404, detail="Knowledge base not found")

    if current_user.role != "admin" and existing_kb.created_by != current_user.member_id:
        raise HTTPException(status_code=403, detail="Permission denied")

    return await knowledge_base_service.get_search_records(surro_knowledge_id, _user_info(current_user))
