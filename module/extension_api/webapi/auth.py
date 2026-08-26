"""Starlette 路由级鉴权包装器。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from functools import wraps
from urllib.parse import urlsplit

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import Response

from module.extension_api.auth import PermissionDeniedError
from module.extension_api.auth.service import SESSION_COOKIE_NAME

Endpoint = Callable[[Request], Awaitable[Response]]


def protected(endpoint: Endpoint, scope: str | None = None) -> Endpoint:
    """在执行传输层路由之前验证会话或 Bearer 客户端令牌。"""

    @wraps(endpoint)
    async def wrapped(request: Request) -> Response:
        bearer_token = _read_bearer_token(request)
        session_token = request.cookies.get(SESSION_COOKIE_NAME)
        principal = await run_in_threadpool(
            request.app.state.auth_service.authenticate,
            session_token=session_token,
            bearer_token=bearer_token,
        )
        if scope:
            principal.require(scope)
        if session_token and request.method not in {"GET", "HEAD", "OPTIONS"}:
            _validate_same_origin(request)
        request.state.auth_principal = principal
        return await endpoint(request)

    return wrapped


async def attach_optional_principal(request: Request) -> None:
    """为会话探测接口附加身份，但不把未登录当成异常。"""
    from module.extension_api.auth import AuthServiceError

    try:
        request.state.auth_principal = await run_in_threadpool(
            request.app.state.auth_service.authenticate,
            session_token=request.cookies.get(SESSION_COOKIE_NAME),
            bearer_token=_read_bearer_token(request),
        )
    except AuthServiceError:
        request.state.auth_principal = None


def optional_auth(endpoint: Endpoint) -> Endpoint:
    @wraps(endpoint)
    async def wrapped(request: Request) -> Response:
        await attach_optional_principal(request)
        return await endpoint(request)

    return wrapped


def _read_bearer_token(request: Request) -> str | None:
    authorization = request.headers.get("authorization", "")
    if not authorization:
        return None
    scheme, separator, token = authorization.partition(" ")
    if separator and scheme.lower() == "bearer" and token.strip():
        return token.strip()
    return None


def _validate_same_origin(request: Request) -> None:
    """Cookie 写请求存在 Origin 时只允许同源，降低跨站请求风险。"""
    origin = request.headers.get("origin")
    if not origin:
        return
    parsed = urlsplit(origin)
    expected_host = request.headers.get("host", "").lower()
    if parsed.scheme not in {"http", "https"} or parsed.netloc.lower() != expected_host:
        raise PermissionDeniedError("拒绝跨站写请求")
