import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.logging_config import configure_logging
from app.middleware import RequestLoggingMiddleware
from app.routes import (
    any_cloud,
    auth,
    dataset,
    experiment,
    hub_connect,
    knowledge_base,
    lite_model,
    member,
    model,
    model_improvement,
    pipeline,
    prompt,
    service,
    workflow,
)

configure_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting AIPaaS Gateway API")
    yield
    logger.info("Shutting down AIPaaS Gateway API")


app = FastAPI(
    title=settings.PROJECT_NAME,
    description="AI PaaS Gateway API with Proxy Support",
    version="1.0.0",
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ALLOW_ORIGINS,
    allow_origin_regex=settings.CORS_ALLOW_ORIGIN_REGEX or None,
    allow_credentials=settings.CORS_ALLOW_CREDENTIALS,
    allow_methods=settings.CORS_ALLOW_METHODS,
    allow_headers=settings.CORS_ALLOW_HEADERS,
)
app.add_middleware(RequestLoggingMiddleware)

app.include_router(auth.router, prefix=settings.API_V1_STR)
app.include_router(service.router, prefix=settings.API_V1_STR)
app.include_router(member.router, prefix=settings.API_V1_STR)
app.include_router(workflow.router, prefix=settings.API_V1_STR)
app.include_router(dataset.router, prefix=settings.API_V1_STR)
app.include_router(pipeline.router, prefix=settings.API_V1_STR)
app.include_router(experiment.router, prefix=settings.API_V1_STR)
app.include_router(model_improvement.router, prefix=settings.API_V1_STR)
app.include_router(model.router, prefix=settings.API_V1_STR)
app.include_router(prompt.router, prefix=settings.API_V1_STR)
app.include_router(knowledge_base.router, prefix=settings.API_V1_STR)
app.include_router(hub_connect.router, prefix=settings.API_V1_STR)
app.include_router(any_cloud.router_cluster, prefix=settings.API_V1_STR)
app.include_router(any_cloud.router_helm, prefix=settings.API_V1_STR)
app.include_router(any_cloud.router_monit, prefix=settings.API_V1_STR)
app.include_router(any_cloud.router_package, prefix=settings.API_V1_STR)
app.include_router(any_cloud.router_catalog, prefix=settings.API_V1_STR)
app.include_router(lite_model.router_info, prefix=settings.API_V1_STR)
app.include_router(lite_model.router_optimize, prefix=settings.API_V1_STR)
app.include_router(lite_model.router_task, prefix=settings.API_V1_STR)
app.include_router(lite_model.router_model, prefix=settings.API_V1_STR)


@app.get("/")
def read_root():
    return {
        "message": "AIPaaS Gateway Management API",
        "version": "1.0.0",
        "docs_url": "/docs",
        "api_prefix": settings.API_V1_STR,
    }


@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "database_configured": bool(settings.DATABASE_URL),
    }


if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
        log_level=settings.LOG_LEVEL,
        access_log=settings.LOG_UVICORN_ACCESS_ENABLED,
    )
