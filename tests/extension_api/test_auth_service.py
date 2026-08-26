import unittest
from tempfile import TemporaryDirectory

from module.extension_api.auth import (
    AuthenticationRequiredError,
    AuthService,
    BootstrapTokenError,
    PasswordResetTokenError,
)


class TestAuthService(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.now = 1_777_000_000
        self.service = AuthService(
            database_path=f"{self.directory.name}/auth.db",
            bootstrap_path=f"{self.directory.name}/bootstrap.txt",
            password_reset_path=f"{self.directory.name}/password-reset.json",
            now=lambda: self.now,
        )

    def test_setup_requires_local_bootstrap_token(self):
        with self.assertRaises(BootstrapTokenError):
            self.service.setup(
                bootstrap_token="invalid-bootstrap-token-value",
                username="owner",
                password="long-test-password",
                rate_limit_key="test:invalid",
            )

        credential = self.service.setup(
            bootstrap_token=self.service.read_bootstrap_token() or "",
            username="owner",
            password="long-test-password",
            rate_limit_key="test:valid",
        )

        self.assertTrue(self.service.initialized)
        self.assertFalse(self.service.bootstrap_path.exists())
        self.assertEqual(
            "owner",
            self.service.authenticate(session_token=credential.token).username,
        )

    def test_websocket_ticket_is_short_lived_single_use_and_bound_to_instance(self):
        credential = self.service.setup(
            bootstrap_token=self.service.read_bootstrap_token() or "",
            username="owner",
            password="long-test-password",
            rate_limit_key="test:setup",
        )
        principal = credential.principal
        ticket = self.service.create_websocket_ticket(
            principal=principal,
            purpose="live_screenshot",
            instance="alas",
        )

        consumed = self.service.consume_websocket_ticket(
            ticket=ticket.ticket,
            purpose="live_screenshot",
            instance="alas",
        )
        self.assertEqual("owner", consumed.username)
        with self.assertRaises(AuthenticationRequiredError):
            self.service.consume_websocket_ticket(
                ticket=ticket.ticket,
                purpose="live_screenshot",
                instance="alas",
            )

        another = self.service.create_websocket_ticket(
            principal=principal,
            purpose="live_control",
            instance="alas",
        )
        with self.assertRaises(AuthenticationRequiredError):
            self.service.consume_websocket_ticket(
                ticket=another.ticket,
                purpose="live_control",
                instance="farm",
            )

        expiring = self.service.create_websocket_ticket(
            principal=principal,
            purpose="live_screenshot",
            instance="alas",
        )
        self.now += 31
        with self.assertRaises(AuthenticationRequiredError):
            self.service.consume_websocket_ticket(
                ticket=expiring.ticket,
                purpose="live_screenshot",
                instance="alas",
            )

    def test_password_reset_requires_local_short_lived_token(self):
        original = self.service.setup(
            bootstrap_token=self.service.read_bootstrap_token() or "",
            username="owner",
            password="long-test-password",
            rate_limit_key="test:setup-reset",
        )
        challenge = self.service.request_password_reset()

        with self.assertRaises(PasswordResetTokenError):
            self.service.reset_password(
                reset_token="invalid-password-reset-token",
                password="new-long-test-password",
                rate_limit_key="test:reset-invalid",
            )

        credential = self.service.reset_password(
            reset_token=challenge.token,
            password="new-long-test-password",
            rate_limit_key="test:reset-valid",
        )

        self.assertFalse(self.service.password_reset_path.exists())
        with self.assertRaises(AuthenticationRequiredError):
            self.service.authenticate(session_token=original.token)
        self.assertEqual(
            "owner",
            self.service.authenticate(session_token=credential.token).username,
        )
        self.assertEqual(
            "owner",
            self.service.login(
                username="owner",
                password="new-long-test-password",
                rate_limit_key="test:login-new-password",
            ).principal.username,
        )

    def test_password_reset_token_expires(self):
        self.service.setup(
            bootstrap_token=self.service.read_bootstrap_token() or "",
            username="owner",
            password="long-test-password",
            rate_limit_key="test:setup-expired-reset",
        )
        challenge = self.service.request_password_reset()
        self.now = challenge.expires_at

        self.assertFalse(self.service.password_reset_available)
        with self.assertRaises(PasswordResetTokenError):
            self.service.reset_password(
                reset_token=challenge.token,
                password="new-long-test-password",
                rate_limit_key="test:reset-expired",
            )


if __name__ == "__main__":
    unittest.main()
