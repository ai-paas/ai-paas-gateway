from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials, OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.auth import AuthService, get_current_user, optional_security
from app.config import settings
from app.cruds import member_crud
from app.database import get_db
from app.schemas.member import (
    ChangePasswordRequest,
    LoginRequest,
    MemberResponse,
    TokenResponse,
)

router = APIRouter(prefix="/auth", tags=["authentication"])


def _set_refresh_token_cookie(response: Response, refresh_token: str) -> None:
    cookie_kwargs = {
        "key": settings.AUTH_REFRESH_COOKIE_NAME,
        "value": refresh_token,
        "httponly": settings.AUTH_REFRESH_COOKIE_HTTPONLY,
        "secure": settings.AUTH_REFRESH_COOKIE_SECURE,
        "samesite": settings.AUTH_REFRESH_COOKIE_SAMESITE,
        "path": settings.AUTH_REFRESH_COOKIE_PATH,
        "max_age": settings.AUTH_REFRESH_COOKIE_MAX_AGE,
    }

    if settings.AUTH_REFRESH_COOKIE_DOMAIN:
        cookie_kwargs["domain"] = settings.AUTH_REFRESH_COOKIE_DOMAIN

    response.set_cookie(**cookie_kwargs)


def _clear_refresh_token_cookie(response: Response) -> None:
    delete_kwargs = {
        "key": settings.AUTH_REFRESH_COOKIE_NAME,
        "path": settings.AUTH_REFRESH_COOKIE_PATH,
    }

    if settings.AUTH_REFRESH_COOKIE_DOMAIN:
        delete_kwargs["domain"] = settings.AUTH_REFRESH_COOKIE_DOMAIN

    response.delete_cookie(**delete_kwargs)


@router.post("/login", response_model=TokenResponse)
def login(
        login_data: LoginRequest,
        response: Response,
        db: Session = Depends(get_db)
):
    """로그인"""
    member = AuthService.authenticate_member(
        db, login_data.member_id, login_data.password
    )

    if not member:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect member_id or password"
        )

    if not member.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Account is deactivated"
        )

    access_token = AuthService.create_access_token(
        data={"sub": member.member_id, "role": member.role}
    )
    refresh_token = AuthService.create_refresh_token(
        data={"sub": member.member_id}
    )

    _set_refresh_token_cookie(response, refresh_token)
    member_crud.update_last_login(db=db, member_id=member.member_id)

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "expires_in": settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60
    }


@router.post("/token", response_model=TokenResponse)
def login_for_swagger(
        response: Response,
        form_data: OAuth2PasswordRequestForm = Depends(),
        db: Session = Depends(get_db)
):
    """Swagger OAuth2 password flow login. `username` 필드에 member_id를 입력."""
    member = AuthService.authenticate_member(
        db, form_data.username, form_data.password
    )

    if not member:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect member_id or password"
        )

    if not member.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Account is deactivated"
        )

    access_token = AuthService.create_access_token(
        data={"sub": member.member_id, "role": member.role}
    )
    refresh_token = AuthService.create_refresh_token(
        data={"sub": member.member_id}
    )

    _set_refresh_token_cookie(response, refresh_token)
    member_crud.update_last_login(db=db, member_id=member.member_id)

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "expires_in": settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60
    }


@router.post("/refresh", response_model=TokenResponse)
def refresh_token(
        request: Request,
        response: Response,
        db: Session = Depends(get_db)
):
    """토큰 갱신"""
    refresh_token_value = request.cookies.get(settings.AUTH_REFRESH_COOKIE_NAME)
    if not refresh_token_value:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token cookie is missing"
        )

    token_data = AuthService.verify_token(refresh_token_value)

    if token_data["type"] != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type"
        )

    member = member_crud.get_member(db, token_data["member_id"])
    if not member or not member.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive"
        )

    new_access_token = AuthService.create_access_token(
        data={"sub": member.member_id, "role": member.role}
    )
    new_refresh_token = AuthService.create_refresh_token(
        data={"sub": member.member_id}
    )

    _set_refresh_token_cookie(response, new_refresh_token)

    return {
        "access_token": new_access_token,
        "token_type": "bearer",
        "expires_in": settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60
    }


@router.post("/logout")
def logout(
        response: Response,
        credentials: HTTPAuthorizationCredentials | None = Depends(optional_security)
):
    """로그아웃"""
    if credentials:
        AuthService.revoke_token(credentials.credentials)

    _clear_refresh_token_cookie(response)

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
    if not AuthService.verify_password(password_data.current_password, current_user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect"
        )

    new_password_hash = AuthService.get_password_hash(password_data.new_password)
    current_user.password_hash = new_password_hash
    db.commit()

    return {"message": "Password changed successfully"}


@router.post("/validate-token")
def validate_token(
        current_user=Depends(get_current_user)
):
    """토큰 유효성 검증"""
    return {
        "valid": True,
        "member_id": current_user.member_id,
        "role": current_user.role
    }
