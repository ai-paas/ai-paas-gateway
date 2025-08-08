from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional, List
from app.database import get_db
from app.crud import member_crud, service_crud
from app.auth import (
    get_current_user,
    get_current_admin_user,
    check_member_access,
    verify_member_access
)
from app.schemas import (
    MemberCreate, MemberUpdate, MemberResponse, MemberListResponse
)

router = APIRouter(prefix="/members", tags=["members"])


@router.post("/", response_model=MemberResponse)
def create_member(
        member: MemberCreate,
        db: Session = Depends(get_db),
        _: None = Depends(get_current_admin_user)
):
    """멤버 생성"""
    # 중복 체크 (member_id - 아이디)
    existing_member = member_crud.get_member(db=db, member_id=member.member_id)
    if existing_member:
        raise HTTPException(status_code=400, detail="Member ID already exists")

    # 중복 체크 (email)
    existing_email = member_crud.get_member_by_email(db=db, email=member.email)
    if existing_email:
        raise HTTPException(status_code=400, detail="Email already exists")

    return member_crud.create_member(db=db, member=member)


@router.get("/", response_model=MemberListResponse)
def get_members(
        page: int = Query(1, ge=1, description="페이지 번호 (1부터 시작)"),
        size: int = Query(20, ge=1, le=100, description="페이지 크기"),
        search: Optional[str] = Query(None, description="검색어 (아이디, 이름, 이메일)"),
        role: Optional[str] = Query(None, description="역할 필터 (admin/user)"),
        db: Session = Depends(get_db),
        _: None = Depends(get_current_admin_user)
):
    """멤버 목록 조회 (검색 및 필터링 포함)"""
    skip = (page - 1) * size
    members, total = member_crud.get_members(
        db=db,
        skip = skip,
        limit=size,
        search=search,
        role=role
    )

    return MemberListResponse(
        members=members,
        total=total,
        page=page,
        size=size
    )


@router.get("/{member_id}", response_model=MemberResponse)
def get_member(
        member_id: str,
        db: Session = Depends(get_db),
        current_user = Depends(get_current_user)
):
    """멤버 기본 정보 조회"""
    check_member_access(current_user, member_id)
    member = member_crud.get_member(db=db, member_id=member_id)
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")
    return member

@router.put("/{member_id}", response_model=MemberResponse)
def update_member(
        member_id: str,
        member_update: MemberUpdate,
        db: Session = Depends(get_db),
        current_user = Depends(get_current_user)
):
    """member_id로 멤버 정보 수정 (본인 또는 관리자만 가능)"""
    # 권한 검증
    check_member_access(current_user, member_id)

    # 기존 멤버 존재 여부 확인
    existing_member = member_crud.get_member(db=db, member_id=member_id)
    if not existing_member:
        raise HTTPException(status_code=404, detail="Member not found")

    # member_id 중복 체크 (변경하는 경우)
    if member_update.member_id and member_update.member_id != existing_member.member_id:
        member_id_exists = member_crud.get_member(db=db, member_id=member_update.member_id)
        if member_id_exists:
            raise HTTPException(status_code=400, detail="Member ID already exists")

    # email 중복 체크 (변경하는 경우)
    if member_update.email and member_update.email != existing_member.email:
        email_exists = member_crud.get_member_by_email(db=db, email=str(member_update.email))
        if email_exists:
            raise HTTPException(status_code=400, detail="Email already exists")

    member = member_crud.update_member(db=db, member_id=existing_member.id, member_update=member_update)
    return member

@router.delete("/{member_id}")
def delete_member(
        member_id: str,
        db: Session = Depends(get_db),
        current_user = Depends(get_current_user)
):
    """member_id로 멤버 삭제 (소프트 삭제)"""
    # 권한 검증
    check_member_access(current_user, member_id)
    member = member_crud.get_member(db=db, member_id=member_id)
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")

    success = member_crud.delete_member(db=db, member_id=member.member_id)
    if not success:
        raise HTTPException(status_code=404, detail="Member not found")
    return {"message": "Member deleted successfully"}


@router.get("/{member_id}/services")
def get_member_services(
        member_id: str,
        skip: int = Query(0, ge=0, description="건너뛸 항목 수"),
        limit: int = Query(100, ge=1, le=1000, description="조회할 항목 수"),
        db: Session = Depends(get_db),
        current_user = Depends(get_current_user)
):
    """특정 멤버가 생성한 서비스 목록 조회"""
    # 권한 검증
    check_member_access(current_user, member_id)
    # 멤버 존재 여부 확인
    member = member_crud.get_member(db=db, member_id=member_id)
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")

    # 해당 멤버가 생성한 서비스 조회
    services, total = service_crud.get_services(
        db=db,
        skip=skip,
        limit=limit,
        creator_id=member_id
    )

    return {
        "services": services,
        "total": total,
        "page": (skip // limit) + 1,
        "size": limit,
        "member": member
    }