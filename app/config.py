import json
import os

from dotenv import load_dotenv

load_dotenv()


def _get_bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).lower() == "true"


def _get_list(name: str, default: list[str] | None = None) -> list[str]:
    raw = os.getenv(name, "")
    if not raw:
        return default[:] if default else []

    raw = raw.strip()
    if raw == "*":
        return ["*"]

    if raw.startswith("["):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return [str(item).strip() for item in parsed if str(item).strip()]
        except json.JSONDecodeError:
            pass

    return [item.strip() for item in raw.split(",") if item.strip()]


class Settings:
    DATABASE_URL: str = os.getenv("DATABASE_URL")

    API_V1_STR: str = os.getenv("API_V1_STR", "/api/v1")
    PROJECT_NAME: str = os.getenv("PROJECT_NAME", "AIPaaS Gateway Management API")
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", "8000"))
    DEBUG: bool = _get_bool("DEBUG", False)
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "info")

    CORS_ALLOW_ORIGINS: list[str] = _get_list("CORS_ALLOW_ORIGINS", ["*"])
    CORS_ALLOW_ORIGIN_REGEX: str = os.getenv("CORS_ALLOW_ORIGIN_REGEX", "")
    CORS_ALLOW_CREDENTIALS: bool = _get_bool("CORS_ALLOW_CREDENTIALS", True)
    CORS_ALLOW_METHODS: list[str] = _get_list("CORS_ALLOW_METHODS", ["*"])
    CORS_ALLOW_HEADERS: list[str] = _get_list("CORS_ALLOW_HEADERS", ["*"])

    JWT_SECRET_KEY: str = os.getenv("JWT_SECRET_KEY")
    JWT_ALGORITHM: str = os.getenv("JWT_ALGORITHM", "HS256")
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "30"))
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = int(os.getenv("JWT_REFRESH_TOKEN_EXPIRE_DAYS", "7"))

    AUTH_REFRESH_COOKIE_NAME: str = os.getenv("AUTH_REFRESH_COOKIE_NAME", "refresh_token")
    AUTH_REFRESH_COOKIE_HTTPONLY: bool = _get_bool("AUTH_REFRESH_COOKIE_HTTPONLY", True)
    AUTH_REFRESH_COOKIE_SECURE: bool = _get_bool("AUTH_REFRESH_COOKIE_SECURE", False)
    AUTH_REFRESH_COOKIE_SAMESITE: str = os.getenv("AUTH_REFRESH_COOKIE_SAMESITE", "lax").lower()
    AUTH_REFRESH_COOKIE_DOMAIN: str = os.getenv("AUTH_REFRESH_COOKIE_DOMAIN", "")
    AUTH_REFRESH_COOKIE_PATH: str = os.getenv("AUTH_REFRESH_COOKIE_PATH", "/api/v1/auth")
    AUTH_REFRESH_COOKIE_MAX_AGE: int = int(
        os.getenv("AUTH_REFRESH_COOKIE_MAX_AGE", str(7 * 24 * 60 * 60))
    )

    LOG_DIR: str = os.getenv("LOG_DIR", "var/log")
    LOG_FILE_ENABLED: bool = _get_bool("LOG_FILE_ENABLED", True)
    LOG_ACCESS_ENABLED: bool = _get_bool("LOG_ACCESS_ENABLED", True)
    LOG_UVICORN_ACCESS_ENABLED: bool = _get_bool("LOG_UVICORN_ACCESS_ENABLED", False)
    LOG_JSON_FORMAT: bool = _get_bool("LOG_JSON_FORMAT", False)
    LOG_ROTATION_MAX_BYTES: int = int(os.getenv("LOG_ROTATION_MAX_BYTES", str(10 * 1024 * 1024)))
    LOG_ROTATION_BACKUP_COUNT: int = int(os.getenv("LOG_ROTATION_BACKUP_COUNT", "10"))
    LOG_ACCESS_MASK_PATHS: list[str] = _get_list(
        "LOG_ACCESS_MASK_PATHS",
        ["/api/v1/auth/login", "/api/v1/auth/refresh", "/api/v1/auth/logout"],
    )

    PROXY_ENABLED: bool = _get_bool("PROXY_ENABLED", False)
    PROXY_TARGET_BASE_URL: str = os.getenv("PROXY_TARGET_BASE_URL", "")
    PROXY_TARGET_PATH_PREFIX: str = os.getenv("PROXY_TARGET_PATH_PREFIX", "/api/v1")
    PROXY_TIMEOUT: float = float(os.getenv("PROXY_TIMEOUT", "30.0"))
    PROXY_CONNECT_TIMEOUT: float = float(os.getenv("PROXY_CONNECT_TIMEOUT", "5.0"))
    PROXY_MAX_CONNECTIONS: int = int(os.getenv("PROXY_MAX_CONNECTIONS", "100"))
    PROXY_MAX_KEEPALIVE_CONNECTIONS: int = int(os.getenv("PROXY_MAX_KEEPALIVE_CONNECTIONS", "20"))
    EXTERNAL_API_USERNAME: str = os.getenv("EXTERNAL_API_USERNAME", "")
    EXTERNAL_API_PASSWORD: str = os.getenv("EXTERNAL_API_PASSWORD", "")

    HUB_CONNECT_ENABLED: bool = _get_bool("HUB_CONNECT_ENABLED", False)
    HUB_CONNECT_TARGET_BASE_URL: str = os.getenv("HUB_CONNECT_TARGET_BASE_URL", "")
    HUB_CONNECT_TARGET_PATH_PREFIX: str = os.getenv("HUB_CONNECT_TARGET_PATH_PREFIX", "/api/v1")
    HUB_CONNECT_TIMEOUT: float = float(os.getenv("HUB_CONNECT_TIMEOUT", "30.0"))
    HUB_CONNECT_CONNECT_TIMEOUT: float = float(os.getenv("HUB_CONNECT_CONNECT_TIMEOUT", "5.0"))
    HUB_CONNECT_MAX_CONNECTIONS: int = int(os.getenv("HUB_CONNECT_MAX_CONNECTIONS", "100"))
    HUB_CONNECT_MAX_KEEPALIVE_CONNECTIONS: int = int(os.getenv("HUB_CONNECT_MAX_KEEPALIVE_CONNECTIONS", "20"))
    HUB_CONNECT_API_USERNAME: str = os.getenv("HUB_CONNECT_API_USERNAME", "")
    HUB_CONNECT_API_PASSWORD: str = os.getenv("HUB_CONNECT_API_PASSWORD", "")

    ANY_CLOUD_ENABLED: bool = _get_bool("ANY_CLOUD_ENABLED", False)
    ANY_CLOUD_TARGET_BASE_URL: str = os.getenv("ANY_CLOUD_TARGET_BASE_URL", "")
    ANY_CLOUD_TIMEOUT: float = float(os.getenv("ANY_CLOUD_TIMEOUT", "30.0"))
    ANY_CLOUD_CONNECT_TIMEOUT: float = float(os.getenv("ANY_CLOUD_CONNECT_TIMEOUT", "5.0"))
    ANY_CLOUD_MAX_CONNECTIONS: int = int(os.getenv("ANY_CLOUD_MAX_CONNECTIONS", "100"))
    ANY_CLOUD_MAX_KEEPALIVE_CONNECTIONS: int = int(os.getenv("ANY_CLOUD_MAX_KEEPALIVE_CONNECTIONS", "20"))

    LITE_MODEL_ENABLED: bool = _get_bool("LITE_MODEL_ENABLED", False)
    LITE_MODEL_TARGET_BASE_URL: str = os.getenv("LITE_MODEL_TARGET_BASE_URL", "")
    LITE_MODEL_TIMEOUT: float = float(os.getenv("LITE_MODEL_TIMEOUT", "30.0"))
    LITE_MODEL_CONNECT_TIMEOUT: float = float(os.getenv("LITE_MODEL_CONNECT_TIMEOUT", "5.0"))
    LITE_MODEL_MAX_CONNECTIONS: int = int(os.getenv("LITE_MODEL_MAX_CONNECTIONS", "100"))
    LITE_MODEL_MAX_KEEPALIVE_CONNECTIONS: int = int(os.getenv("LITE_MODEL_MAX_KEEPALIVE_CONNECTIONS", "20"))

    def __init__(self):
        if not self.DATABASE_URL:
            raise ValueError("DATABASE_URL environment variable is required")

        if not self.JWT_SECRET_KEY:
            raise ValueError("JWT_SECRET_KEY environment variable is required")

        if self.AUTH_REFRESH_COOKIE_SAMESITE not in {"lax", "strict", "none"}:
            raise ValueError(
                "AUTH_REFRESH_COOKIE_SAMESITE must be one of: lax, strict, none"
            )

        if not self.CORS_ALLOW_ORIGINS and not self.CORS_ALLOW_ORIGIN_REGEX:
            raise ValueError("Either CORS_ALLOW_ORIGINS or CORS_ALLOW_ORIGIN_REGEX must be set")

        if self.PROXY_ENABLED and not self.PROXY_TARGET_BASE_URL:
            raise ValueError("PROXY_TARGET_BASE_URL is required when PROXY_ENABLED is true")

        if self.PROXY_ENABLED:
            if not self.EXTERNAL_API_USERNAME:
                raise ValueError("EXTERNAL_API_USERNAME is required when PROXY_ENABLED is true")
            if not self.EXTERNAL_API_PASSWORD:
                raise ValueError("EXTERNAL_API_PASSWORD is required when PROXY_ENABLED is true")

        if self.HUB_CONNECT_ENABLED and not self.HUB_CONNECT_TARGET_BASE_URL:
            raise ValueError("HUB_CONNECT_TARGET_BASE_URL is required when HUB_CONNECT_ENABLED is true")

        if self.HUB_CONNECT_ENABLED:
            if not self.HUB_CONNECT_API_USERNAME:
                raise ValueError("HUB_CONNECT_API_USERNAME is required when HUB_CONNECT_ENABLED is true")
            if not self.HUB_CONNECT_API_PASSWORD:
                raise ValueError("HUB_CONNECT_API_PASSWORD is required when HUB_CONNECT_ENABLED is true")


settings = Settings()
