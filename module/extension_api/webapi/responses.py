"""REST API 响应辅助函数。"""

from pydantic import BaseModel
from starlette.responses import JSONResponse


def model_response(model: BaseModel, status_code: int = 200) -> JSONResponse:
    return JSONResponse(
        model.model_dump(mode="json", by_alias=True),
        status_code=status_code,
    )
