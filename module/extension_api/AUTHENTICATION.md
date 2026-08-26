# 扩展 API 鉴权

`/api/v1` 使用独立的 SQLite 鉴权层，不修改 AzurPilot 原有 WebUI 密码逻辑，也不修改
原有 `/ws/*` WebSocket 处理器和协议。

## 安全默认值

- 首次启动会在 `config/extension-api-bootstrap.txt` 生成一次性初始化令牌。
- 业务接口在初始化完成前统一返回 `setup_required`。
- 初始化成功后令牌文件立即删除，账号密码以 scrypt 哈希保存在
  `config/extension-api-auth.db`。
- 会话使用 `HttpOnly`、`SameSite=Strict` Cookie；经 HTTPS 网关访问时自动增加
  `Secure`。
- 客户端令牌只保存 SHA-256 摘要，明文只在创建响应中返回一次。
- 实时截图和设备控制使用 30 秒有效、单次使用、绑定实例与用途的 WebSocket 票据。

数据库和初始化令牌路径可分别通过 `AZURPILOT_EXTENSION_AUTH_DB` 与
`AZURPILOT_EXTENSION_BOOTSTRAP_FILE` 修改。密码重置凭据路径可通过
`AZURPILOT_EXTENSION_PASSWORD_RESET_FILE` 修改。

## 忘记密码

密码不能通过公开接口直接找回。请先在运行 AzurPilot 的机器上执行：

```bash
uv run python -m module.extension_api.auth.password_reset
```

命令会生成一个有效期 15 分钟的一次性令牌；将它输入 Janus 登录页的“忘记密码”
表单即可设置新密码。成功后令牌立即删除，已有网页登录会话和 WebSocket 票据全部
失效。该流程不开放远程生成令牌的接口，因此只拥有公网 Janus 地址的人无法发起重置。

## 路由边界

- 公开：`GET /api/v1/health`、`GET /api/v1/auth/status`、初始化、登录和使用本机令牌重置密码。
- 会话：`GET /api/v1/auth/session`、`POST /api/v1/auth/logout`。
- 客户端令牌：`/api/v1/auth/tokens`。
- WebSocket 票据：`POST /api/v1/auth/ws-tickets`。
- 受保护媒体适配器：`/api/v1/ws/live_screenshot`、`/api/v1/ws/live_control`。

受保护媒体适配器只在票据校验成功后调用 `module.webui.api` 中原有处理器。部署网关
必须只公开 `/api/v1/*`，不得公开原有 `/ws/*`。

## 启动建议

同机部署时显式绑定回环地址：

```bash
uv run python gui.py --host 127.0.0.1 --port 25548
```

跨机器部署时也应绑定明确的私有接口地址，并通过受控连接器接入网关；不要监听
`0.0.0.0` 或 `::`。
