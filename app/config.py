import os
from dotenv import load_dotenv

# .env 파일 로드
load_dotenv()

class Settings:
    # 필수 환경변수
    DATABASE_URL: str = os.getenv("DATABASE_URL")
    
    # 선택적 환경변수 (기본값 포함)
    API_V1_STR: str = os.getenv("API_V1_STR", "/api/v1")
    PROJECT_NAME: str = os.getenv("PROJECT_NAME", "AIPaaS Gateway Management API")
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", "8000"))
    DEBUG: bool = os.getenv("DEBUG", "false").lower() == "true"
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "info")

    # JWT 설정
    JWT_SECRET_KEY: str = os.getenv("JWT_SECRET_KEY")
    JWT_ALGORITHM: str = os.getenv("JWT_ALGORITHM", "HS256")
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "30"))
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = int(os.getenv("JWT_REFRESH_TOKEN_EXPIRE_DAYS", "7"))

    # 외부 API 설정
    PROXY_ENABLED: bool = os.getenv("PROXY_ENABLED", "false").lower() == "true"
    PROXY_TARGET_BASE_URL: str = os.getenv("PROXY_TARGET_BASE_URL", "")
    PROXY_TARGET_PATH_PREFIX: str = os.getenv("PROXY_TARGET_PATH_PREFIX", "/api/v1")
    PROXY_TIMEOUT: float = float(os.getenv("PROXY_TIMEOUT", "30.0"))
    PROXY_CONNECT_TIMEOUT: float = float(os.getenv("PROXY_CONNECT_TIMEOUT", "5.0"))
    PROXY_MAX_CONNECTIONS: int = int(os.getenv("PROXY_MAX_CONNECTIONS", "100"))
    PROXY_MAX_KEEPALIVE_CONNECTIONS: int = int(os.getenv("PROXY_MAX_KEEPALIVE_CONNECTIONS", "20"))

    # 외부 API 인증 설정
    EXTERNAL_API_USERNAME: str = os.getenv("EXTERNAL_API_USERNAME", "")
    EXTERNAL_API_PASSWORD: str = os.getenv("EXTERNAL_API_PASSWORD", "")

    def __init__(self):
        # 필수 환경변수 체크
        if not self.DATABASE_URL:
            raise ValueError("DATABASE_URL environment variable is required")

        # JWT 시크릿 키 체크
        if not self.JWT_SECRET_KEY:
            raise ValueError("JWT_SECRET_KEY environment variable is required")

        # 프록시 설정 검증
        if self.PROXY_ENABLED and not self.PROXY_TARGET_BASE_URL:
            raise ValueError("PROXY_TARGET_BASE_URL is required when PROXY_ENABLED is true")

        # 외부 API 인증 설정 검증 (프록시가 활성화된 경우)
        if self.PROXY_ENABLED:
            if not self.EXTERNAL_API_USERNAME:
                raise ValueError("EXTERNAL_API_USERNAME is required when PROXY_ENABLED is true")
            if not self.EXTERNAL_API_PASSWORD:
                raise ValueError("EXTERNAL_API_PASSWORD is required when PROXY_ENABLED is true")

settings = Settings()
