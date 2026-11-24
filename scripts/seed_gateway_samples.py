"""gateway API를 경유해 KB/프롬프트/서비스/워크플로우 샘플을 멱등 시드한다.

서비스 상세(`GET /api/v1/services/{id}`)의 워크플로우 컴포넌트 기반 KB/모델/프롬프트
평탄 리스트 보강 동작을 수동/통합으로 검증할 때 쓴다. 게이트웨이 API를 통해 생성하므로
gateway DB 매핑(`created_by`, `surro_*_id`)이 자동으로 만들어진다 — MLOps에 직접 POST하면
gateway DB 매핑이 없어 보강 응답에 안 보임.

환경변수 (fallback/하드코딩 없음 — public 저장소 정책 준수):
- GATEWAY_BASE_URL          예: http://localhost:8000
- GATEWAY_USERNAME          gateway 로그인 member_id
- GATEWAY_PASSWORD          gateway 로그인 password
- SEED_PDF_PATH             유효한 PDF 파일 경로 (KB upload용). 미지정 시 fail.
- SEED_MODEL_ID (선택)      워크플로우 MODEL 컴포넌트에 박을 모델 ID. 미지정 시 GET /models 첫 항목(임베딩 제외).
- SEED_EMBEDDING_MODEL_ID (선택) KB 생성 시 임베딩 모델 ID. 미지정 시 GET /models에서 type_info에 "embedding" 포함 항목을 검색.

사용 예:
    set GATEWAY_BASE_URL=http://localhost:8000
    set GATEWAY_USERNAME=...
    set GATEWAY_PASSWORD=...
    set SEED_PDF_PATH=C:\\path\\to\\sample.pdf
    python scripts/seed_gateway_samples.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx


SAMPLE_KB_NAME = "seed-sample-kb"
SAMPLE_PROMPT_NAME = "seed-sample-prompt"
SAMPLE_SERVICE_NAME = "seed-sample-service"
SAMPLE_WORKFLOW_NAME = "seed-sample-workflow"


class SeedError(RuntimeError):
    pass


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise SeedError(f"환경변수 {name} 가 필요합니다.")
    return value


def _login(client: httpx.Client, base_url: str, member_id: str, password: str) -> str:
    resp = client.post(
        f"{base_url}/api/v1/auth/login",
        json={"member_id": member_id, "password": password},
        timeout=30.0,
    )
    if resp.status_code != 200:
        raise SeedError(f"login 실패 [{resp.status_code}]: {resp.text}")
    return resp.json()["access_token"]


def _get_first_lookup(
    client: httpx.Client, base_url: str, headers: Dict[str, str], path: str
) -> int:
    resp = client.get(f"{base_url}{path}", headers=headers, params={"size": 1})
    if resp.status_code != 200:
        raise SeedError(f"{path} 조회 실패 [{resp.status_code}]: {resp.text}")
    items = resp.json().get("data") or []
    if not items:
        raise SeedError(f"{path} 응답에 항목 없음 — MLOps 측 데이터 부족")
    return int(items[0]["id"])


def _list_models(
    client: httpx.Client, base_url: str, headers: Dict[str, str]
) -> List[Dict[str, Any]]:
    resp = client.get(
        f"{base_url}/api/v1/models", headers=headers, params={"size": 100}
    )
    if resp.status_code != 200:
        raise SeedError(f"models 조회 실패 [{resp.status_code}]: {resp.text}")
    return resp.json().get("data") or []


def _is_embedding_type(model: Dict[str, Any]) -> bool:
    type_info = model.get("type_info") or {}
    name = (type_info.get("name") or "").lower()
    return "embedding" in name


def _pick_model_id(
    client: httpx.Client, base_url: str, headers: Dict[str, str]
) -> int:
    """워크플로우 MODEL 컴포넌트용 — 임베딩 모델은 의도적으로 제외."""
    override = os.environ.get("SEED_MODEL_ID")
    if override:
        return int(override)
    items = _list_models(client, base_url, headers)
    non_embedding = [m for m in items if not _is_embedding_type(m)]
    pool = non_embedding or items
    if not pool:
        raise SeedError(
            "GET /api/v1/models 응답에 항목 없음 — SEED_MODEL_ID 환경변수로 지정하세요."
        )
    return int(pool[0]["id"])


def _pick_embedding_model_id(
    client: httpx.Client, base_url: str, headers: Dict[str, str]
) -> int:
    """KB 생성용 임베딩 모델 — SEED_EMBEDDING_MODEL_ID 우선, 없으면 type_info에서 'embedding' 검색."""
    override = os.environ.get("SEED_EMBEDDING_MODEL_ID")
    if override:
        return int(override)
    items = _list_models(client, base_url, headers)
    candidates = [m for m in items if _is_embedding_type(m)]
    if not candidates:
        raise SeedError(
            "GET /api/v1/models에서 임베딩 모델을 찾지 못했습니다. "
            "SEED_EMBEDDING_MODEL_ID 환경변수로 명시하세요."
        )
    return int(candidates[0]["id"])


def _find_existing_kb(
    client: httpx.Client, base_url: str, headers: Dict[str, str], name: str
) -> Optional[Dict[str, Any]]:
    # KB 라우트는 prefix만이라 trailing slash 없음
    resp = client.get(
        f"{base_url}/api/v1/knowledge-bases",
        headers=headers,
        params={"size": 100},
    )
    if resp.status_code != 200:
        return None
    for kb in resp.json().get("data") or []:
        if kb.get("name") == name:
            return kb
    return None


def _create_kb(
    client: httpx.Client,
    base_url: str,
    headers: Dict[str, str],
    pdf_path: Path,
    language_id: int,
    embedding_model_id: int,
    chunk_type_id: int,
    search_method_id: int,
) -> Dict[str, Any]:
    existing = _find_existing_kb(client, base_url, headers, SAMPLE_KB_NAME)
    if existing:
        print(f"[KB] 재사용 (이미 존재): id={existing['id']}")
        return existing

    with pdf_path.open("rb") as fp:
        files = {"file": (pdf_path.name, fp, "application/pdf")}
        data = {
            "name": SAMPLE_KB_NAME,
            "description": "seed sample KB for service-detail enrichment",
            "language_id": str(language_id),
            "embedding_model_id": str(embedding_model_id),
            "chunk_size": "500",
            "chunk_overlap": "50",
            "chunk_type_id": str(chunk_type_id),
            "search_method_id": str(search_method_id),
            "top_k": "5",
            "threshold": "0.5",
        }
        resp = client.post(
            f"{base_url}/api/v1/knowledge-bases",
            headers=headers,
            data=data,
            files=files,
            timeout=300.0,
        )
    if resp.status_code not in (200, 201):
        raise SeedError(f"KB 생성 실패 [{resp.status_code}]: {resp.text}")
    kb = resp.json()
    print(f"[KB] 신규 생성: id={kb['id']}")
    return kb


def _find_existing_prompt(
    client: httpx.Client, base_url: str, headers: Dict[str, str], name: str
) -> Optional[Dict[str, Any]]:
    resp = client.get(
        f"{base_url}/api/v1/prompts/", headers=headers, params={"size": 100}
    )
    if resp.status_code != 200:
        return None
    for p in resp.json().get("data") or []:
        if p.get("name") == name:
            return p
    return None


def _create_prompt(
    client: httpx.Client, base_url: str, headers: Dict[str, str]
) -> Dict[str, Any]:
    existing = _find_existing_prompt(client, base_url, headers, SAMPLE_PROMPT_NAME)
    if existing:
        print(f"[Prompt] 재사용: id={existing['id']}")
        return existing

    # MLOps prompt variable enum은 사용자 검증 결과 "context"만 허용
    payload = {
        "prompt": {
            "name": SAMPLE_PROMPT_NAME,
            "description": "seed sample prompt",
            "content": "Summarize the following:\n{{context}}",
        },
        "prompt_variable": ["context"],
    }
    resp = client.post(
        f"{base_url}/api/v1/prompts/",
        headers=headers,
        json=payload,
        timeout=60.0,
    )
    if resp.status_code not in (200, 201):
        raise SeedError(f"Prompt 생성 실패 [{resp.status_code}]: {resp.text}")
    p = resp.json()
    print(f"[Prompt] 신규 생성: id={p['id']}")
    return p


def _find_existing_service(
    client: httpx.Client, base_url: str, headers: Dict[str, str], name: str
) -> Optional[Dict[str, Any]]:
    resp = client.get(
        f"{base_url}/api/v1/services/", headers=headers, params={"size": 100}
    )
    if resp.status_code != 200:
        return None
    for s in resp.json().get("data") or []:
        if s.get("name") == name:
            return s
    return None


def _create_service(
    client: httpx.Client, base_url: str, headers: Dict[str, str]
) -> Dict[str, Any]:
    existing = _find_existing_service(client, base_url, headers, SAMPLE_SERVICE_NAME)
    if existing:
        print(f"[Service] 재사용: id={existing['id']}, surro={existing['surro_service_id']}")
        return existing

    payload = {
        "name": SAMPLE_SERVICE_NAME,
        "description": "seed sample service",
        "tags": ["seed", "enrichment"],
    }
    resp = client.post(
        f"{base_url}/api/v1/services/",
        headers=headers,
        json=payload,
        timeout=60.0,
    )
    if resp.status_code not in (200, 201):
        raise SeedError(f"Service 생성 실패 [{resp.status_code}]: {resp.text}")
    s = resp.json()
    print(f"[Service] 신규 생성: id={s['id']}, surro={s['surro_service_id']}")
    return s


def _find_existing_workflow(
    client: httpx.Client,
    base_url: str,
    headers: Dict[str, str],
    name: str,
    service_id: str,
) -> Optional[Dict[str, Any]]:
    resp = client.get(
        f"{base_url}/api/v1/workflows/",
        headers=headers,
        params={"size": 100, "service_id": service_id},
    )
    if resp.status_code != 200:
        return None
    for w in resp.json().get("data") or []:
        if w.get("name") == name:
            return w
    return None


def _create_workflow(
    client: httpx.Client,
    base_url: str,
    headers: Dict[str, str],
    service_id: str,
    kb_id: int,
    prompt_id: int,
    model_id: int,
) -> Dict[str, Any]:
    existing = _find_existing_workflow(
        client, base_url, headers, SAMPLE_WORKFLOW_NAME, service_id
    )
    if existing:
        print(f"[Workflow] 재사용: surro={existing['surro_workflow_id']}")
        return existing

    payload = {
        "name": SAMPLE_WORKFLOW_NAME,
        "description": "seed sample workflow (KB + MODEL with prompt)",
        "service_id": service_id,
        "workflow_definition": {
            "components": [
                {"ref_id": "start-1", "name": "start", "type": "START"},
                {
                    "ref_id": "kb-1",
                    "name": "knowledge",
                    "type": "KNOWLEDGE_BASE",
                    "knowledge_base_id": kb_id,
                },
                {
                    "ref_id": "model-1",
                    "name": "model",
                    "type": "MODEL",
                    "model_id": model_id,
                    "prompt_id": prompt_id,
                },
                {"ref_id": "end-1", "name": "end", "type": "END"},
            ],
            "connections": [
                {"source_ref_id": "start-1", "target_ref_id": "kb-1"},
                {"source_ref_id": "kb-1", "target_ref_id": "model-1"},
                {"source_ref_id": "model-1", "target_ref_id": "end-1"},
            ],
        },
    }
    resp = client.post(
        f"{base_url}/api/v1/workflows/",
        headers=headers,
        json=payload,
        timeout=120.0,
    )
    if resp.status_code not in (200, 201):
        raise SeedError(f"Workflow 생성 실패 [{resp.status_code}]: {resp.text}")
    w = resp.json()
    print(f"[Workflow] 신규 생성: surro={w['surro_workflow_id']}")
    return w


def main() -> int:
    try:
        base_url = _require_env("GATEWAY_BASE_URL").rstrip("/")
        username = _require_env("GATEWAY_USERNAME")
        password = _require_env("GATEWAY_PASSWORD")
        pdf_path_str = _require_env("SEED_PDF_PATH")

        pdf_path = Path(pdf_path_str)
        if not pdf_path.is_file():
            raise SeedError(f"SEED_PDF_PATH 파일 없음: {pdf_path}")

        # follow_redirects: FastAPI redirect_slashes=True 라 trailing-slash 불일치 시 307 발생 — 안전망.
        with httpx.Client(follow_redirects=True) as client:
            token = _login(client, base_url, username, password)
            headers = {"Authorization": f"Bearer {token}"}

            print("[1/6] 모델 ID 선택...")
            model_id = _pick_model_id(client, base_url, headers)
            embedding_model_id = _pick_embedding_model_id(client, base_url, headers)
            print(f"      model_id={model_id}, embedding_model_id={embedding_model_id}")

            print("[2/6] KB lookup 데이터 조회...")
            chunk_type_id = _get_first_lookup(
                client, base_url, headers, "/api/v1/knowledge-bases/chunk-types"
            )
            language_id = _get_first_lookup(
                client, base_url, headers, "/api/v1/knowledge-bases/languages"
            )
            search_method_id = _get_first_lookup(
                client, base_url, headers, "/api/v1/knowledge-bases/search-methods"
            )
            print(
                f"      chunk_type_id={chunk_type_id}, language_id={language_id}, "
                f"search_method_id={search_method_id}"
            )

            print("[3/6] KB 시드...")
            kb = _create_kb(
                client,
                base_url,
                headers,
                pdf_path,
                language_id=language_id,
                embedding_model_id=embedding_model_id,
                chunk_type_id=chunk_type_id,
                search_method_id=search_method_id,
            )
            kb_surro_id = kb["surro_knowledge_id"]

            print("[4/6] Prompt 시드...")
            prompt = _create_prompt(client, base_url, headers)
            prompt_surro_id = prompt["surro_prompt_id"]

            print("[5/6] Service 시드...")
            service = _create_service(client, base_url, headers)
            service_surro_id = service["surro_service_id"]

            print("[6/6] Workflow 시드...")
            workflow = _create_workflow(
                client,
                base_url,
                headers,
                service_id=service_surro_id,
                kb_id=kb_surro_id,
                prompt_id=prompt_surro_id,
                model_id=model_id,
            )

        print("\n=== 시드 완료 ===")
        print(f"service_id        = {service_surro_id}")
        print(f"workflow_id       = {workflow['surro_workflow_id']}")
        print(f"knowledge_base_id = {kb_surro_id}")
        print(f"prompt_id         = {prompt_surro_id}")
        print(f"model_id          = {model_id}")
        print("\n검증:")
        print(
            f"  curl -H \"Authorization: Bearer <token>\" "
            f"\"{base_url}/api/v1/services/{service_surro_id}\""
        )
        return 0
    except SeedError as exc:
        print(f"[seed] 실패: {exc}", file=sys.stderr)
        return 1
    except httpx.HTTPError as exc:
        print(f"[seed] HTTP 오류: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
