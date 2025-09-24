from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from contextlib import asynccontextmanager
from app.config import settings
from app.routes import service, member, auth, workflow, model, dataset, hub_connect, any_cloud
import uvicorn
import logging

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

    yield

    # 종료 시
    logger.info("Shutting down AIPaaS Gateway API")


# FastAPI 앱 초기화
app = FastAPI(
    title=settings.PROJECT_NAME,
    description="AI PaaS Gateway API with Proxy Support",
    version="1.0.0",
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    lifespan=lifespan
)

# CORS 설정
# app.add_middleware(
#     CORSMiddleware,
#     allow_origins=["*"],  # 프로덕션에서는 특정 도메인으로 제한
#     allow_credentials=True,
#     allow_methods=["*"],
#     allow_headers=["*"],
# )

@app.middleware("http")
async def selective_cors_middleware(request, call_next):
    response = await call_next(request)

    # /members 경로에만 CORS 헤더 추가
    if request.url.path.startswith(f"{settings.API_V1_STR}/members"):
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "*"
        response.headers["Access-Control-Allow-Credentials"] = "false"

    return response


# OPTIONS 요청 처리 (Preflight) - Swagger에서 숨김
@app.options(f"{settings.API_V1_STR}/members/{{path:path}}", include_in_schema=False)
@app.options(f"{settings.API_V1_STR}/members/", include_in_schema=False)
@app.options(f"{settings.API_V1_STR}/members", include_in_schema=False)  # trailing slash 없는 버전 추가
async def handle_cors_preflight():
    """멤버 API용 CORS preflight 요청 처리"""
    response = Response()
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "*"
    response.headers["Access-Control-Allow-Credentials"] = "false"
    return response

# 라우터 등록
app.include_router(auth.router, prefix=settings.API_V1_STR)
app.include_router(service.router, prefix=settings.API_V1_STR)
app.include_router(member.router, prefix=settings.API_V1_STR)
app.include_router(workflow.router, prefix=settings.API_V1_STR)
app.include_router(model.router, prefix=settings.API_V1_STR)
app.include_router(dataset.router, prefix=settings.API_V1_STR)
app.include_router(hub_connect.router, prefix=settings.API_V1_STR)
app.include_router(any_cloud.router_cluster, prefix=settings.API_V1_STR)
app.include_router(any_cloud.router_helm, prefix=settings.API_V1_STR)
app.include_router(any_cloud.router_monit, prefix=settings.API_V1_STR)
app.include_router(any_cloud.router_package, prefix=settings.API_V1_STR)
app.include_router(any_cloud.router_catalog, prefix=settings.API_V1_STR)

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