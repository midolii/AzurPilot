"""从 AzurPilot 本机生成短期密码重置令牌。"""

from __future__ import annotations

from datetime import datetime

from module.extension_api.auth import AuthService, SetupRequiredError


def main() -> int:
    """生成一次性令牌并输出后续操作说明。"""
    service = AuthService()
    try:
        challenge = service.request_password_reset()
    except SetupRequiredError as exc:
        print(f"无法生成密码重置令牌：{exc}")
        return 1

    expires_at = datetime.fromtimestamp(challenge.expires_at).astimezone()
    print("已生成一次性密码重置令牌，有效期 15 分钟。")
    print(f"重置令牌：{challenge.token}")
    print(f"失效时间：{expires_at:%Y-%m-%d %H:%M:%S %z}")
    print(f"凭据文件：{service.password_reset_path.resolve()}")
    print("请在 Janus 登录页选择“忘记密码”，完成后该令牌会立即失效。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
