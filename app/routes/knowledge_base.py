from fastapi import APIRouter, Depends, HTTPException, Query, status, UploadFile, File, Form
from sqlalchemy.orm import Session
from typing import Optional, List
from app.database import get_db
from app.cruds.knowledge_base import knowledge_base_crud
from app.auth import get_current_user
from app.schemas.knowledge_base import (
    KnowledgeBaseCreate,
    KnowledgeBaseUpdate,
    KnowledgeBaseResponse,
    KnowledgeBaseDetailResponse,
    KnowledgeBaseListResponse,
    ChunkTypeListResponse,
    LanguageListResponse,
    SearchMethodListResponse,
    KnowledgeBaseSearchRequest,
    KnowledgeBaseSearchResponse
)
from app.services.knowledge_base_service import knowledge_base_service
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/knowledge-bases", tags=["knowledge-bases"])


# ===== 메타데이터 조회 API (페이징 추가) =====

@router.get("/chunk-types", response_model=ChunkTypeListResponse)
async def get_chunk_types(
        page: int = Query(1, ge=1, description="페이지 번호 (기본값: 1)"),
        size: int = Query(100, ge=1, le=1000, description="페이지당 항목 수 (기본값: 100)"),
        current_user=Depends(get_current_user)
):
    """청크 타입 목록 조회 (페이징)"""
    user_info = {
        'member_id': current_user.member_id,
        'role': current_user.role,
        'name': current_user.name
    }

    all_chunk_types = await knowledge_base_service.get_chunk_types(user_info)

    # 페이징 처리
    total = len(all_chunk_types)
    start = (page - 1) * size
    end = start + size
    chunk_types = all_chunk_types[start:end]

    return ChunkTypeListResponse(
        data=chunk_types,
        total=total,
        page=page,
        size=size
    )


@router.get("/languages", response_model=LanguageListResponse)
async def get_languages(
        page: int = Query(1, ge=1, description="페이지 번호 (기본값: 1)"),
        size: int = Query(100, ge=1, le=1000, description="페이지당 항목 수 (기본값: 100)"),
        current_user=Depends(get_current_user)
):
    """언어 목록 조회 (페이징)"""
    user_info = {
        'member_id': current_user.member_id,
        'role': current_user.role,
        'name': current_user.name
    }

    all_languages = await knowledge_base_service.get_languages(user_info)

    # 페이징 처리
    total = len(all_languages)
    start = (page - 1) * size
    end = start + size
    languages = all_languages[start:end]

    return LanguageListResponse(
        data=languages,
        total=total,
        page=page,
        size=size
    )


@router.get("/search-methods", response_model=SearchMethodListResponse)
async def get_search_methods(
        page: int = Query(1, ge=1, description="페이지 번호 (기본값: 1)"),
        size: int = Query(100, ge=1, le=1000, description="페이지당 항목 수 (기본값: 100)"),
        current_user=Depends(get_current_user)
):
    """검색 방법 목록 조회 (페이징)"""
    user_info = {
        'member_id': current_user.member_id,
        'role': current_user.role,
        'name': current_user.name
    }

    all_search_methods = await knowledge_base_service.get_search_methods(user_info)

    # 페이징 처리
    total = len(all_search_methods)
    start = (page - 1) * size
    end = start + size
    search_methods = all_search_methods[start:end]

    return SearchMethodListResponse(
        data=search_methods,
        total=total,
        page=page,
        size=size
    )


# ===== Knowledge Base CRUD =====

@router.post("/", response_model=KnowledgeBaseResponse, status_code=status.HTTP_201_CREATED)
async def create_knowledge_base(
        name: str = Form(...),
        description: Optional[str] = Form(None),
        language_id: int = Form(...),
        embedding_model_id: int = Form(...),
        chunk_size: int = Form(...),
        chunk_overlap: int = Form(...),
        chunk_type_id: int = Form(...),
        search_method_id: int = Form(...),
        top_k: int = Form(...),
        threshold: float = Form(...),
        file: UploadFile = File(...),
        db: Session = Depends(get_db),
        current_user=Depends(get_current_user)
):
    """지식베이스 생성 (파일 업로드)"""
    user_info = {
        'member_id': current_user.member_id,
        'role': current_user.role,
        'name': current_user.name
    }

    # 외부 API 호출
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
        user_info=user_info
    )

    # 우리 DB에 저장
    try:
        db_kb = knowledge_base_crud.create_knowledge_base(
            db=db,
            name=external_kb.name,
            description=external_kb.description,
            created_by=current_user.member_id,
            surro_knowledge_id=external_kb.id,
            collection_name=external_kb.collection_name
        )
        logger.info(
            f"Created knowledge base: surro_id={external_kb.id}, "
            f"member_id={current_user.member_id}"
        )
    except Exception as mapping_error:
        logger.error(f"Failed to create knowledge base: {str(mapping_error)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Knowledge base created in external API but failed to save: {str(mapping_error)}"
        )

    # 응답: DB 메타정보 + 외부 API 데이터
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
        threshold=external_kb.threshold
    )


