"""实例实时截图媒体连接描述路由。"""

from starlette.requests import Request
from starlette.responses import JSONResponse

from module.extension_api.webapi.models import LiveScreenshotStreamResponse
from module.extension_api.webapi.responses import model_response


async def get_live_screenshot_stream(request: Request) -> JSONResponse:
    """返回媒体连接元数据；高频截图帧仍由独立 WebSocket 传输。"""
    instance = request.path_params["instance"]
    request.app.state.instance_service.get(instance)
    return model_response(LiveScreenshotStreamResponse(instance=instance))
