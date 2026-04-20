# scripts/

개발·운영용 Python 스크립트 저장 폴더.

## 관리 규약

| 위치 | 용도 | Git |
|---|---|---|
| `scripts/*.py` | **커밋 대상**: 팀 공유 개발 도구 (예: 데이터 싱크, 마이그레이션 보조 등) | 트래킹 |
| `scripts/local/**` | **로컬 전용**: 로컬 테스트 스크립트, MLOps OpenAPI 덤프, 임시 토큰 등 | `.gitignore`로 제외 |

`scripts/local/`은 `.gitignore`에서 디렉토리 단위로 무시되므로, 로컬 전용 파일을 이 하위에 두면
개별 패턴을 `.gitignore`에 추가하지 않아도 됩니다.

## 현재 파일

### scripts/ (트래킹)
- `sync_datasets.py` — 데이터셋 동기화 스크립트

### scripts/local/ (로컬 전용)
- `mlops_openapi.json` — MLOps `/openapi.json` 덤프 (스웨거 설명 동기화용 참조)
- `mlops_workflows_summary.txt` — 위 덤프에서 Workflows 섹션만 추출한 요약
- `mlops_models_summary.txt` — 위 덤프에서 Models 섹션만 추출한 요약
- `test_workflow_gets.py` — 게이트웨이(127.0.0.1:8000) vs MLOps(***REDACTED***:30080) GET 비교 스크립트
- `.tok_local`, `.tok_mlops` — 로그인 토큰 임시 저장 (테스트 후 삭제 권장)

## MLOps OpenAPI 재다운로드

스웨거 설명 최신화 등이 필요할 때:

```bash
curl -sS -o scripts/local/mlops_openapi.json http://***REDACTED***:30080/openapi.json
```

## GET API 비교 테스트

```bash
# 1) 로컬 게이트웨이 로그인 (admin / ***REDACTED***)
curl -s -X POST http://127.0.0.1:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"member_id":"admin","password":"***REDACTED***"}' \
  | python -c "import sys,json; print(json.load(sys.stdin)['access_token'])" \
  > scripts/local/.tok_local

# 2) MLOps 로그인 (.env의 EXTERNAL_API_USERNAME/PASSWORD)
curl -s -X POST http://***REDACTED***:30080/api/v1/authentications/token \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d 'username=***REDACTED***&password=***REDACTED***' \
  | python -c "import sys,json; print(json.load(sys.stdin)['access_token'])" \
  > scripts/local/.tok_mlops

# 3) 비교 테스트 실행
python scripts/local/test_workflow_gets.py

# 4) 테스트 후 토큰 정리
rm scripts/local/.tok_local scripts/local/.tok_mlops
```
