from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth import (
    get_current_user,
    get_current_admin_user,
    check_member_access
)
from app.common.sort import parse_sort, resolve_sort_columns
from app.cruds import member_crud
from app.database import get_db
from app.models.member import Member
from app.schemas.member import (
    MemberCreate, MemberUpdate, MemberResponse, MemberListResponse
)

router = APIRouter(prefix="/members", tags=["members"])

_MEMBER_SORT_FIELDS = {
    "member_id": Member.member_id,
    "name": Member.name,
    "email": Member.email,
    "role": Member.role,
    "is_active": Member.is_active,
    "created_at": Member.created_at,
    "updated_at": Member.updated_at,
}
_MEMBER_SORT_DEFAULT = [(Member.created_at, True)]
_MEMBER_SORT_TIE_BREAKER = Member.member_id


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
        sort: Optional[str] = Query(
            None,
            description=(
                "정렬 기준. `,` 로 다중 키, `-` 접두사는 내림차순(DESC). "
                "미지정 시 `-created_at`. 허용 필드: "
                "`member_id`, `name`, `email`, `role`, `is_active`, `created_at`, `updated_at`."
            ),
            openapi_examples={
                "default": {"summary": "최신순 (기본)", "value": "-created_at"},
                "name_asc": {"summary": "이름 오름차순", "value": "name"},
                "name_desc": {"summary": "이름 내림차순", "value": "-name"},
                "role_then_name": {"summary": "역할 ASC + 이름 ASC", "value": "role,name"},
                "multi": {"summary": "활성 상태 DESC + 생성일 DESC", "value": "-is_active,-created_at"},
            },
        ),
        db: Session = Depends(get_db),
        _: None = Depends(get_current_admin_user)
):
    """멤버 목록 조회 (검색 및 필터링 포함)"""
    skip = (page - 1) * size
    order_by = resolve_sort_columns(
        parsed=parse_sort(sort),
        allowed=_MEMBER_SORT_FIELDS,
        default=_MEMBER_SORT_DEFAULT,
        tie_breaker=_MEMBER_SORT_TIE_BREAKER,
    )
    members, total = member_crud.get_members(
        db=db,
        skip=skip,
        limit=size,
        search=search,
        role=role,
        order_by=order_by,
    )

    return MemberListResponse(
        data=members,
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
    """멤버 기본 정보 조회 (관리자는 비활성 회원도 조회 가능)"""
    check_member_access(current_user, member_id)

    include_inactive = getattr(current_user, "role", None) == "admin"

    member = member_crud.get_member(db=db, member_id=member_id, include_inactive=include_inactive)
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
    existing_member = member_crud.get_member(db=db, member_id=member_id, include_inactive=True)
    if not existing_member:
        raise HTTPException(status_code=404, detail="Member not found")

    # member_id 중복 체크 (기존 값과 다르게 변경하는 경우만)
    if (member_update.member_id and
        member_update.member_id != existing_member.member_id):
        member_id_exists = member_crud.get_member(db=db, member_id=member_update.member_id)
        if member_id_exists:
            raise HTTPException(status_code=400, detail="Member ID already exists")

    # email 중복 체크 (기존 값과 다르게 변경하는 경우만)
    if (member_update.email and
        member_update.email != existing_member.email):
        email_exists = member_crud.get_member_by_email(db=db, email=str(member_update.email))
        if email_exists:
            raise HTTPException(status_code=400, detail="Email already exists")

    member = member_crud.update_member(db=db, member_id=existing_member.member_id, member_update=member_update)
    return member

@router.delete("/{member_id}")
def delete_member(
        member_id: str,
        db: Session = Depends(get_db),
        current_user = Depends(get_current_user)
):
    """member_id로 멤버 삭제 (하드 삭제)"""
    check_member_access(current_user, member_id)

    member = member_crud.get_member(db=db, member_id=member_id, include_inactive=True)
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")

    success = member_crud.delete_member(db=db, member_id=member.member_id)
    if not success:
        raise HTTPException(status_code=404, detail="Member not found")

    return {"message": "Member deleted successfully"}

@router.patch("/{member_id}/status", response_model=MemberResponse)
def toggle_member_status(
        member_id: str,
        is_active: bool,
        db: Session = Depends(get_db),
        _: None = Depends(get_current_admin_user)
):
    """멤버 활성/비활성 상태 변경"""
    member = member_crud.get_member(db=db, member_id=member_id, include_inactive=True)
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")

    member.is_active = is_active
    member.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(member)
    return member


# @router.get("/{member_id}/services")
# def get_member_services(
#         member_id: str,
#         skip: int = Query(0, ge=0, description="건너뛸 항목 수"),
#         limit: int = Query(100, ge=1, le=1000, description="조회할 항목 수"),
#         db: Session = Depends(get_db),
#         current_user = Depends(get_current_user)
# ):
#     """특정 멤버가 생성한 서비스 목록 조회"""
#     # 권한 검증
#     check_member_access(current_user, member_id)
#     # 멤버 존재 여부 확인
#     member = member_crud.get_member(db=db, member_id=member_id)
#     if not member:
#         raise HTTPException(status_code=404, detail="Member not found")
#
#     # 해당 멤버가 생성한 서비스 조회
#     services, total = service_crud.get_services(
#         db=db,
#         skip=skip,
#         limit=limit,
#         creator_id=member_id
#     )
#
#     return {
#         "services": services,
#         "total": total,
#         "page": (skip // limit) + 1,
#         "size": limit,
#         "member": member
#     }