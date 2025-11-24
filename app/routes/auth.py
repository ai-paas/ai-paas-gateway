from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from app.database import get_db
from app.schemas.member import (
    LoginRequest, TokenResponse, RefreshTokenRequest,
    ChangePasswordRequest, MemberResponse
)
from app.auth import AuthService, get_current_user, security
from app.cruds import member_crud

router = APIRouter(prefix="/auth", tags=["authentication"])


@router.post("/login", response_model=TokenResponse)
def login(
        login_data: LoginRequest,
        db: Session = Depends(get_db)
):
    """로그인"""
    # 사용자 인증
    member = AuthService.authenticate_member(
        db, login_data.member_id, login_data.password
    )

    if not member:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect member_id or password"
        )

    # 활성 상태 확인
    if not member.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Account is deactivated"
        )

    # 토큰 생성
    access_token = AuthService.create_access_token(
        data={"sub": member.member_id, "role": member.role}
    )
    refresh_token = AuthService.create_refresh_token(
        data={"sub": member.member_id}
    )

    # 마지막 로그인 시간 업데이트
    member_crud.update_last_login(db=db, member_id=member.member_id)

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "expires_in": 30 * 60  # 30분을 초로 변환
    }


@router.post("/refresh", response_model=TokenResponse)
def refresh_token(
        refresh_data: RefreshTokenRequest,
        db: Session = Depends(get_db)
):
    """토큰 갱신"""
    try:
        # 리프레시 토큰 검증
        token_data = AuthService.verify_token(refresh_data.refresh_token)

        if token_data["type"] != "refresh":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token type"
            )

        # 사용자 확인
        member = member_crud.get_member(db, token_data["member_id"])
        if not member or not member.is_active:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found or inactive"
            )

        # 새 토큰 생성
        new_access_token = AuthService.create_access_token(
            data={"sub": member.member_id, "role": member.role}
        )
        new_refresh_token = AuthService.create_refresh_token(
            data={"sub": member.member_id}
        )

        return {
            "access_token": new_access_token,
            "refresh_token": new_refresh_token,
            "token_type": "bearer",
            "expires_in": 30 * 60
        }

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token"
        )


@router.post("/logout")
def logout(
        credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """로그아웃"""
    token = credentials.credentials

    # 토큰을 블랙리스트에 추가
    AuthService.revoke_token(token)

    return {"message": "Successfully logged out"}


@router.get("/me", response_model=MemberResponse)
def get_current_user_info(
        current_user=Depends(get_current_user)
):
    """현재 로그인한 사용자 정보 조회"""
    return current_user


@router.post("/change-password")
def change_password(
        password_data: ChangePasswordRequest,
        current_user=Depends(get_current_user),
        db: Session = Depends(get_db)
):
    """비밀번호 변경"""
    # 현재 비밀번호 확인
    if not AuthService.verify_password(password_data.current_password, current_user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect"
        )

    # 새 비밀번호 해싱
    new_password_hash = AuthService.get_password_hash(password_data.new_password)

    # 데이터베이스 업데이트
    current_user.password_hash = new_password_hash
    db.commit()

    return {"message": "Password changed successfully"}


@router.post("/validate-token")
def validate_token(
        current_user=Depends(get_current_user)
):
    """토큰 유효성 검사"""
    return {
        "valid": True,
        "member_id": current_user.member_id,
        "role": current_user.role
    }