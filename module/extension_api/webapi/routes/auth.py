"""扩展 API 初始化、登录和访问令牌路由。"""

from __future__ import annotations

import time
from json import JSONDecodeError

from pydantic import ValidationError as PydanticValidationError
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from module.extension_api.auth import AuthPrincipal, ValidationError
from module.extension_api.auth.service import SESSION_COOKIE_NAME
from module.extension_api.errors import InvalidRequestError
from module.extension_api.webapi.models import (
    AuthLoginRequest,
    AuthPasswordResetRequest,
    AuthSessionResponse,
    AuthSetupRequest,
    AuthStatusResponse,
    AuthUserResponse,
    ClientTokenCreateRequest,
    ClientTokenListResponse,
    ClientTokenResponse,
    WebSocketTicketRequest,
    WebSocketTicketResponse,
)
from module.extension_api.webapi.responses import model_response


async def get_auth_status(request: Request) -> JSONResponse:
    initialized = await run_in_threadpool(
        lambda: request.app.state.auth_service.initialized
    )
    return _no_store(
        model_response(
            AuthStatusResponse(
                initialized=initialized,
                setup_required=not initialized,
                password_reset_available=(
                    request.app.state.auth_service.password_reset_available
                    if initialized
                    else False
                ),
            )
        )
    )


async def setup_auth(request: Request) -> JSONResponse:
    payload = await _parse_request(request, AuthSetupRequest, "初始化请求体无效")
    credential = await run_in_threadpool(
        request.app.state.auth_service.setup,
        bootstrap_token=payload.bootstrap_token,
        username=payload.username,
        password=payload.password,
        rate_limit_key=_rate_limit_key(request, "setup"),
    )
    response = model_response(
        AuthSessionResponse(
            authenticated=True,
            user=_serialize_principal(credential.principal),
            expires_at_ms=credential.expires_at * 1000,
        ),
        status_code=201,
    )
    _set_session_cookie(request, response, credential.token, credential.expires_at)
    return _no_store(response)


async def login(request: Request) -> JSONResponse:
    payload = await _parse_request(request, AuthLoginRequest, "登录请求体无效")
    credential = await run_in_threadpool(
        request.app.state.auth_service.login,
        username=payload.username,
        password=payload.password,
        rate_limit_key=_rate_limit_key(request, "login"),
    )
    response = model_response(
        AuthSessionResponse(
            authenticated=True,
            user=_serialize_principal(credential.principal),
            expires_at_ms=credential.expires_at * 1000,
        )
    )
    _set_session_cookie(request, response, credential.token, credential.expires_at)
    return _no_store(response)


async def reset_password(request: Request) -> JSONResponse:
    payload = await _parse_request(
        request, AuthPasswordResetRequest, "密码重置请求体无效"
    )
    credential = await run_in_threadpool(
        request.app.state.auth_service.reset_password,
        reset_token=payload.reset_token,
        password=payload.password,
        rate_limit_key=_rate_limit_key(request, "password-reset"),
    )
    response = model_response(
        AuthSessionResponse(
            authenticated=True,
            user=_serialize_principal(credential.principal),
            expires_at_ms=credential.expires_at * 1000,
        )
    )
    _set_session_cookie(request, response, credential.token, credential.expires_at)
    return _no_store(response)


async def logout(request: Request) -> Response:
    await run_in_threadpool(
        request.app.state.auth_service.logout,
        request.cookies.get(SESSION_COOKIE_NAME),
    )
    response = Response(status_code=204)
    response.delete_cookie(SESSION_COOKIE_NAME, path="/", samesite="strict")
    return _no_store(response)


async def get_session(request: Request) -> JSONResponse:
    principal = getattr(request.state, "auth_principal", None)
    return _no_store(
        model_response(
            AuthSessionResponse(
                authenticated=principal is not None,
                user=_serialize_principal(principal) if principal else None,
            )
        )
    )


