#!/usr/bin/env python
"""`docs/api-reference.md` 생성기.

`app.main:app` 의 라우트에서 경로 · 메서드 · 권한 · 설명을 읽어 마크다운 표를 만든다.

엔드포인트 표를 손으로 유지하면 반드시 어긋난다 — 라우트를 추가·삭제해도 문서가 따라오지
않기 때문이다. 실제로 any-cloud 표가 27행에 머물러 있는 동안 코드에는 109개가 있었다.
그래서 문서를 생성물로 두고, `--check` 로 최신 여부를 검증한다.

    python scripts/gen_api_docs.py           # docs/api-reference.md 갱신
    python scripts/gen_api_docs.py --check   # 최신이 아니면 exit 1 (커밋 전 확인용)

DB 에 붙지 않는다. 앱 import 만 하므로 DATABASE_URL / JWT_SECRET_KEY 가 없으면
더미 값을 채워 넣는다.
"""

from __future__ import annotations

import argparse
import inspect
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "docs" / "api-reference.md"

# 앱 import 만 하고 DB 는 건드리지 않는다. 실제 .env 가 있으면 그대로 쓴다.
os.environ.setdefault("DATABASE_URL", "sqlite:///./_gen_api_docs.db")
os.environ.setdefault("JWT_SECRET_KEY", "x" * 48)
os.environ.setdefault("ENABLE_SCHEDULER", "false")
sys.path.insert(0, str(ROOT))

# 태그 → 문서 섹션. 여기 없는 태그는 "기타" 로 모아 뒤에 붙는다(누락 방지).
SECTIONS: list[tuple[str, list[str]]] = [
    ("인증", ["authentication"]),
    ("회원", ["members"]),
    ("서비스", ["services"]),
    ("워크플로우", ["workflows"]),
    ("모델", ["Models"]),
    ("모델 개선", ["Model Improvements"]),
    ("데이터셋", ["Datasets"]),
    ("학습", ["Learning"]),
    ("프롬프트", ["prompts"]),
    ("지식베이스", ["Knowledge Bases"]),
    ("Hub Connect", ["Hub Connect"]),
    ("Any Cloud — 클러스터", ["Any Cloud - Cluster"]),
    ("Any Cloud — VM 인프라", ["Any Cloud - VM"]),
    ("Any Cloud — Kubernetes", ["Any Cloud - Kubernetes", "Any Cloud - Packages"]),
    ("Any Cloud — Helm 저장소 · 카탈로그", ["Any Cloud - HelmRepository", "Any Cloud - Catalog"]),
    ("Any Cloud — 모니터링 · 관측", ["Any Cloud - Monitoring", "Any Cloud - Observability"]),
    ("Any Cloud — 프로바이더 · 자격증명 · 애드온",
     ["Any Cloud - Providers", "Any Cloud - Credentials", "Any Cloud - Addons"]),
    ("Any Cloud — 작업 · 워크플로", ["Any Cloud - Operations", "Any Cloud - Workflow"]),
    ("Any Cloud — 관리자 전용",
     ["Any Cloud - Admin", "Any Cloud - Admin Cluster", "Any Cloud - Admin Agent",
      "Any Cloud - Fleet Upgrade"]),
    ("관리자 대시보드", ["Admin - Dashboard"]),
    ("개인 대시보드", ["My - Dashboard"]),
]

# docstring 이 upstream 구현 세부를 그대로 노출하거나 장황한 경우만 문서용 문구로 대체.
DESCRIPTION_OVERRIDES: dict[tuple[str, str], str] = {
    ("GET", "/any-cloud/catalog/releases"): "클러스터의 Helm 릴리즈 목록",
    ("GET", "/any-cloud/catalog/{repoName}"): "저장소의 차트 목록",
    ("GET", "/any-cloud/catalog/{repoName}/{chartName}/detail"): "차트 상세",
    ("GET", "/any-cloud/catalog/{repoName}/{chartName}/readme"): "차트 README",
    ("GET", "/any-cloud/catalog/{repoName}/{chartName}/status"): "릴리즈 배포 상태",
    ("GET", "/any-cloud/catalog/{repoName}/{chartName}/values"): "차트 기본 values.yaml",
    ("GET", "/any-cloud/catalog/releases/{releaseName}/resources"): "릴리즈가 만든 리소스 목록",
    ("GET", "/any-cloud/kubernetes/{resource_type}"): "리소스 목록 (cursor 페이지네이션)",
    ("GET", "/any-cloud/kubernetes/{resource_type}/{resource_name}"): "리소스 단건 조회",
    ("GET", "/any-cloud/system/cluster/{cluster_id}"): "클러스터 상세 (VM/Registered 통합 스키마)",
    ("DELETE", "/any-cloud/admin/clusters/{cluster_name}/force"): "클러스터 강제 삭제",
    ("DELETE", "/any-cloud/admin/clusters/{stack_name}/orphan-state"): "오펀 Pulumi state 삭제",
    ("GET", "/any-cloud/admin/agents"): "cluster-agent 전체 목록",
    ("GET", "/any-cloud/kubernetes/clusters/{cluster_name}/pods/{namespace}/{pod_name}/exec"):
        "Pod exec 프록시. 토큰은 `bearer` 서브프로토콜 또는 `Authorization` 헤더",
}

