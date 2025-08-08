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
    
    def __init__(self):
        # 필수 환경변수 체크
        if not self.DATABASE_URL:
            raise ValueError("DATABASE_URL environment variable is required")

settings = Settings()
