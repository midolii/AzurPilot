"""REST API 请求与响应模型。"""

from pydantic import BaseModel, ConfigDict


def _to_camel(value: str) -> str:
    head, *tail = value.split("_")
    return head + "".join(part.capitalize() for part in tail)


class ApiModel(BaseModel):
    """统一使用 camelCase 输出，便于独立 Web 客户端消费。"""

    model_config = ConfigDict(
        alias_generator=_to_camel,
        from_attributes=True,
        populate_by_name=True,
    )


class HealthResponse(ApiModel):
    status: str = "ok"
    api_version: str


class SystemResponse(ApiModel):
    api_version: str
    core_commit: str
    python_version: str
    platform: str
    capabilities: list[str]


class InstanceResponse(ApiModel):
    name: str
    module: str
    running: bool
    state: str


class InstanceListResponse(ApiModel):
    items: list[InstanceResponse]


class ErrorDetail(ApiModel):
    code: str
    message: str


class ErrorResponse(ApiModel):
    error: ErrorDetail
