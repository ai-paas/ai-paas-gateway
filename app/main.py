from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.routes import service, member, auth
import uvicorn

# FastAPI 앱 초기화
app = FastAPI(
    title=settings.PROJECT_NAME,
    description="AI PaaS Gateway API",
    version="1.0.0",
    openapi_url=f"{settings.API_V1_STR}/openapi.json"
)

# CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 프로덕션에서는 특정 도메인으로 제한
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 애플리케이션 시작 이벤트
@app.on_event("startup")
async def startup_event():
    """애플리케이션 시작 시 초기화"""
    print("Service Management API started successfully")

# 라우터 등록
app.include_router(service.router, prefix=settings.API_V1_STR)
app.include_router(member.router, prefix=settings.API_V1_STR)
app.include_router(auth.router, prefix=settings.API_V1_STR)

# 기본 엔드포인트
@app.get("/")
def read_root():
    return {
        "message": "Service Management API",
        "version": "1.0.0",
        "docs_url": "/docs",
        "api_prefix": settings.API_V1_STR
    }

# 헬스체크 엔드포인트
@app.get("/health")
def health_check():
    return {"status": "healthy"}

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True
    )
