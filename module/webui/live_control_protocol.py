"""实时设备控制 WebSocket 的协议校验与响应构造。"""

from typing import Any


CONTROL_PROTOCOL_VERSION = 2
CONTROL_COORDINATE_WIDTH = 1280
CONTROL_COORDINATE_HEIGHT = 720
CONTROL_ACTIONS = (
    "tap",
    "drag",
    "touch",
    "key",
    "text",
    "back",
    "home",
    "app_switch",
)
CONTROL_TOUCH_PHASES = ("down", "move", "up")


class LiveControlCommandError(ValueError):
    """控制消息不符合公开协议。"""

    def __init__(self, code: str, message: str, command_id: str | int | None = None):
        super().__init__(message)
        self.code = code
        self.command_id = command_id


def ready_message(instance: str) -> dict[str, Any]:
    """构造控制连接就绪消息。"""
    return {
        "type": "ready",
        "protocolVersion": CONTROL_PROTOCOL_VERSION,
        "instance": instance,
        "coordinateSpace": {
            "width": CONTROL_COORDINATE_WIDTH,
            "height": CONTROL_COORDINATE_HEIGHT,
        },
        "actions": list(CONTROL_ACTIONS),
    }


def ack_message(command: dict[str, Any]) -> dict[str, Any]:
    """构造已完成控制操作的确认消息。"""
    response = {"type": "ack", "action": command["type"]}
    if command.get("id") is not None:
        response["id"] = command["id"]
    return response


def error_message(
    code: str,
    message: str,
    command_id: str | int | None = None,
) -> dict[str, Any]:
    """构造稳定的控制错误消息。"""
    response: dict[str, Any] = {"type": "error", "code": code, "message": message}
    if command_id is not None:
        response["id"] = command_id
    return response


def parse_control_command(data: Any) -> dict[str, Any]:
    """校验并标准化浏览器发来的控制消息。"""
    if not isinstance(data, dict):
        raise LiveControlCommandError("invalid_command", "控制消息必须是 JSON 对象")

    command_id = _parse_command_id(data.get("id"))
    action = data.get("type")
    if action not in CONTROL_ACTIONS:
        raise LiveControlCommandError(
            "unsupported_action",
            f"未知控制动作: {action}",
            command_id,
        )

    command: dict[str, Any] = {"type": action}
    if command_id is not None:
        command["id"] = command_id

    if action == "tap":
        command["x"] = _parse_coordinate(
            data.get("x"), "x", CONTROL_COORDINATE_WIDTH, command_id
        )
        command["y"] = _parse_coordinate(
            data.get("y"), "y", CONTROL_COORDINATE_HEIGHT, command_id
        )
    elif action == "drag":
        command["start"] = _parse_point(data.get("start"), "start", command_id)
        command["end"] = _parse_point(data.get("end"), "end", command_id)
        command["duration_ms"] = _parse_integer(
            data.get("duration_ms", 220),
            "duration_ms",
            minimum=40,
            maximum=1500,
            command_id=command_id,
        )
    elif action == "touch":
        phase = data.get("phase")
        if phase not in CONTROL_TOUCH_PHASES:
            raise LiveControlCommandError(
                "invalid_touch_phase",
                f"touch.phase 必须是 {', '.join(CONTROL_TOUCH_PHASES)} 之一",
                command_id,
            )
        command["phase"] = phase
        command["x"] = _parse_coordinate(
            data.get("x"), "x", CONTROL_COORDINATE_WIDTH, command_id
        )
        command["y"] = _parse_coordinate(
            data.get("y"), "y", CONTROL_COORDINATE_HEIGHT, command_id
        )
    elif action == "key":
        keycode = data.get("keycode")
        key = data.get("key")
        if keycode is None and not isinstance(key, str):
            raise LiveControlCommandError(
                "invalid_key",
                "key 操作需要 key 或 keycode",
                command_id,
            )
        if keycode is not None:
            command["keycode"] = _parse_integer(
                keycode,
                "keycode",
                minimum=0,
                maximum=288,
                command_id=command_id,
            )
        if isinstance(key, str):
            if len(key) > 32:
                raise LiveControlCommandError("invalid_key", "key 长度不能超过 32", command_id)
            command["key"] = key
    elif action == "text":
        text = data.get("text", "")
        if not isinstance(text, str):
            raise LiveControlCommandError("invalid_text", "text 必须是字符串", command_id)
        if not text:
            raise LiveControlCommandError("invalid_text", "text 不能为空", command_id)
        if len(text) > 256:
            raise LiveControlCommandError("invalid_text", "text 长度不能超过 256", command_id)
        command["text"] = text

    return command


def _parse_command_id(value: Any) -> str | int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise LiveControlCommandError("invalid_command_id", "id 必须是字符串或整数")
    if isinstance(value, str) and (not value or len(value) > 64):
        raise LiveControlCommandError("invalid_command_id", "id 长度必须在 1 到 64 之间")
    return value


def _parse_point(
    value: Any,
    name: str,
    command_id: str | int | None,
) -> dict[str, int]:
    if not isinstance(value, dict):
        raise LiveControlCommandError(
            "invalid_coordinate",
            f"{name} 必须是坐标对象",
            command_id,
        )
    return {
        "x": _parse_coordinate(
            value.get("x"), f"{name}.x", CONTROL_COORDINATE_WIDTH, command_id
        ),
        "y": _parse_coordinate(
            value.get("y"), f"{name}.y", CONTROL_COORDINATE_HEIGHT, command_id
        ),
    }


def _parse_coordinate(
    value: Any,
    name: str,
    maximum: int,
    command_id: str | int | None,
) -> int:
    return _parse_integer(
        value,
        name,
        minimum=0,
        maximum=maximum,
        command_id=command_id,
        error_code="invalid_coordinate",
    )


def _parse_integer(
    value: Any,
    name: str,
    minimum: int,
    maximum: int,
    command_id: str | int | None,
    error_code: str = "invalid_command",
) -> int:
    if isinstance(value, bool):
        raise LiveControlCommandError(error_code, f"{name} 必须是整数", command_id)
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise LiveControlCommandError(error_code, f"{name} 必须是整数", command_id) from exc
    if parsed < minimum or parsed > maximum:
        raise LiveControlCommandError(
            error_code,
            f"{name} 必须位于 {minimum} 到 {maximum} 之间",
            command_id,
        )
    return parsed
