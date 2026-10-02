"""생성 시도와 업스트림 KB 를 1:1 로 잇는 상관 토큰.

업스트림 API 를 바꾸지 않기 위해 생성 요청의 description 끝에 토큰을 붙여 보내고, 업스트림
응답을 파싱할 때 떼어낸다. 업스트림이 description 을 가공 없이 저장한다는 전제에 기대므로,
그 전제가 깨지면 예외 없이 자동 복구만 멈춘다.
"""
import hashlib
import hmac
import re
from datetime import datetime, timezone
from typing import Optional, Tuple

from app.config import settings

# 업스트림 description 컬럼 한도. 토큰 길이만큼 사용자 입력 한도가 줄어든다.
UPSTREAM_DESCRIPTION_LIMIT = 255

_TOKEN_HEX_LEN = 16
# $ 는 끝의 줄바꿈 앞에서도 맞으므로 문자열 끝은 \Z 로 잡는다.
_TOKEN_RE = re.compile(r"(?:^| )\[kbt:([0-9a-f]{16})\]\Z")
MAX_USER_DESCRIPTION = UPSTREAM_DESCRIPTION_LIMIT - len(" [kbt:]") - _TOKEN_HEX_LEN


def make_token(attempt_id: int, request_id: Optional[str], started_at: datetime) -> str:
    """비밀키 없이는 다른 시도의 토큰을 만들 수 없다.
    JWT 키를 교체하면 그 시점에 살아 있는 시도의 자동 복구가 멈춘다(시도 TTL 동안).

    attempt_id·request_id·started_at 으로 토큰을 만든다.
    DB 복원으로 id 가 재발급되고 X-Request-ID 가 고정돼 있어도 started_at 으로 구분된다.
    시각은 DB 가 naive/aware 어느 쪽으로 돌려줘도 같도록 UTC 로 고정한다."""
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=timezone.utc)
    instant = started_at.astimezone(timezone.utc).isoformat(timespec="microseconds")
    message = f"kb-attempt-token:{attempt_id}:{request_id or ''}:{instant}".encode()
    digest = hmac.new(settings.JWT_SECRET_KEY.encode(), message, hashlib.sha256).hexdigest()
    return digest[:_TOKEN_HEX_LEN]


def attempt_token(attempt) -> str:
    """시도 레코드의 토큰. 생성 요청에 실을 때와 복구·보호 판정이 모두 이 함수를 거쳐야
    같은 값에서 같은 토큰이 나온다."""
    return make_token(attempt.id, attempt.request_id, attempt.started_at)


def attach_token(description: Optional[str], token: str) -> str:
    tag = f"[kbt:{token}]"
    return f"{description} {tag}" if description else tag


def split_token(description: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """(사용자 설명, 토큰). 토큰이 없으면 입력을 그대로 돌려준다."""
    if not description:
        return description, None
    match = _TOKEN_RE.search(description)
    if match is None:
        return description, None
    return description[:match.start()] or None, match.group(1)