@router.get("/", response_model=KnowledgeBaseListResponse)
async def get_knowledge_bases(
        page: int = Query(1, ge=1, description="페이지 번호 (기본값: 1)"),
        size: int = Query(10, ge=1, le=1000, description="페이지당 항목 수 (기본값: 10)"),
        search: Optional[str] = Query(None, description="검색어 (이름, 설명, collection_name)"),
        db: Session = Depends(get_db),
        current_user=Depends(get_current_user)
):
    """지식베이스 목록 조회 (페이징)

    - **page**: 페이지 번호 (기본값: 1)
    - **size**: 페이지당 항목 수 (기본값: 10)
    - **search**: 검색어 (선택)
    """
    skip = (page - 1) * size
    limit = size

    # DB에서 조회
    knowledge_bases, total = knowledge_base_crud.get_knowledge_bases(
        db=db,
        skip=skip,
        limit=limit,
        search=search
    )

    # 응답 데이터 구성
    response_data = [
        KnowledgeBaseResponse(
            id=kb.id,
            surro_knowledge_id=kb.surro_knowledge_id,
            created_at=kb.created_at,
            updated_at=kb.updated_at,
            created_by=kb.created_by,
            name=kb.name,
            description=kb.description,
            collection_name=kb.collection_name,
            chunk_size=None,
            chunk_overlap=None,
            top_k=None,
            threshold=None
        )
        for kb in knowledge_bases
    ]

    return KnowledgeBaseListResponse(
        data=response_data,
        total=total,
        page=page,
        size=size
    )


@router.get("/{surro_knowledge_id}", response_model=KnowledgeBaseDetailResponse)
async def get_knowledge_base(
        surro_knowledge_id: int,
        db: Session = Depends(get_db),
        current_user=Depends(get_current_user)
):
    """지식베이스 상세 정보 조회"""
    # DB에서 조회 (우리 메타 정보)
    db_kb = knowledge_base_crud.get_knowledge_base_by_surro_id(
        db=db,
        surro_knowledge_id=surro_knowledge_id
    )
    if not db_kb:
        raise HTTPException(status_code=404, detail="Knowledge base not found")

    # 외부 API에서 상세 정보 조회
    user_info = {
        'member_id': current_user.member_id,
        'role': current_user.role,
        'name': current_user.name
    }

    external_kb = await knowledge_base_service.get_knowledge_base(
        surro_knowledge_id,
        user_info
    )

    if not external_kb:
        raise HTTPException(
            status_code=404,
            detail="Knowledge base not found in external service"
        )

    # 응답: 우리 DB 메타 정보 + 외부 API 전체 데이터
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
        files=external_kb.files
    )


@router.put("/{surro_knowledge_id}", response_model=KnowledgeBaseResponse)
async def update_knowledge_base(
        surro_knowledge_id: int,
        knowledge_base_update: KnowledgeBaseUpdate,
        db: Session = Depends(get_db),
        current_user=Depends(get_current_user)
):
    """지식베이스 정보 수정"""
    existing_kb = knowledge_base_crud.get_knowledge_base_by_surro_id(
        db=db,
        surro_knowledge_id=surro_knowledge_id
    )
    if not existing_kb:
        raise HTTPException(status_code=404, detail="Knowledge base not found")

    # 권한 확인
    if current_user.role != "admin" and existing_kb.created_by != current_user.member_id:
        raise HTTPException(status_code=403, detail="Permission denied")

    # 외부 API 업데이트
    user_info = {
        'member_id': current_user.member_id,
        'role': current_user.role,
        'name': current_user.name
    }

    try:
        updated_external = await knowledge_base_service.update_knowledge_base(
            knowledge_base_id=surro_knowledge_id,
            name=knowledge_base_update.name,
            description=knowledge_base_update.description,
            user_info=user_info
        )

        if not updated_external:
            raise HTTPException(
                status_code=404,
                detail="Knowledge base not found in external service"
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update external knowledge base: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to update external knowledge base: {str(e)}"
        )

    # DB 업데이트
    try:
        existing_kb.name = updated_external.name
        existing_kb.description = updated_external.description
        existing_kb.collection_name = updated_external.collection_name

        db.commit()
        db.refresh(existing_kb)
    except Exception as e:
        logger.error(f"Failed to sync DB with external API: {str(e)}")

    # 응답
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
        threshold=updated_external.threshold
    )


