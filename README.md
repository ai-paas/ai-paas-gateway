# AI PaaS Gateway

[AI-PaaS](https://github.com/ai-paas) 프로젝트의 게이트웨이 저장소.

FastAPI 기반 AI PaaS 게이트웨이. 외부 AI 플랫폼(MLOps/Surro, [Hub Connect](https://github.com/ai-paas/hub-connect), [Any Cloud](https://github.com/ai-paas/any-cloud-management))을 프론트엔드([ai-paas-web](https://github.com/ai-paas/ai-paas-web))에 단일 API로 노출하고, 게이트웨이 자체 DB에서 **사용자·권한·리소스 매핑**을 관리한다.

- API 경로: `/api/v1` — 188 path / 231 operation
- 라우터 모듈 14개 (`any_cloud`는 17개 sub-router로 분할)
- 테스트 473건 통과 (`pytest -m "not postgres"`)

## 빠른 시작

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env             # DATABASE_URL, JWT_SECRET_KEY는 필수
alembic upgrade head
uvicorn app.main:app --reload
```

기동 후 <http://localhost:8000/docs>에서 Swagger UI로 전체 API를 확인할 수 있다. `./run.sh`는 의존성 설치 → 마이그레이션 → 서버 실행을 한 번에 수행한다.

Docker로 띄우려면:

```bash
docker compose up --build
```

## 핵심 설계 원칙

| 원칙 | 내용 |
|---|---|
| 단순 프록시가 아니다 | 외부 provider 리소스는 게이트웨이 DB의 매핑 행(`created_by`, `surro_*_id`, soft-delete 상태)과 결합해 권한을 판정한다. upstream ID만으로 접근을 허용하지 않는다. |
| public contract 분리 | 프론트에 노출되는 요청/응답 형식은 게이트웨이 표준(`page`/`size`, `{data,total,page,size}`)을 따르고, upstream의 `page_size`/`limit`/`items` 등은 service adapter 내부에서만 변환한다. |
| 검증 lockstep | upstream spec이 완화되면 게이트웨이 라우트 검증(`Body`/`Query` 제약, 스키마)도 같이 완화한다. 그렇지 않으면 새 spec을 따르는 클라이언트가 게이트웨이에서 먼저 422를 받는다. |
| provider 비활성 허용 | `PROXY_ENABLED` / `HUB_CONNECT_ENABLED` / `ANY_CLOUD_ENABLED`가 false여도 앱은 기동된다. 해당 도메인만 비활성화된다. |

## 기술 스택

| 구분 | 사용 기술 |
|---|---|
| 런타임 | Python 3.12 (Docker 이미지 `python:3.12-slim`) |
| 웹 | FastAPI 0.135.3, Uvicorn 0.34.3, Starlette |
| DB | PostgreSQL (`psycopg2-binary` 2.9.11), SQLAlchemy 2.0.49, Alembic 1.18.4 |
| 스키마 | Pydantic 2.12.5, email-validator |
| 인증 | python-jose (JWT), bcrypt 4.3.0 |
| 외부 통신 | httpx 0.28.1 (AsyncClient 커넥션 풀), websockets 13.1 (pod exec 프록시 · uvicorn WS 지원) |
| 스케줄러 | APScheduler 3.10.4 (in-process BackgroundScheduler) |
| 테스트 | pytest 9.0.3 |

## 문서

| 문서 | 내용 |
|---|---|
| [docs/architecture.md](docs/architecture.md) | 모듈 계층, 요청 흐름, 외부 provider 매핑, 데이터 모델 |
| [docs/api-conventions.md](docs/api-conventions.md) | 인증/인가, 페이지네이션, 정렬, 삭제 정책, 감사 로그 |
| [docs/api-reference.md](docs/api-reference.md) | 엔드포인트 전체 목록 (자동 생성) |
| [docs/configuration.md](docs/configuration.md) | 환경 변수, 백그라운드 스케줄러 |
| [docs/deployment.md](docs/deployment.md) | 로컬/Docker 실행, CI 배포, 테스트 |
| [docs/development.md](docs/development.md) | 프로젝트 구조, 개발 가이드, 알려진 제약 |

요청/응답 스키마의 단일 소스는 실행 중인 서버의 Swagger UI(`/docs`)와 `/api/v1/openapi.json`이다. `docs/api-reference.md`는 경로·권한 조망용이며 `scripts/gen_api_docs.py`가 생성한다.

## 라이선스

[Apache License 2.0](LICENSE).