ADMIN_DEPS = {"get_current_admin_user", "get_ws_admin_user"}
USER_DEPS = {"get_current_user", "get_ws_current_user"}
SKIP_PATHS = {"/api/v1/openapi.json"}


# WebSocket 라우트는 APIRouter 의 tags 를 물려받지 않는다 — 경로로 보정.
PATH_TAG_FALLBACK = [
    ("/api/v1/any-cloud/kubernetes", "Any Cloud - Kubernetes"),
    ("/api/v1/any-cloud", "Any Cloud - Cluster"),
]


def _tag_from_path(path: str) -> str:
    for prefix, tag in PATH_TAG_FALLBACK:
        if path.startswith(prefix):
            return tag
    return "기타"


def _permission(route) -> str:
    # HTTPBearer 같은 클래스 인스턴스 의존성은 __name__ 이 없다
    names = {getattr(d.call, "__name__", type(d.call).__name__)
             for d in route.dependant.dependencies if getattr(d, "call", None)}
    if names & ADMIN_DEPS:
        return "관리자"
    if names & USER_DEPS:
        return "인증"
    return "공개"


def _description(method: str, path: str, route) -> str:
    override = DESCRIPTION_OVERRIDES.get((method, path))
    if override:
        return override
    text = (getattr(route, "summary", None) or inspect.getdoc(route.endpoint) or "").strip()
    text = text.split("\n")[0].strip()
    # "요약 — 부연" 형태에서 부연이 길면 요약만 남긴다
    if " — " in text and len(text) > 46:
        text = text.split(" — ")[0]
    text = text.rstrip(".").strip()
    if text.startswith("[deprecated]"):
        text = text[len("[deprecated]"):].strip()
    return text or "(설명 없음)"


def collect() -> list[tuple[str, str, str, str, bool]]:
    """(tag, method, path, permission, deprecated, description) 목록."""
    from app.main import app

    rows = []
    for route in app.routes:
        path = getattr(route, "path", "")
        if not path.startswith("/api/v1") or path in SKIP_PATHS:
            continue
        if not hasattr(route, "dependant"):
            continue
        tag = (getattr(route, "tags", None) or [_tag_from_path(path)])[0]
        methods = sorted(m for m in (getattr(route, "methods", None) or {"WEBSOCKET"})
                         if m not in ("HEAD", "OPTIONS"))
        for method in methods:
            short = path[len("/api/v1"):]
            rows.append((tag, method, short, _permission(route),
                         bool(getattr(route, "deprecated", False)),
                         _description(method, short, route)))
    return rows


def render(rows) -> str:
    by_tag: dict[str, list] = {}
    for tag, *rest in rows:
        by_tag.setdefault(tag, []).append(rest)

    known = {t for _, tags in SECTIONS for t in tags}
    leftovers = sorted(t for t in by_tag if t not in known)
    sections = SECTIONS + ([("기타", leftovers)] if leftovers else [])

    total = len(rows)
    admin = sum(1 for r in rows if r[3] == "관리자")
    public = sum(1 for r in rows if r[3] == "공개")

    out = [
        "# API 레퍼런스",
        "",
        "> **이 파일은 `scripts/gen_api_docs.py`가 생성합니다. 직접 고치지 마세요.**",
        "> 라우트를 바꿨으면 `python scripts/gen_api_docs.py`를 다시 돌리세요.",
        "",
        f"전체 {total}개 — 공개 {public} · 인증 {total - admin - public} · 관리자 {admin}.",
        "",
        "권한 열의 의미는 [api-conventions.md](api-conventions.md#인증--인가)를 참조하세요.",
        "요청/응답 스키마는 실행 중인 서버의 Swagger UI(`/docs`)가 단일 소스입니다.",
        "",
    ]
    for title, tags in sections:
        items = [x for t in tags for x in by_tag.get(t, [])]
        if not items:
            continue
        out += [f"## {title} ({len(items)})", "",
                "| Method | Path | 설명 | 권한 |", "|---|---|---|---|"]
        for method, path, perm, deprecated, desc in items:
            if deprecated:
                desc = f"**(deprecated)** {desc}"
            out.append(f"| {method} | `{path}` | {desc} | {perm} |")
        out.append("")
    return "\n".join(out)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="생성 결과가 현재 파일과 다르면 exit 1 (파일은 쓰지 않음)")
    args = parser.parse_args()

    content = render(collect())

    if args.check:
        current = OUTPUT.read_text(encoding="utf-8") if OUTPUT.exists() else ""
        if current != content:
            print(f"{OUTPUT.relative_to(ROOT)} 가 최신이 아닙니다. "
                  "`python scripts/gen_api_docs.py` 를 실행하세요.", file=sys.stderr)
            return 1
        print(f"{OUTPUT.relative_to(ROOT)} 최신입니다.")
        return 0

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(content, encoding="utf-8", newline="\n")
    print(f"{OUTPUT.relative_to(ROOT)} 생성 — {content.count(chr(10)) + 1} 줄")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
