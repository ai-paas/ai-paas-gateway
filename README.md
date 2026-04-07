# AI-PaaS Gateway Management API

## 기능 개요

### 주요 기능
- JWT 기반 인증/인가 (Access Token, Refresh Token, 역할 기반 접근 제어)
- 회원 관리 (가입, 조회, 수정, 삭제)
- 서비스 관리 (CRUD, 검색, 페이지네이션)
- AI 모델 관리 (외부 Surro API 연동, 모델 생성/조회/삭제/테스트)
- 워크플로우 관리 (외부 API 연동, 생성/조회/수정/삭제)

### API 엔드포인트

#### 인증 (`/api/v1/auth`)
| HTTP 메서드 | 엔드포인트 | 설명 |
|-------------|------------|------|
| POST | `/auth/login` | 로그인 |
| POST | `/auth/refresh` | Access Token 갱신 |
| POST | `/auth/logout` | 로그아웃 (토큰 무효화) |
| GET | `/auth/me` | 현재 사용자 정보 조회 |
| POST | `/auth/change-password` | 비밀번호 변경 |
| POST | `/auth/validate-token` | 토큰 유효성 검증 |

#### 회원 (`/api/v1/members`)
| HTTP 메서드 | 엔드포인트 | 설명 |
|-------------|------------|------|
| POST | `/members/` | 회원 가입 |
| GET | `/members/` | 회원 목록 조회 (관리자, 페이징/검색) |
| GET | `/members/{member_id}` | 회원 상세 조회 |
| PUT | `/members/{member_id}` | 회원 정보 수정 |
| DELETE | `/members/{member_id}` | 회원 삭제 (소프트 삭제) |

#### 서비스 (`/api/v1/services`)
| HTTP 메서드 | 엔드포인트 | 설명 |
|-------------|------------|------|
| POST | `/services/` | 서비스 생성 (관리자) |
| GET | `/services/` | 서비스 목록 조회 (페이징/검색) |
| GET | `/services/{service_id}` | 서비스 상세 조회 |
| PUT | `/services/{service_id}` | 서비스 수정 |
| DELETE | `/services/{service_id}` | 서비스 삭제 (소프트 삭제) |

#### 모델 (`/api/v1/models`)
| HTTP 메서드 | 엔드포인트 | 설명 |
|-------------|------------|------|
| GET | `/models/` | 모델 목록 조회 |
| GET | `/models/providers` | 모델 제공자 목록 |
| GET | `/models/types` | 모델 타입 목록 |
| GET | `/models/formats` | 모델 포맷 목록 |
| GET | `/models/{model_id}` | 모델 상세 조회 |
| POST | `/models/` | 모델 생성 (파일 업로드 지원) |
| DELETE | `/models/{model_id}` | 모델 삭제 |
| POST | `/models/{model_id}/test` | 모델 테스트 |

#### 워크플로우 (`/api/v1/workflows`)
| HTTP 메서드 | 엔드포인트 | 설명 |
|-------------|------------|------|
| POST | `/workflows/` | 워크플로우 생성 |
| GET | `/workflows/` | 워크플로우 목록 조회 (페이징) |
| GET | `/workflows/{workflow_id}` | 워크플로우 상세 조회 |
| PUT | `/workflows/{workflow_id}` | 워크플로우 수정 |
| DELETE | `/workflows/{workflow_id}` | 워크플로우 삭제 (소프트 삭제) |
| GET | `/workflows/my/workflows` | 내 워크플로우 조회 |
| GET | `/workflows/{workflow_id}/external-status` | 외부 워크플로우 상태 확인 |

#### 기타
| HTTP 메서드 | 엔드포인트 | 설명 |
|-------------|------------|------|
| GET | `/` | 루트 |
| GET | `/health` | 헬스 체크 |

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

### Docker로 실행

```bash
# Docker Compose로 실행
docker-compose up -d

# 로그 확인
docker-compose logs -f

# 종료
docker-compose down
```

## API 문서

서버 실행 후 다음 URL에서 API 문서를 확인할 수 있습니다:

- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc
- **OpenAPI JSON**: http://localhost:8000/api/v1/openapi.json

## 프로젝트 구조

```
app/
├── main.py              # FastAPI 앱 진입점
├── auth.py              # JWT 인증/토큰 관리
├── config.py            # 환경 설정
├── database.py          # DB 세션 관리
├── middleware.py         # 미들웨어
├── cruds/               # 데이터베이스 CRUD 로직
│   ├── member.py
│   ├── model.py
│   ├── service.py
│   └── workflow.py
├── models/              # SQLAlchemy ORM 모델
│   ├── base.py
│   ├── member.py
│   ├── model.py
│   ├── service.py
│   └── workflow.py
├── routes/              # API 라우터
│   ├── auth.py
│   ├── member.py
│   ├── model.py
│   ├── service.py
│   └── workflow.py
├── schemas/             # Pydantic 요청/응답 스키마
│   ├── member.py
│   ├── model.py
│   ├── service.py
│   └── workflow.py
└── services/            # 외부 API 연동 서비스
    ├── model_service.py
    └── workflow_service.py
```

## 데이터베이스 스키마

### 주요 테이블

1. **members**: 사용자 정보 (역할, 인증)
2. **services**: 서비스 기본 정보
3. **models**: AI 모델 매핑 (외부 Surro API 연동)
4. **workflows**: 워크플로우 정보 (외부 API 연동)

## 개발 가이드

### 새로운 API 추가

1. `app/schemas/`에 Pydantic 스키마 추가
2. `app/models/`에 SQLAlchemy 모델 추가 (필요한 경우)
3. `app/cruds/`에 데이터베이스 CRUD 로직 추가
4. `app/services/`에 외부 API 연동 서비스 추가 (필요한 경우)
5. `app/routes/`에 API 라우터 추가
6. `app/main.py`에 라우터 등록
7. 마이그레이션 생성 및 적용

### 데이터베이스 스키마 변경

```bash
# 모델 수정 후 마이그레이션 생성
alembic revision --autogenerate -m "변경사항 설명"

# 마이그레이션 적용
alembic upgrade head

# 롤백 (필요한 경우)
alembic downgrade -1
```
