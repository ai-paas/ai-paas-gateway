# AI-PaaS Gateway Management API

## 기능 개요

### 주요 기능
- 서비스 생성, 조회, 수정, 삭제 (CRUD)
- 서비스별 워크플로우, 데이터셋, 모델, 프롬프트, 모니터링 관리
- 서비스 검색 및 페이지네이션
- 서비스 상세 정보 조회 (관련 모든 리소스 포함)

### API 엔드포인트
| 기능 | HTTP 메서드 | 엔드포인트 | 설명 |
|------|-------------|------------|------|
| 서비스 생성 | POST | `/api/v1/services/` | 새 서비스 생성 |
| 서비스 목록 조회 | GET | `/api/v1/services/` | 서비스 목록 조회 (검색, 페이징) |
| 서비스 기본 정보 | GET | `/api/v1/services/{id}` | 서비스 메타데이터 조회 |
| 서비스 상세 정보 | GET | `/api/v1/services/{id}/detail` | 서비스 + 관련 리소스 조회 |
| 서비스 수정 | PUT | `/api/v1/services/{id}` | 서비스 정보 수정 |
| 서비스 삭제 | DELETE | `/api/v1/services/{id}` | 서비스 소프트 삭제 |
| 워크플로우 조회 | GET | `/api/v1/services/{id}/workflows` | 서비스 워크플로우 목록 |
| 데이터셋 조회 | GET | `/api/v1/services/{id}/datasets` | 서비스 데이터셋 목록 |
| 모델 조회 | GET | `/api/v1/services/{id}/models` | 서비스 모델 목록 |
| 프롬프트 조회 | GET | `/api/v1/services/{id}/prompts` | 서비스 프롬프트 목록 |
| 모니터링 조회 | GET | `/api/v1/services/{id}/monitoring` | 서비스 모니터링 목록 |

## 설치 및 실행

### 1. 환경 준비

```bash
# 프로젝트 클론
git clone <repository-url>
cd service-management-api

# 가상환경 생성 (권장)
python -m venv venv

# 가상환경 활성화
# Linux/Mac:
source venv/bin/activate
# Windows:
venv\Scripts\activate

# 의존성 설치
pip install -r requirements.txt
```

### 2. 환경변수 설정

`.env.example` 파일을 참고하여 `.env` 파일을 생성하고 데이터베이스 정보를 입력하세요.

```bash
cp .env.example .env
# .env 파일을 편집하여 실제 데이터베이스 정보 입력
```

### 3. 데이터베이스 마이그레이션

```bash
# Alembic 초기화 (처음 실행 시만)
alembic init alembic

# 마이그레이션 파일 생성
alembic revision --autogenerate -m "Initial migration"

# 마이그레이션 실행
alembic upgrade head
```

### 4. 서버 실행

```bash
# 개발 서버 실행
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# 또는 스크립트 실행
chmod +x run.sh
./run.sh
```

## API 문서

서버 실행 후 다음 URL에서 API 문서를 확인할 수 있습니다:

- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc
- **OpenAPI JSON**: http://localhost:8000/api/v1/openapi.json

## 데이터베이스 스키마

### 주요 테이블

1. **services**: 서비스 기본 정보
2. **service_workflows**: 서비스-워크플로우 매핑
3. **service_datasets**: 서비스-데이터셋 매핑
4. **service_models**: 서비스-모델 매핑
5. **service_prompts**: 서비스-프롬프트 매핑
6. **service_monitoring**: 서비스-모니터링 매핑

## 개발 가이드

### 새로운 API 추가

1. `app/schemas.py`에 Pydantic 스키마 추가
2. `app/models.py`에 SQLAlchemy 모델 추가 (필요한 경우)
3. `app/crud.py`에 데이터베이스 로직 추가
4. `app/routes/`에 API 엔드포인트 추가
5. 마이그레이션 생성 및 적용

### 데이터베이스 스키마 변경

```bash
# 모델 수정 후 마이그레이션 생성
alembic revision --autogenerate -m "변경사항 설명"

# 마이그레이션 적용
alembic upgrade head

# 롤백 (필요한 경우)
alembic downgrade -1
```

## 기술 스택

- **Framework**: FastAPI 0.104.1
- **Database**: PostgreSQL
- **ORM**: SQLAlchemy 2.0.23
- **Migration**: Alembic 1.13.0
- **Validation**: Pydantic 2.5.0
- **Server**: Uvicorn 0.24.0