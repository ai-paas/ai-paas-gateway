from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from app.config import settings
from app.routes import service, member, auth, workflow, external_api_test, model
import uvicorn
import logging

# 프록시가 활성화된 경우에만 import
if settings.PROXY_ENABLED:
    from app.routes import proxy

# 로깅 설정
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper()),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """애플리케이션 라이프사이클 관리"""
    # 시작 시
    logger.info("Starting AIPaaS Gateway API")
    logger.info(f"Proxy enabled: {settings.PROXY_ENABLED}")
    if settings.PROXY_ENABLED:
        logger.info(f"Proxy target: {settings.PROXY_TARGET_BASE_URL}")

    yield

    # 종료 시
    logger.info("Shutting down AIPaaS Gateway API")
    if settings.PROXY_ENABLED:
        await proxy.cleanup_proxy()


# FastAPI 앱 초기화
app = FastAPI(
    title=settings.PROJECT_NAME,
    description="AI PaaS Gateway API with Proxy Support",
    version="1.0.0",
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    lifespan=lifespan
)

# CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 프로덕션에서는 특정 도메인으로 제한
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 라우터 등록 (순서가 중요! 프록시 라우터는 가장 마지막에)
app.include_router(auth.router, prefix=settings.API_V1_STR)
app.include_router(service.router, prefix=settings.API_V1_STR)
app.include_router(member.router, prefix=settings.API_V1_STR)
app.include_router(workflow.router, prefix=settings.API_V1_STR)
app.include_router(external_api_test.router, prefix=settings.API_V1_STR)
app.include_router(model.router, prefix=settings.API_V1_STR)

# 프록시 라우터는 가장 마지막에 등록 (모든 경로를 캐치하므로)
if settings.PROXY_ENABLED:
    app.include_router(proxy.router, prefix=settings.API_V1_STR)
    logger.info("Proxy router registered")


# 기본 엔드포인트
@app.get("/")
def read_root():
    return {
        "message": "AIPaaS Gateway Management API",
        "version": "1.0.0",
        "docs_url": "/docs",
        "api_prefix": settings.API_V1_STR,
    }


# 헬스체크 엔드포인트
@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "database_configured": bool(settings.DATABASE_URL)
    }


if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
        log_level=settings.LOG_LEVEL
    )