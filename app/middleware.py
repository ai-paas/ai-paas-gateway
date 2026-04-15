import logging
import time
import uuid

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from app.auth import AuthService
from app.config import settings
from app.logging_config import get_access_logger

_fallback_logger = logging.getLogger(__name__)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start_time = time.perf_counter()
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = request_id

        response: Response | None = None
        status_code = 500

        try:
            response = await call_next(request)
            status_code = response.status_code
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            try:
                log_data = self._build_log_data(request, request_id, status_code, start_time)
                get_access_logger().info("access", extra={"event_data": log_data})
            except Exception:
                _fallback_logger.exception("Failed to write access log")

    def _build_log_data(
        self,
        request: Request,
        request_id: str,
        status_code: int,
        start_time: float,
    ) -> dict:
        duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
        path = request.url.path
        is_masked_path = path in settings.LOG_ACCESS_MASK_PATHS

        member_id = "masked" if is_masked_path else self._extract_member_id(request)
        query_string = "-" if is_masked_path else (request.url.query or "-")

        data = {
            "request_id": request_id,
            "method": request.method,
            "path": path,
            "query": query_string,
            "status": status_code,
            "duration_ms": duration_ms,
            "client_ip": self._extract_client_ip(request),
            "member_id": member_id,
            "user_agent": request.headers.get("user-agent", "-"),
        }
        if is_masked_path:
            data["masked"] = True
        return data

    @staticmethod
    def _extract_client_ip(request: Request) -> str:
        forwarded_for = request.headers.get("x-forwarded-for")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()

        if request.client:
            return request.client.host

        return "-"

    @staticmethod
    def _extract_member_id(request: Request) -> str:
        state_member_id = getattr(request.state, "member_id", None)
        if state_member_id:
            return state_member_id

        authorization = request.headers.get("authorization")
        if not authorization or not authorization.lower().startswith("bearer "):
            return "anonymous"

        token = authorization.split(" ", 1)[1].strip()
        if not token:
            return "anonymous"

        try:
            token_data = AuthService.verify_token(token)
            return token_data.get("member_id", "anonymous")
        except Exception:
            return "anonymous"
