# from fastapi import HTTPException, Request, status
# from fastapi.responses import JSONResponse
# from starlette.middleware.base import BaseHTTPMiddleware
# from starlette.responses import Response
# from sqlalchemy.orm import Session
# from app.database import get_db
# from app.auth import AuthService
# from app.cruds import member_crud
# import re
#
#
# class AuthMiddleware(BaseHTTPMiddleware):
#     """
#     자동 JWT 인증 미들웨어
#     특정 경로에 대해 자동으로 JWT 토큰을 확인하고 사용자 정보를 request.state에 저장
#     """
#
#     # 인증이 필요 없는 경로들
#     PUBLIC_PATHS = [
#         "/",
#         "/health",
#         "/docs",
#         "/redoc",
#         "/openapi.json",
#         "/api/v1/auth/login",
#         "/api/v1/auth/register",
#         "/api/v1/auth/refresh",
#     ]
#
#     # 인증이 필요한 경로 패턴들
#     PROTECTED_PATTERNS = [
#         r"^/api/v1/members.*",
#         r"^/api/v1/services.*",
#     ]
#
#     def __init__(self, app):
#         super().__init__(app)
#
#     async def dispatch(self, request: Request, call_next):
#         """요청 처리 전후로 인증 로직 실행"""
#
#         # 인증이 필요한지 확인
#         if not self._requires_auth(request.url.path):
#             response = await call_next(request)
#             return response
#
#         try:
#             # JWT 토큰 추출 및 검증
#             user = await self._authenticate_request(request)
#
#             # 사용자 정보를 request.state에 저장
#             request.state.current_user = user
#
#         except HTTPException as e:
#             return JSONResponse(
#                 status_code=e.status_code,
#                 content={"detail": e.detail}
#             )
#         except Exception as e:
#             return JSONResponse(
#                 status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
#                 content={"detail": "Internal server error"}
#             )
#
#         response = await call_next(request)
#         return response
#
#     def _requires_auth(self, path: str) -> bool:
#         """경로가 인증이 필요한지 확인"""
#         # 공개 경로인 경우 인증 불필요
#         if path in self.PUBLIC_PATHS:
#             return False
#
#         # 보호된 패턴과 매칭되는지 확인
#         for pattern in self.PROTECTED_PATTERNS:
#             if re.match(pattern, path):
#                 return True
#
#         return False
#
#     async def _authenticate_request(self, request: Request):
#         """요청에서 JWT 토큰을 추출하고 사용자 인증"""
#
#         # Authorization 헤더에서 토큰 추출
#         authorization = request.headers.get("Authorization")
#         if not authorization:
#             raise HTTPException(
#                 status_code=status.HTTP_401_UNAUTHORIZED,
#                 detail="Authorization header missing"
#             )
#
#         if not authorization.startswith("Bearer "):
#             raise HTTPException(
#                 status_code=status.HTTP_401_UNAUTHORIZED,
#                 detail="Invalid authorization header format"
#             )
#
#         token = authorization.split(" ")[1]
#
#         # 토큰 검증
#         token_data = AuthService.verify_token(token)
#
#         if token_data["type"] != "access":
#             raise HTTPException(
#                 status_code=status.HTTP_401_UNAUTHORIZED,
#                 detail="Invalid token type"
#             )
#
#         # 데이터베이스에서 사용자 조회
#         db = next(get_db())
#         try:
#             member = member_crud.get_member(db, token_data["member_id"])
#             if member is None:
#                 raise HTTPException(
#                     status_code=status.HTTP_401_UNAUTHORIZED,
#                     detail="User not found"
#                 )
#             return member
#         finally:
#             db.close()
#
#
# # Request에서 현재 사용자 가져오는 의존성
# def get_current_user_from_state(request: Request):
#     """미들웨어에서 설정한 현재 사용자 정보 반환"""
#     user = getattr(request.state, 'current_user', None)
#     if not user:
#         raise HTTPException(
#             status_code=status.HTTP_401_UNAUTHORIZED,
#             detail="User not authenticated"
#         )
#     return user
#
#
# # 선택적으로 현재 사용자 가져오기
# def get_current_user_optional_from_state(request: Request):
#     """미들웨어에서 설정한 현재 사용자 정보 반환 (선택적)"""
#     return getattr(request.state, 'current_user', None)