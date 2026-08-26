import unittest

from module.webui.live_control_protocol import (
    LiveControlCommandError,
    ack_message,
    error_message,
    parse_control_command,
    ready_message,
)


class TestLiveControlProtocol(unittest.TestCase):
    def test_ready_message_describes_stable_coordinate_space(self):
        message = ready_message("alas")

        self.assertEqual("ready", message["type"])
        self.assertEqual(1, message["protocolVersion"])
        self.assertEqual({"width": 1280, "height": 720}, message["coordinateSpace"])
        self.assertIn("tap", message["actions"])
        self.assertIn("app_switch", message["actions"])

    def test_parse_tap_and_drag_commands(self):
        tap = parse_control_command({"id": "tap-1", "type": "tap", "x": 640, "y": 360})
        drag = parse_control_command({
            "id": 2,
            "type": "drag",
            "start": {"x": 100, "y": 200},
            "end": {"x": 900, "y": 500},
            "duration_ms": 300,
        })

        self.assertEqual(
            {"id": "tap-1", "type": "tap", "x": 640, "y": 360},
            tap,
        )
        self.assertEqual(300, drag["duration_ms"])
        self.assertEqual({"x": 900, "y": 500}, drag["end"])

    def test_rejects_out_of_bounds_and_oversized_input(self):
        with self.assertRaisesRegex(LiveControlCommandError, "x 必须位于") as context:
            parse_control_command({"id": "tap-1", "type": "tap", "x": 1281, "y": 0})
        self.assertEqual(context.exception.command_id, "tap-1")
        with self.assertRaisesRegex(LiveControlCommandError, "长度不能超过 256"):
            parse_control_command({"type": "text", "text": "字" * 257})
        with self.assertRaisesRegex(LiveControlCommandError, "未知控制动作"):
            parse_control_command({"type": "power"})

    def test_ack_and_error_preserve_command_id(self):
        command = parse_control_command({"id": "42", "type": "back"})

        self.assertEqual(
            {"type": "ack", "action": "back", "id": "42"},
            ack_message(command),
        )
        self.assertEqual(
            {"type": "error", "code": "failed", "message": "失败", "id": "42"},
            error_message("failed", "失败", "42"),
        )


if __name__ == "__main__":
    unittest.main()