async def create_client_token(request: Request) -> JSONResponse:
    payload = await _parse_request(
        request, ClientTokenCreateRequest, "客户端令牌请求体无效"
    )
    principal = _request_principal(request)
    expires_at = (
        payload.expires_at_ms // 1000 if payload.expires_at_ms is not None else None
    )
    credential = await run_in_threadpool(
        request.app.state.auth_service.create_client_token,
        principal=principal,
        name=payload.name,
        scopes=payload.scopes,
        expires_at=expires_at,
    )
    return _no_store(
        model_response(
            ClientTokenResponse(
                id=credential.token_id,
                name=credential.name,
                scopes=sorted(credential.scopes),
                created_at_ms=credential.created_at * 1000,
                token=credential.token,
            ),
            status_code=201,
        ),
    )


async def list_client_tokens(request: Request) -> JSONResponse:
    tokens = await run_in_threadpool(
        request.app.state.auth_service.list_client_tokens,
        _request_principal(request),
    )
    return _no_store(
        model_response(
            ClientTokenListResponse(
                items=[
                    ClientTokenResponse(
                        id=token.token_id,
                        name=token.name,
                        scopes=sorted(token.scopes),
                        created_at_ms=token.created_at * 1000,
                        last_used_at_ms=(
                            token.last_used_at * 1000
                            if token.last_used_at is not None
                            else None
                        ),
                        expires_at_ms=(
                            token.expires_at * 1000
                            if token.expires_at is not None
                            else None
                        ),
                    )
                    for token in tokens
                ]
            )
        )
    )


async def revoke_client_token(request: Request) -> Response:
    revoked = await run_in_threadpool(
        request.app.state.auth_service.revoke_client_token,
        _request_principal(request),
        request.path_params["token_id"],
    )
    if not revoked:
        raise ValidationError("客户端令牌不存在或已经撤销")
    return _no_store(Response(status_code=204))


async def create_websocket_ticket(request: Request) -> JSONResponse:
    payload = await _parse_request(
        request, WebSocketTicketRequest, "WebSocket 票据请求体无效"
    )
    ticket = await run_in_threadpool(
        request.app.state.auth_service.create_websocket_ticket,
        principal=_request_principal(request),
        purpose=payload.purpose,
        instance=payload.instance,
    )
    return _no_store(
        model_response(
            WebSocketTicketResponse(
                ticket=ticket.ticket,
                purpose=ticket.purpose,
                instance=ticket.instance,
                expires_at_ms=ticket.expires_at * 1000,
            ),
            status_code=201,
        ),
    )


async def _parse_request(request: Request, model_type, message: str):
    try:
        return model_type.model_validate(await request.json())
    except (
        JSONDecodeError,
        TypeError,
        UnicodeDecodeError,
        PydanticValidationError,
    ) as exc:
        raise InvalidRequestError(message) from exc


def _request_principal(request: Request) -> AuthPrincipal:
    principal = getattr(request.state, "auth_principal", None)
    if not isinstance(principal, AuthPrincipal):
        raise TypeError("受保护路由缺少鉴权上下文")
    return principal


def _serialize_principal(principal: AuthPrincipal) -> AuthUserResponse:
    return AuthUserResponse(
        username=principal.username,
        scopes=sorted(principal.scopes),
        auth_type=principal.auth_type,
    )


def _set_session_cookie(
    request: Request, response: Response, token: str, expires_at: int
) -> None:
    forwarded_proto = request.headers.get("x-forwarded-proto", "")
    secure = (
        request.url.scheme == "https" or forwarded_proto.split(",", 1)[0] == "https"
    )
    max_age = max(0, expires_at - int(time.time()))
    response.set_cookie(
        SESSION_COOKIE_NAME,
        token,
        max_age=max_age,
        httponly=True,
        secure=secure,
        samesite="strict",
        path="/",
    )


def _rate_limit_key(request: Request, action: str) -> str:
    client = request.client.host if request.client else "unknown"
    return f"{action}:{client}"


def _no_store(response: Response):
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    return response
