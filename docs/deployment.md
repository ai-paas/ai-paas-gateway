# 설치 · 실행 · 배포

## 로컬 개발

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env             # DATABASE_URL, JWT_SECRET_KEY는 필수
alembic upgrade head
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

`./run.sh`는 의존성 설치 → `alembic upgrade head` → uvicorn 실행을 한 번에 수행한다.

`DATABASE_URL` 또는 `JWT_SECRET_KEY`가 없으면 `app/config.py`가 기동 시점에 `ValueError`로 실패한다. provider를 켜는 경우(`PROXY_ENABLED` 등) 해당 base URL·계정도 함께 검증한다.

## Docker

```bash
docker compose up --build
```

```bash
docker build -t ai-paas-gateway .
docker run --env-file .env -d --name ai-paas-gateway-api -p 8000:8000 ai-paas-gateway
```

`docker compose`는 `.env`를 읽어 환경변수를 주입하고 소스를 볼륨 마운트한다(개발용, `--reload`).

`docker-compose.test.yml`은 Postgres를 함께 띄우는 로컬 테스트용이다. 시크릿을 파일에 두지 않으므로
`.env.test`(gitignored)를 만들고 `--env-file`로 넘겨야 한다 — compose의 `${...}` 보간은 `env_file:` 값을 읽지 않는다.

```bash
cp .env.example .env.test        # POSTGRES_PASSWORD, JWT_SECRET_KEY 채우기
docker compose --env-file .env.test -f docker-compose.test.yml up -d --build
```

`develop` 브랜치 push 시 `.github/workflows/deploy.yml`이 self-hosted runner에서 이미지를 빌드하고 컨테이너를 재기동한다(`.env`는 `secrets.ENV_FILE`에서 생성).

## 테스트

```bash
python -m pytest tests/ -q -m "not postgres"
```

```bash
python -m pytest tests/ -q
```

- 현재 473건 통과 (`-m "not postgres"`).
- `postgres` 마커는 PostgreSQL 전용 테스트에 사용한다(`pytest.ini`). 실행에는 `TEST_DATABASE_URL`이 필요하다.
- 픽스처 표준은 `tests/conftest.py` (`sample_member`, `admin_member`, monkeypatch 기반 provider fake).
- 외부 provider 호출은 실제 네트워크를 타지 않도록 service 함수를 monkeypatch한다.
