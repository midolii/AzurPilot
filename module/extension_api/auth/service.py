"""基于 SQLite 的扩展 API 鉴权服务。"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import threading
import time
import uuid
from collections import defaultdict, deque
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

SESSION_COOKIE_NAME = "azurpilot_session"
SESSION_TTL_SECONDS = 30 * 24 * 60 * 60
WEBSOCKET_TICKET_TTL_SECONDS = 30
PASSWORD_RESET_TTL_SECONDS = 15 * 60
PASSWORD_SCRYPT_N = 2**14
PASSWORD_SCRYPT_R = 8
PASSWORD_SCRYPT_P = 1
PASSWORD_HASH_LENGTH = 32
USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{3,64}$")
DUMMY_PASSWORD_HASH = (
    "scrypt$16384$8$1$00112233445566778899aabbccddeeff$"
    "f7299bbd4cd75c64fc6ef9209cc8a20567ac8b8cbd306a7b3d190b089bdd6cf4"
)

ALL_AUTH_SCOPES = frozenset(
    {
        "system:read",
        "instances:read",
        "instances:operate",
        "config:read",
        "config:write",
        "tasks:read",
        "tasks:run",
        "logs:read",
        "statistics:read",
        "media:view",
        "device:control",
        "core:update",
        "tokens:manage",
    }
)


class AuthServiceError(Exception):
    """鉴权服务的可预期错误。"""


class SetupRequiredError(AuthServiceError):
    """扩展 API 尚未完成初始化。"""


class SetupAlreadyCompletedError(AuthServiceError):
    """扩展 API 已经完成初始化。"""


class BootstrapTokenError(AuthServiceError):
    """一次性初始化令牌无效。"""


class PasswordResetTokenError(AuthServiceError):
    """本机生成的密码重置令牌无效或已过期。"""


class AuthenticationRequiredError(AuthServiceError):
    """当前请求没有有效身份。"""


class PermissionDeniedError(AuthServiceError):
    """当前身份缺少所需权限。"""


class RateLimitExceededError(AuthServiceError):
    """请求频率超过限制。"""


class ValidationError(AuthServiceError):
    """鉴权请求参数不符合约束。"""


@dataclass(frozen=True, slots=True)
class AuthPrincipal:
    """已经通过校验的调用方身份。"""

    subject_id: str
    username: str
    scopes: frozenset[str]
    auth_type: str

    def require(self, scope: str) -> None:
        if scope not in self.scopes:
            raise PermissionDeniedError(f"缺少权限: {scope}")


@dataclass(frozen=True, slots=True)
class SessionCredential:
    token: str
    expires_at: int
    principal: AuthPrincipal


@dataclass(frozen=True, slots=True)
class ClientTokenCredential:
    token_id: str
    token: str
    name: str
    scopes: frozenset[str]
    created_at: int


@dataclass(frozen=True, slots=True)
class ClientTokenSummary:
    token_id: str
    name: str
    scopes: frozenset[str]
    created_at: int
    last_used_at: int | None
    expires_at: int | None


@dataclass(frozen=True, slots=True)
class WebSocketTicket:
    ticket: str
    purpose: str
    instance: str
    expires_at: int


@dataclass(frozen=True, slots=True)
class PasswordResetChallenge:
    """仅能由 AzurPilot 本机生成的短期密码重置凭据。"""

    token: str
    expires_at: int


class _AttemptLimiter:
    """单进程内的轻量限速器，避免登录接口被高速尝试。"""

    def __init__(self, limit: int = 8, window_seconds: int = 60):
        self.limit = limit
        self.window_seconds = window_seconds
        self._attempts: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str) -> None:
        now = time.monotonic()
        with self._lock:
            attempts = self._attempts[key]
            threshold = now - self.window_seconds
            while attempts and attempts[0] <= threshold:
                attempts.popleft()
            if len(attempts) >= self.limit:
                raise RateLimitExceededError("尝试次数过多，请稍后再试")
            attempts.append(now)

    def clear(self, key: str) -> None:
        with self._lock:
            self._attempts.pop(key, None)


class AuthService:
    """管理本地账号、会话、客户端令牌和一次性 WebSocket 票据。"""

    def __init__(
        self,
        database_path: str | Path | None = None,
        bootstrap_path: str | Path | None = None,
        password_reset_path: str | Path | None = None,
        now: Callable[[], int] | None = None,
    ):
        configured_database = os.environ.get(
            "AZURPILOT_EXTENSION_AUTH_DB", "config/extension-api-auth.db"
        )
        configured_bootstrap = os.environ.get(
            "AZURPILOT_EXTENSION_BOOTSTRAP_FILE",
            "config/extension-api-bootstrap.txt",
        )
        configured_password_reset = os.environ.get(
            "AZURPILOT_EXTENSION_PASSWORD_RESET_FILE",
            "config/extension-api-password-reset.json",
        )
        self.database_path = Path(database_path or configured_database)
        self.bootstrap_path = Path(bootstrap_path or configured_bootstrap)
        self.password_reset_path = Path(
            password_reset_path or configured_password_reset
        )
        self._now = now or (lambda: int(time.time()))
        self._write_lock = threading.RLock()
        self._login_limiter = _AttemptLimiter()
        self._setup_limiter = _AttemptLimiter(limit=5, window_seconds=300)
        self._password_reset_limiter = _AttemptLimiter(limit=5, window_seconds=300)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.bootstrap_path.parent.mkdir(parents=True, exist_ok=True)
        self.password_reset_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize_database()
        self._synchronize_bootstrap_file()

    @property
    def initialized(self) -> bool:
        with self._connect() as connection:
            row = connection.execute("SELECT 1 FROM users LIMIT 1").fetchone()
        return row is not None

    def read_bootstrap_token(self) -> str | None:
        """读取本机一次性令牌；仅供本机初始化流程和测试使用。"""
        try:
            return self.bootstrap_path.read_text(encoding="utf-8").strip() or None
        except FileNotFoundError:
            return None

    @property
    def password_reset_available(self) -> bool:
        """返回当前是否存在尚未过期的本机密码重置凭据。"""
        challenge = self._read_password_reset_challenge()
        return bool(challenge and challenge.expires_at > self._now())

    def request_password_reset(self) -> PasswordResetChallenge:
        """在本机生成短期一次性重置令牌；此方法不通过 HTTP 暴露。"""
        if not self.initialized:
            raise SetupRequiredError("扩展 API 尚未初始化")

        challenge = PasswordResetChallenge(
            token=f"azr_{secrets.token_urlsafe(32)}",
            expires_at=self._now() + PASSWORD_RESET_TTL_SECONDS,
        )
        self._write_restricted_json(
            self.password_reset_path,
            {"token": challenge.token, "expiresAt": challenge.expires_at},
        )
        return challenge

    def reset_password(
        self,
        *,
        reset_token: str,
        password: str,
        rate_limit_key: str,
    ) -> SessionCredential:
        """使用本机短期凭据重置唯一管理员密码，并注销已有会话。"""
        if not self.initialized:
            raise SetupRequiredError("扩展 API 尚未初始化")
        self._password_reset_limiter.check(rate_limit_key)
        self._validate_password(password)
        challenge = self._read_password_reset_challenge()
        expected_token = challenge.token if challenge else secrets.token_urlsafe(32)
        token_valid = secrets.compare_digest(reset_token, expected_token)
        if not challenge or challenge.expires_at <= self._now() or not token_valid:
            raise PasswordResetTokenError("密码重置令牌无效或已过期")

        now = self._now()
        password_hash = self._hash_password(password)
        with self._write_lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT id, username, scopes FROM users LIMIT 1"
            ).fetchone()
            if row is None:
                connection.rollback()
                raise SetupRequiredError("扩展 API 尚未初始化")
            connection.execute(
                "UPDATE users SET password_hash = ? WHERE id = ?",
                (password_hash, row["id"]),
            )
            connection.execute("DELETE FROM sessions WHERE user_id = ?", (row["id"],))
            connection.execute(
                "DELETE FROM websocket_tickets WHERE user_id = ?", (row["id"],)
            )
            self._write_audit(
                connection,
                actor_id=row["id"],
                action="auth.password.reset",
                detail={},
                created_at=now,
            )
            credential = self._create_session(
                connection,
                user_id=row["id"],
                username=row["username"],
                now=now,
                scopes=self._parse_scopes(row["scopes"]),
            )
            connection.commit()

        self.password_reset_path.unlink(missing_ok=True)
        self._password_reset_limiter.clear(rate_limit_key)
        return credential

    def setup(
        self,
        *,
        bootstrap_token: str,
        username: str,
        password: str,
        rate_limit_key: str,
    ) -> SessionCredential:
        self._setup_limiter.check(rate_limit_key)
        username = self._validate_username(username)
        self._validate_password(password)
        expected_token = self.read_bootstrap_token()
        if not expected_token or not secrets.compare_digest(
            bootstrap_token, expected_token
        ):
            raise BootstrapTokenError("初始化令牌无效")

        now = self._now()
        user_id = str(uuid.uuid4())
        password_hash = self._hash_password(password)
        scopes_json = self._serialize_scopes(ALL_AUTH_SCOPES)
        with self._write_lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if connection.execute("SELECT 1 FROM users LIMIT 1").fetchone():
                connection.rollback()
                raise SetupAlreadyCompletedError("扩展 API 已完成初始化")
            connection.execute(
                """
                INSERT INTO users (id, username, password_hash, scopes, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (user_id, username, password_hash, scopes_json, now),
            )
            self._write_audit(
                connection,
                actor_id=user_id,
                action="auth.setup",
                detail={"username": username},
                created_at=now,
            )
            credential = self._create_session(
                connection, user_id=user_id, username=username, now=now
            )
            connection.commit()

        self._setup_limiter.clear(rate_limit_key)
        self.bootstrap_path.unlink(missing_ok=True)
        self.password_reset_path.unlink(missing_ok=True)
        return credential

    def login(
        self, *, username: str, password: str, rate_limit_key: str
    ) -> SessionCredential:
        if not self.initialized:
            raise SetupRequiredError("扩展 API 尚未初始化")
        self._login_limiter.check(rate_limit_key)
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT id, username, password_hash, scopes
                FROM users
                WHERE username = ? COLLATE NOCASE
                """,
                (username.strip(),),
            ).fetchone()
        password_hash = row["password_hash"] if row is not None else DUMMY_PASSWORD_HASH
        password_valid = self._verify_password(password, password_hash)
        if row is None or not password_valid:
            raise AuthenticationRequiredError("用户名或密码错误")

        now = self._now()
        with self._write_lock, self._connect() as connection:
            credential = self._create_session(
                connection,
                user_id=row["id"],
                username=row["username"],
                now=now,
                scopes=self._parse_scopes(row["scopes"]),
            )
            self._write_audit(
                connection,
                actor_id=row["id"],
                action="auth.login",
                detail={},
                created_at=now,
            )
            connection.commit()
        self._login_limiter.clear(rate_limit_key)
        return credential

    def authenticate(
        self, *, session_token: str | None = None, bearer_token: str | None = None
    ) -> AuthPrincipal:
        if not self.initialized:
            raise SetupRequiredError("扩展 API 尚未初始化")
        token = bearer_token or session_token
        if not token:
            raise AuthenticationRequiredError("请先登录")
        now = self._now()
        token_hash = self._token_digest(token)
        if bearer_token:
            principal = self._authenticate_client_token(token_hash, now)
        else:
            principal = self._authenticate_session(token_hash, now)
        if principal is None:
            raise AuthenticationRequiredError("登录状态无效或已过期")
        return principal

    def logout(self, session_token: str | None) -> None:
        if not session_token:
            return
        with self._write_lock, self._connect() as connection:
            connection.execute(
                "DELETE FROM sessions WHERE token_hash = ?",
                (self._token_digest(session_token),),
            )
            connection.commit()

    def create_client_token(
        self,
        *,
        principal: AuthPrincipal,
        name: str,
        scopes: Iterable[str],
        expires_at: int | None = None,
    ) -> ClientTokenCredential:
        principal.require("tokens:manage")
        name = name.strip()
        if not 1 <= len(name) <= 80:
            raise ValidationError("令牌名称长度必须为 1 到 80 个字符")
        selected_scopes = frozenset(scopes)
        if not selected_scopes or not selected_scopes.issubset(ALL_AUTH_SCOPES):
            raise ValidationError("令牌权限范围无效")
        if not selected_scopes.issubset(principal.scopes):
            raise PermissionDeniedError("不能签发超出当前账号权限的令牌")
        now = self._now()
        if expires_at is not None and expires_at <= now:
            raise ValidationError("令牌过期时间必须晚于当前时间")
        token_id = str(uuid.uuid4())
        token = f"azp_{secrets.token_urlsafe(32)}"
        with self._write_lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO client_tokens (
                    id, name, token_hash, user_id, scopes, created_at, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    token_id,
                    name,
                    self._token_digest(token),
                    principal.subject_id,
                    self._serialize_scopes(selected_scopes),
                    now,
                    expires_at,
                ),
            )
            self._write_audit(
                connection,
                actor_id=principal.subject_id,
                action="auth.token.create",
                detail={"name": name, "scopes": sorted(selected_scopes)},
                created_at=now,
            )
            connection.commit()
        return ClientTokenCredential(
            token_id=token_id,
            token=token,
            name=name,
            scopes=selected_scopes,
            created_at=now,
        )

    def list_client_tokens(
        self, principal: AuthPrincipal
    ) -> tuple[ClientTokenSummary, ...]:
        principal.require("tokens:manage")
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, name, scopes, created_at, last_used_at, expires_at
                FROM client_tokens
                WHERE user_id = ? AND revoked_at IS NULL
                ORDER BY created_at DESC
                """,
                (principal.subject_id,),
            ).fetchall()
        return tuple(
            ClientTokenSummary(
                token_id=row["id"],
                name=row["name"],
                scopes=self._parse_scopes(row["scopes"]),
                created_at=row["created_at"],
                last_used_at=row["last_used_at"],
                expires_at=row["expires_at"],
            )
            for row in rows
        )

    def revoke_client_token(self, principal: AuthPrincipal, token_id: str) -> bool:
        principal.require("tokens:manage")
        now = self._now()
        with self._write_lock, self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE client_tokens
                SET revoked_at = ?
                WHERE id = ? AND user_id = ? AND revoked_at IS NULL
                """,
                (now, token_id, principal.subject_id),
            )
            if cursor.rowcount:
                self._write_audit(
                    connection,
                    actor_id=principal.subject_id,
                    action="auth.token.revoke",
                    detail={"tokenId": token_id},
                    created_at=now,
                )
            connection.commit()
        return bool(cursor.rowcount)

    def create_websocket_ticket(
        self, *, principal: AuthPrincipal, purpose: str, instance: str
    ) -> WebSocketTicket:
        required_scope = self._scope_for_websocket_purpose(purpose)
        principal.require(required_scope)
        instance = instance.strip()
        if not instance or len(instance) > 128:
            raise ValidationError("实例名称无效")
        now = self._now()
        expires_at = now + WEBSOCKET_TICKET_TTL_SECONDS
        ticket = f"azw_{secrets.token_urlsafe(32)}"
        with self._write_lock, self._connect() as connection:
            connection.execute(
                "DELETE FROM websocket_tickets WHERE expires_at <= ?", (now,)
            )
            connection.execute(
                """
                INSERT INTO websocket_tickets (
                    token_hash, user_id, purpose, instance, created_at, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    self._token_digest(ticket),
                    principal.subject_id,
                    purpose,
                    instance,
                    now,
                    expires_at,
                ),
            )
            connection.commit()
        return WebSocketTicket(
            ticket=ticket,
            purpose=purpose,
            instance=instance,
            expires_at=expires_at,
        )

    def consume_websocket_ticket(
        self, *, ticket: str, purpose: str, instance: str
    ) -> AuthPrincipal:
        required_scope = self._scope_for_websocket_purpose(purpose)
        now = self._now()
        token_hash = self._token_digest(ticket)
        with self._write_lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT
                    websocket_tickets.user_id,
                    websocket_tickets.purpose,
                    websocket_tickets.instance,
                    websocket_tickets.expires_at,
                    websocket_tickets.used_at,
                    users.username,
                    users.scopes
                FROM websocket_tickets
                JOIN users ON users.id = websocket_tickets.user_id
                WHERE websocket_tickets.token_hash = ?
                """,
                (token_hash,),
            ).fetchone()
            valid = bool(
                row
                and row["used_at"] is None
                and row["expires_at"] > now
                and row["purpose"] == purpose
                and row["instance"] == instance
            )
            if not valid:
                connection.rollback()
                raise AuthenticationRequiredError("WebSocket 票据无效或已过期")
            connection.execute(
                "UPDATE websocket_tickets SET used_at = ? WHERE token_hash = ?",
                (now, token_hash),
            )
            connection.commit()
        principal = AuthPrincipal(
            subject_id=row["user_id"],
            username=row["username"],
            scopes=self._parse_scopes(row["scopes"]),
            auth_type="websocket_ticket",
        )
        principal.require(required_scope)
        return principal

    def _authenticate_session(self, token_hash: str, now: int) -> AuthPrincipal | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT users.id, users.username, users.scopes
                FROM sessions
                JOIN users ON users.id = sessions.user_id
                WHERE sessions.token_hash = ? AND sessions.expires_at > ?
                """,
                (token_hash, now),
            ).fetchone()
        if row is None:
            return None
        return AuthPrincipal(
            subject_id=row["id"],
            username=row["username"],
            scopes=self._parse_scopes(row["scopes"]),
            auth_type="session",
        )

    def _authenticate_client_token(
        self, token_hash: str, now: int
    ) -> AuthPrincipal | None:
        with self._write_lock, self._connect() as connection:
            row = connection.execute(
                """
                SELECT
                    client_tokens.user_id,
                    client_tokens.scopes,
                    users.username
                FROM client_tokens
                JOIN users ON users.id = client_tokens.user_id
                WHERE client_tokens.token_hash = ?
                  AND client_tokens.revoked_at IS NULL
                  AND (client_tokens.expires_at IS NULL OR client_tokens.expires_at > ?)
                """,
                (token_hash, now),
            ).fetchone()
            if row is not None:
                connection.execute(
                    "UPDATE client_tokens SET last_used_at = ? WHERE token_hash = ?",
                    (now, token_hash),
                )
                connection.commit()
        if row is None:
            return None
        return AuthPrincipal(
            subject_id=row["user_id"],
            username=row["username"],
            scopes=self._parse_scopes(row["scopes"]),
            auth_type="client_token",
        )

    def _create_session(
        self,
        connection: sqlite3.Connection,
        *,
        user_id: str,
        username: str,
        now: int,
        scopes: frozenset[str] = ALL_AUTH_SCOPES,
    ) -> SessionCredential:
        token = f"azs_{secrets.token_urlsafe(32)}"
        expires_at = now + SESSION_TTL_SECONDS
        connection.execute("DELETE FROM sessions WHERE expires_at <= ?", (now,))
        connection.execute(
            """
            INSERT INTO sessions (token_hash, user_id, created_at, expires_at)
            VALUES (?, ?, ?, ?)
            """,
            (self._token_digest(token), user_id, now, expires_at),
        )
        return SessionCredential(
            token=token,
            expires_at=expires_at,
            principal=AuthPrincipal(
                subject_id=user_id,
                username=username,
                scopes=scopes,
                auth_type="session",
            ),
        )

    def _initialize_database(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    password_hash TEXT NOT NULL,
                    scopes TEXT NOT NULL,
                    created_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    token_hash TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    created_at INTEGER NOT NULL,
                    expires_at INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS sessions_expires_at
                    ON sessions(expires_at);
                CREATE TABLE IF NOT EXISTS client_tokens (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    token_hash TEXT NOT NULL UNIQUE,
                    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    scopes TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    last_used_at INTEGER,
                    expires_at INTEGER,
                    revoked_at INTEGER
                );
                CREATE INDEX IF NOT EXISTS client_tokens_user_id
                    ON client_tokens(user_id);
                CREATE TABLE IF NOT EXISTS websocket_tickets (
                    token_hash TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    purpose TEXT NOT NULL,
                    instance TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    expires_at INTEGER NOT NULL,
                    used_at INTEGER
                );
                CREATE INDEX IF NOT EXISTS websocket_tickets_expires_at
                    ON websocket_tickets(expires_at);
                CREATE TABLE IF NOT EXISTS audit_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    actor_id TEXT,
                    action TEXT NOT NULL,
                    detail TEXT NOT NULL,
                    created_at INTEGER NOT NULL
                );
                """
            )
            connection.commit()
        self._restrict_file_permissions(self.database_path)

    def _synchronize_bootstrap_file(self) -> None:
        if self.initialized:
            self.bootstrap_path.unlink(missing_ok=True)
            return
        if self.bootstrap_path.exists():
            self._restrict_file_permissions(self.bootstrap_path)
            return
        token = secrets.token_urlsafe(32)
        try:
            descriptor = os.open(
                self.bootstrap_path,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
            )
        except FileExistsError:
            self._restrict_file_permissions(self.bootstrap_path)
            return
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            output.write(f"{token}\n")

    def _read_password_reset_challenge(self) -> PasswordResetChallenge | None:
        try:
            payload = json.loads(self.password_reset_path.read_text(encoding="utf-8"))
            token = payload["token"]
            expires_at = payload["expiresAt"]
            if not isinstance(token, str) or not isinstance(expires_at, int):
                return None
            return PasswordResetChallenge(token=token, expires_at=expires_at)
        except FileNotFoundError, json.JSONDecodeError, KeyError, TypeError:
            return None

    @classmethod
    def _write_restricted_json(cls, path: Path, payload: dict[str, object]) -> None:
        temporary_path = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
        descriptor = os.open(
            temporary_path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as output:
                json.dump(payload, output, ensure_ascii=True, separators=(",", ":"))
                output.write("\n")
            os.replace(temporary_path, path)
            cls._restrict_file_permissions(path)
        finally:
            temporary_path.unlink(missing_ok=True)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("PRAGMA journal_mode = WAL")
        for suffix in ("", "-wal", "-shm"):
            self._restrict_file_permissions(Path(f"{self.database_path}{suffix}"))
        try:
            yield connection
        finally:
            connection.close()

    @staticmethod
    def _scope_for_websocket_purpose(purpose: str) -> str:
        scopes = {
            "live_screenshot": "media:view",
            "live_control": "device:control",
        }
        try:
            return scopes[purpose]
        except KeyError as exc:
            raise ValidationError("WebSocket 用途无效") from exc

    @staticmethod
    def _validate_username(username: str) -> str:
        value = username.strip()
        if not USERNAME_PATTERN.fullmatch(value):
            raise ValidationError("用户名仅支持 3 到 64 位字母、数字、点、横线和下划线")
        return value

    @staticmethod
    def _validate_password(password: str) -> None:
        if not 12 <= len(password) <= 128:
            raise ValidationError("密码长度必须为 12 到 128 个字符")

    @staticmethod
    def _hash_password(password: str) -> str:
        salt = secrets.token_bytes(16)
        digest = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=PASSWORD_SCRYPT_N,
            r=PASSWORD_SCRYPT_R,
            p=PASSWORD_SCRYPT_P,
            dklen=PASSWORD_HASH_LENGTH,
        )
        return (
            f"scrypt${PASSWORD_SCRYPT_N}${PASSWORD_SCRYPT_R}${PASSWORD_SCRYPT_P}$"
            f"{salt.hex()}${digest.hex()}"
        )

    @staticmethod
    def _verify_password(password: str, encoded: str) -> bool:
        try:
            algorithm, n, r, p, salt_hex, digest_hex = encoded.split("$", 5)
            if algorithm != "scrypt":
                return False
            digest = hashlib.scrypt(
                password.encode("utf-8"),
                salt=bytes.fromhex(salt_hex),
                n=int(n),
                r=int(r),
                p=int(p),
                dklen=len(bytes.fromhex(digest_hex)),
            )
            return hmac.compare_digest(digest, bytes.fromhex(digest_hex))
        except TypeError, ValueError:
            return False

    @staticmethod
    def _token_digest(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    @staticmethod
    def _serialize_scopes(scopes: Iterable[str]) -> str:
        return json.dumps(sorted(set(scopes)), ensure_ascii=True, separators=(",", ":"))

    @staticmethod
    def _parse_scopes(value: str) -> frozenset[str]:
        parsed = json.loads(value)
        if not isinstance(parsed, list):
            return frozenset()
        return frozenset(item for item in parsed if isinstance(item, str))

    @staticmethod
    def _write_audit(
        connection: sqlite3.Connection,
        *,
        actor_id: str | None,
        action: str,
        detail: dict[str, object],
        created_at: int,
    ) -> None:
        connection.execute(
            """
            INSERT INTO audit_events (actor_id, action, detail, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (
                actor_id,
                action,
                json.dumps(detail, ensure_ascii=False, separators=(",", ":")),
                created_at,
            ),
        )

    @staticmethod
    def _restrict_file_permissions(path: Path) -> None:
        try:
            os.chmod(path, 0o600)
        except FileNotFoundError, PermissionError, OSError:
            # Windows 会忽略 POSIX 权限；部署仍依赖受限目录 ACL。
            return
