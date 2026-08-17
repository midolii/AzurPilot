import unittest

from module.extension_api.sensitive import REDACTED_TEXT, SensitiveValuePolicy


class TestSensitiveValuePolicy(unittest.TestCase):
    def setUp(self):
        self.policy = SensitiveValuePolicy()

    def test_explicit_and_semantic_sensitive_fields(self):
        self.assertTrue(self.policy.is_sensitive("Alas.Error.LlmApiKey"))
        self.assertTrue(self.policy.is_sensitive("Custom.Auth.AccessToken"))
        self.assertTrue(self.policy.is_sensitive("Custom.Auth.Password"))

    def test_public_key_is_allowed(self):
        self.assertFalse(
            self.policy.is_sensitive("Alas.EmulatorInfo.RemoteSSHPublicKey")
        )

    def test_redact_config_returns_copy_and_paths(self):
        original = {
            "Alas": {
                "Error": {
                    "LlmApiKey": "secret-value",
                    "LlmModel": "model",
                    "OnePushConfig": "token: push-secret",
                }
            }
        }

        result = self.policy.redact_config(original)

        self.assertEqual("secret-value", original["Alas"]["Error"]["LlmApiKey"])
        self.assertIsNone(result.values["Alas"]["Error"]["LlmApiKey"])
        self.assertEqual("model", result.values["Alas"]["Error"]["LlmModel"])
        self.assertEqual(
            (
                "Alas.Error.LlmApiKey",
                "Alas.Error.OnePushConfig",
            ),
            result.redacted_paths,
        )
        self.assertIn("secret-value", result.sensitive_values)
        self.assertIn("token: push-secret", result.sensitive_values)

    def test_redact_text_replaces_raw_and_repr_values(self):
        text = "key=secret-value config='token: push-secret'"

        redacted = self.policy.redact_text(
            text, ("secret-value", "token: push-secret")
        )

        self.assertNotIn("secret-value", redacted)
        self.assertNotIn("push-secret", redacted)
        self.assertIn(REDACTED_TEXT, redacted)


if __name__ == "__main__":
    unittest.main()
