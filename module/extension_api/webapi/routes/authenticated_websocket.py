"""在扩展 API 命名空间内保护原有实时 WebSocket 处理器。"""

from __future__ import annotations

from starlette.concurrency import run_in_threadpool
from starlette.websockets import WebSocket

from module.extension_api.auth import AuthServiceError


async def live_screenshot_websocket(websocket: WebSocket) -> None:
    if not await _consume_ticket(websocket, "live_screenshot"):
        return
    # 原处理器保持不变；适配层只负责在调用之前完成鉴权。
    from module.webui.api import ws_live_screenshot

    await ws_live_screenshot(websocket)


async def live_control_websocket(websocket: WebSocket) -> None:
    if not await _consume_ticket(websocket, "live_control"):
        return
    # 原处理器保持不变；适配层只负责在调用之前完成鉴权。
    from module.webui.api import ws_live_control

    await ws_live_control(websocket)


async def _consume_ticket(websocket: WebSocket, purpose: str) -> bool:
    ticket = websocket.query_params.get("ticket", "")
    instance = websocket.query_params.get("instance", "")
    try:
        principal = await run_in_threadpool(
            websocket.app.state.auth_service.consume_websocket_ticket,
            ticket=ticket,
            purpose=purpose,
            instance=instance,
        )
    except AuthServiceError:
        # 在 accept 之前拒绝，确保无效连接无法占用截图或设备控制资源。
        await websocket.close(code=4401, reason="WebSocket authentication failed")
        return False
    websocket.scope["auth_principal"] = principal
    return True