@router.delete("/{surro_knowledge_id}", status_code=204)
async def delete_knowledge_base(
        surro_knowledge_id: int,
        db: Session = Depends(get_db),
        current_user=Depends(get_current_user)
):
    """지식베이스 삭제"""
    existing_kb = knowledge_base_crud.get_knowledge_base_by_surro_id(
        db=db,
        surro_knowledge_id=surro_knowledge_id
    )
    if not existing_kb:
        raise HTTPException(status_code=404, detail="Knowledge base not found")

    # 권한 확인
    if current_user.role != "admin" and existing_kb.created_by != current_user.member_id:
        raise HTTPException(status_code=403, detail="Permission denied")

    # 외부 API 삭제
    user_info = {
        'member_id': current_user.member_id,
        'role': current_user.role,
        'name': current_user.name
    }

    try:
        await knowledge_base_service.delete_knowledge_base(
            surro_knowledge_id,
            user_info
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to delete external knowledge base: {str(e)}"
        )

    # 우리 DB 삭제
    success = knowledge_base_crud.delete_knowledge_base_by_surro_id(
        db=db,
        surro_knowledge_id=surro_knowledge_id
    )
    if not success:
        raise HTTPException(status_code=404, detail="Knowledge base not found")

    return None


# ===== 파일 관리 =====

@router.post("/{surro_knowledge_id}/files", response_model=KnowledgeBaseDetailResponse)
async def add_file_to_knowledge_base(
        surro_knowledge_id: int,
        file: UploadFile = File(...),
        db: Session = Depends(get_db),
        current_user=Depends(get_current_user)
):
    """지식베이스에 파일 추가"""
    existing_kb = knowledge_base_crud.get_knowledge_base_by_surro_id(
        db=db,
        surro_knowledge_id=surro_knowledge_id
    )
    if not existing_kb:
        raise HTTPException(status_code=404, detail="Knowledge base not found")

    if current_user.role != "admin" and existing_kb.created_by != current_user.member_id:
        raise HTTPException(status_code=403, detail="Permission denied")

    user_info = {
        'member_id': current_user.member_id,
        'role': current_user.role,
        'name': current_user.name
    }

    external_kb = await knowledge_base_service.add_file(
        surro_knowledge_id,
        file,
        user_info
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
        files=external_kb.files
    )


@router.delete("/{surro_knowledge_id}/files/{file_id}", response_model=KnowledgeBaseDetailResponse)
async def delete_file_from_knowledge_base(
        surro_knowledge_id: int,
        file_id: int,
        db: Session = Depends(get_db),
        current_user=Depends(get_current_user)
):
    """지식베이스에서 파일 삭제"""
    existing_kb = knowledge_base_crud.get_knowledge_base_by_surro_id(
        db=db,
        surro_knowledge_id=surro_knowledge_id
    )
    if not existing_kb:
        raise HTTPException(status_code=404, detail="Knowledge base not found")

    if current_user.role != "admin" and existing_kb.created_by != current_user.member_id:
        raise HTTPException(status_code=403, detail="Permission denied")

    user_info = {
        'member_id': current_user.member_id,
        'role': current_user.role,
        'name': current_user.name
    }

    external_kb = await knowledge_base_service.delete_file(
        surro_knowledge_id,
        file_id,
        user_info
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
        files=external_kb.files
    )


# ===== 검색 =====

@router.post("/{surro_knowledge_id}/search", response_model=KnowledgeBaseSearchResponse)
async def search_knowledge_base(
        surro_knowledge_id: int,
        search_request: KnowledgeBaseSearchRequest,
        db: Session = Depends(get_db),
        current_user=Depends(get_current_user)
):
    """지식베이스 검색"""
    existing_kb = knowledge_base_crud.get_knowledge_base_by_surro_id(
        db=db,
        surro_knowledge_id=surro_knowledge_id
    )
    if not existing_kb:
        raise HTTPException(status_code=404, detail="Knowledge base not found")

    user_info = {
        'member_id': current_user.member_id,
        'role': current_user.role,
        'name': current_user.name
    }

    search_result = await knowledge_base_service.search_knowledge_base(
        surro_knowledge_id,
        search_request.text,
        user_info
    )

    return search_result


@router.get("/{surro_knowledge_id}/search-records")
async def get_search_records(
        surro_knowledge_id: int,
        db: Session = Depends(get_db),
        current_user=Depends(get_current_user)
):
    """지식베이스 검색 기록 조회"""
    existing_kb = knowledge_base_crud.get_knowledge_base_by_surro_id(
        db=db,
        surro_knowledge_id=surro_knowledge_id
    )
    if not existing_kb:
        raise HTTPException(status_code=404, detail="Knowledge base not found")

    user_info = {
        'member_id': current_user.member_id,
        'role': current_user.role,
        'name': current_user.name
    }

    search_records = await knowledge_base_service.get_search_records(
        surro_knowledge_id,
        user_info
    )

    return search_records