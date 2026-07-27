import unittest

from app import auth


class JwtCompatibilityTests(unittest.TestCase):
    def test_access_token_round_trip_uses_configured_algorithm(self):
        token = auth.create_access_token({"sub": "security-smoke-test"})

        payload = auth.jwt.decode(
            token,
            auth.settings.SECRET_KEY,
            algorithms=[auth.settings.ALGORITHM],
        )

        self.assertEqual(payload["sub"], "security-smoke-test")

    def test_tampered_access_token_raises_shared_jwt_error(self):
        token = auth.create_access_token({"sub": "security-smoke-test"})

        with self.assertRaises(auth.JWTError):
            auth.jwt.decode(
                f"{token}tampered",
                auth.settings.SECRET_KEY,
                algorithms=[auth.settings.ALGORITHM],
            )


if __name__ == "__main__":
    unittest.main()
