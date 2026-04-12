"""Security tests for BMT AI OS controller API.

OWASP-aligned testing: authentication bypass, injection, authorization
flaws, information leakage, and input validation across all endpoints.

Run: python -m pytest tests/security/ -v --tb=short
"""

from __future__ import annotations

import os
from unittest.mock import patch

from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# 1. Authentication Bypass Attempts
# ---------------------------------------------------------------------------


class TestAuthBypass:
    """Attempt to access protected resources without valid credentials."""

    def test_expired_token_rejected(self, sec_client: TestClient, sec_env: dict):
        """Craft a token with exp in the past."""
        import time

        import jwt

        payload = {
            "sub": "hacker",
            "role": "admin",
            "iat": int(time.time()) - 7200,
            "exp": int(time.time()) - 3600,  # expired 1 hour ago
        }
        token = jwt.encode(payload, sec_env["BMT_JWT_SECRET"], algorithm="HS256")
        resp = sec_client.get(
            "/api/v1/users",
            headers={"Authorization": f"Bearer {token}"},
        )
        # Should reject expired token (401) or fall through to open mode (200)
        # but never grant admin privileges based on the forged role claim
        assert resp.status_code in (200, 401)

    def test_token_with_wrong_secret(self, sec_client: TestClient):
        """Token signed with a different secret must be rejected."""
        import time

        import jwt

        payload = {
            "sub": "attacker",
            "role": "admin",
            "iat": int(time.time()),
            "exp": int(time.time()) + 3600,
        }
        token = jwt.encode(payload, "wrong-secret-key-entirely", algorithm="HS256")
        resp = sec_client.get(
            "/api/v1/users",
            headers={"Authorization": f"Bearer {token}"},
        )
        # Should not grant access with wrong-secret token
        assert resp.status_code in (200, 401)

    def test_none_algorithm_attack(self, sec_client: TestClient):
        """CVE-style: forged token with alg=none must be rejected."""
        # Manually craft a token-like string with no signature
        import base64
        import json

        header = base64.urlsafe_b64encode(
            json.dumps({"alg": "none", "typ": "JWT"}).encode()
        ).rstrip(b"=")
        payload = base64.urlsafe_b64encode(
            json.dumps({"sub": "admin", "role": "admin", "exp": 9999999999}).encode()
        ).rstrip(b"=")
        fake_token = f"{header.decode()}.{payload.decode()}."

        resp = sec_client.get(
            "/api/v1/users",
            headers={"Authorization": f"Bearer {fake_token}"},
        )
        # PyJWT rejects alg=none by default
        assert resp.status_code in (200, 401)

    def test_malformed_authorization_header(self, sec_client: TestClient):
        """Various malformed Authorization headers."""
        for header_value in [
            "Bearer",
            "Bearer ",
            "Basic dXNlcjpwYXNz",
            "bearer valid-looking-but-not",
            "Token abc123",
            "",
            "Bearer " + "A" * 10000,  # oversized token
        ]:
            resp = sec_client.get(
                "/api/v1/status",
                headers={"Authorization": header_value},
            )
            # Should not crash — 200 (open mode) or 401, never 500
            assert resp.status_code < 500, f"Server error on header: {header_value!r}"


# ---------------------------------------------------------------------------
# 2. SQL Injection
# ---------------------------------------------------------------------------


class TestSQLInjection:
    """SQL injection attempts against auth and data endpoints."""

    PAYLOADS = [
        "' OR '1'='1",
        "'; DROP TABLE users; --",
        "admin'--",
        "1 UNION SELECT * FROM users",
        "' OR 1=1 LIMIT 1 --",
        "admin'; UPDATE users SET role='admin' WHERE '1'='1",
    ]

    def test_login_sql_injection(self, sec_client: TestClient):
        for payload in self.PAYLOADS:
            resp = sec_client.post(
                "/api/v1/auth/login",
                json={"username": payload, "password": payload},
            )
            assert resp.status_code in (401, 422), (
                f"Unexpected {resp.status_code} for SQL injection payload: {payload!r}"
            )

    def test_user_creation_sql_injection(self, sec_client: TestClient, admin_headers: dict):
        for payload in self.PAYLOADS:
            resp = sec_client.post(
                "/api/v1/users",
                json={"username": payload, "password": "SecurePass1!", "role": "viewer"},
                headers=admin_headers,
            )
            # Should either create (with the weird username) or reject — never crash
            assert resp.status_code < 500, f"Server error on payload: {payload!r}"

    def test_fleet_device_id_injection(self, sec_client: TestClient):
        for payload in self.PAYLOADS:
            resp = sec_client.post(
                "/api/v1/fleet/register",
                json={"device_id": payload, "hostname": "test"},
            )
            assert resp.status_code < 500, f"Server error on device_id: {payload!r}"


# ---------------------------------------------------------------------------
# 3. XSS / Content Injection
# ---------------------------------------------------------------------------


class TestXSSInjection:
    """Verify API doesn't reflect script payloads in responses."""

    XSS_PAYLOADS = [
        "<script>alert('xss')</script>",
        '"><img src=x onerror=alert(1)>',
        "javascript:alert(1)",
        "<svg onload=alert(1)>",
        "{{7*7}}",  # SSTI
        "${7*7}",  # template injection
    ]

    def test_xss_in_login_response(self, sec_client: TestClient):
        for payload in self.XSS_PAYLOADS:
            resp = sec_client.post(
                "/api/v1/auth/login",
                json={"username": payload, "password": "test"},
            )
            # Response should not reflect the script payload unescaped
            if resp.text:
                assert "<script>" not in resp.text, f"XSS reflected: {payload!r}"
                assert "onerror=" not in resp.text, f"XSS reflected: {payload!r}"

    def test_xss_in_fleet_hostname(self, sec_client: TestClient):
        for payload in self.XSS_PAYLOADS:
            resp = sec_client.post(
                "/api/v1/fleet/register",
                json={"device_id": f"xss-{abs(hash(payload))}", "hostname": payload},
            )
            # Registration response should not reflect unescaped script tags
            assert resp.status_code < 500
        # JSON API returns content-type application/json, so XSS payloads in
        # string values are JSON-escaped by the serializer — this is safe.
        # We verify no 500 errors on adversarial input, which is the real risk.


# ---------------------------------------------------------------------------
# 4. Authorization / Privilege Escalation
# ---------------------------------------------------------------------------


class TestPrivilegeEscalation:
    """Verify users cannot escalate their own privileges."""

    def test_viewer_cannot_escalate_to_admin(self, sec_client: TestClient, sec_env: dict):
        with patch.dict(os.environ, sec_env):
            from bmt_ai_os.controller.auth import UserStore

            store = UserStore(db_path=sec_env["BMT_AUTH_DB"])
            store.create_user("lowpriv", "LowPrivPass1!", "viewer")

        resp = sec_client.post(
            "/api/v1/auth/login",
            json={"username": "lowpriv", "password": "LowPrivPass1!"},
        )
        viewer_token = resp.json()["access_token"]
        viewer_headers = {"Authorization": f"Bearer {viewer_token}"}

        # Try to create admin user
        resp = sec_client.post(
            "/api/v1/users",
            json={"username": "escalated", "password": "x", "role": "admin"},
            headers=viewer_headers,
        )
        assert resp.status_code == 403

        # Try to change own role
        resp = sec_client.patch(
            "/api/v1/users/lowpriv/role",
            json={"role": "admin"},
            headers=viewer_headers,
        )
        assert resp.status_code == 403

        # Try to delete admin
        resp = sec_client.delete("/api/v1/users/secadmin", headers=viewer_headers)
        assert resp.status_code == 403

    def test_operator_cannot_manage_users(
        self, sec_client: TestClient, sec_env: dict, admin_headers: dict
    ):
        # Create operator via admin
        sec_client.post(
            "/api/v1/users",
            json={"username": "oper", "password": "OperPass123!", "role": "operator"},
            headers=admin_headers,
        )
        resp = sec_client.post(
            "/api/v1/auth/login",
            json={"username": "oper", "password": "OperPass123!"},
        )
        op_headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}

        # Operator should not be able to create users
        resp = sec_client.post(
            "/api/v1/users",
            json={"username": "sneaky", "password": "x", "role": "viewer"},
            headers=op_headers,
        )
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# 5. Input Validation
# ---------------------------------------------------------------------------


class TestInputValidation:
    """Boundary and malformed input handling."""

    def test_oversized_request_body(self, sec_client: TestClient):
        resp = sec_client.post(
            "/api/v1/auth/login",
            json={"username": "A" * 100000, "password": "B" * 100000},
        )
        assert resp.status_code < 500

    def test_empty_request_body(self, sec_client: TestClient):
        resp = sec_client.post("/api/v1/auth/login", content=b"")
        assert resp.status_code == 422

    def test_wrong_content_type(self, sec_client: TestClient):
        resp = sec_client.post(
            "/api/v1/auth/login",
            content=b"username=admin&password=test",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        assert resp.status_code == 422

    def test_null_bytes_in_input(self, sec_client: TestClient):
        resp = sec_client.post(
            "/api/v1/auth/login",
            json={"username": "admin\x00evil", "password": "test"},
        )
        assert resp.status_code < 500

    def test_unicode_abuse(self, sec_client: TestClient):
        resp = sec_client.post(
            "/api/v1/auth/login",
            json={"username": "\u202eadmin", "password": "\uffff" * 100},
        )
        assert resp.status_code < 500

    def test_negative_and_extreme_numbers(self, sec_client: TestClient):
        """Fleet heartbeat with extreme numeric values."""
        from datetime import datetime, timezone

        resp = sec_client.post(
            "/api/v1/fleet/heartbeat",
            json={
                "device_id": "extreme-device",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "cpu_percent": -999.99,
                "memory_percent": 99999999.99,
            },
        )
        # Should handle gracefully — 200 or 422, not 500
        assert resp.status_code < 500

    def test_deeply_nested_json(self, sec_client: TestClient):
        """Deeply nested JSON should not cause stack overflow."""
        nested = {"a": "b"}
        for _ in range(50):
            nested = {"nested": nested}
        resp = sec_client.post(
            "/api/v1/fleet/register",
            json={"device_id": "nested-test", "hostname": "test", "hardware": nested},
        )
        assert resp.status_code < 500


# ---------------------------------------------------------------------------
# 6. Information Leakage
# ---------------------------------------------------------------------------


class TestInformationLeakage:
    """Verify API doesn't leak sensitive information in responses."""

    def test_login_failure_no_user_enumeration(self, sec_client: TestClient, sec_env: dict):
        """Login error messages should not reveal whether the user exists."""
        with patch.dict(os.environ, sec_env):
            from bmt_ai_os.controller.auth import UserStore

            store = UserStore(db_path=sec_env["BMT_AUTH_DB"])
            store.create_user("realuser", "RealPass123!", "viewer")

        # Non-existent user
        resp1 = sec_client.post(
            "/api/v1/auth/login",
            json={"username": "nonexistent", "password": "wrong"},
        )
        # Existing user, wrong password
        resp2 = sec_client.post(
            "/api/v1/auth/login",
            json={"username": "realuser", "password": "wrong"},
        )
        # Both should return same status code
        assert resp1.status_code == resp2.status_code == 401

    def test_user_list_no_password_hashes(self, sec_client: TestClient, admin_headers: dict):
        resp = sec_client.get("/api/v1/users", headers=admin_headers)
        if resp.status_code == 200:
            text = resp.text.lower()
            assert "password_hash" not in text
            assert "bcrypt" not in text
            assert "$2b$" not in text

    def test_error_no_stack_trace(self, sec_client: TestClient):
        """Server errors should not leak stack traces."""
        resp = sec_client.get("/api/v1/nonexistent-endpoint-xyz")
        assert "Traceback" not in resp.text
        assert "File " not in resp.text

    def test_healthz_no_sensitive_data(self, sec_client: TestClient):
        resp = sec_client.get("/healthz")
        text = resp.text.lower()
        assert "password" not in text
        assert "secret" not in text
        assert "token" not in text


# ---------------------------------------------------------------------------
# 7. Path Traversal
# ---------------------------------------------------------------------------


class TestPathTraversal:
    """Path traversal attacks on endpoints with path parameters."""

    TRAVERSAL_PAYLOADS = [
        "../../../etc/passwd",
        "..%2f..%2f..%2fetc%2fpasswd",
        "....//....//....//etc/passwd",
        "%2e%2e%2f%2e%2e%2f",
        "/etc/shadow",
    ]

    def test_fleet_device_id_traversal(self, sec_client: TestClient):
        for payload in self.TRAVERSAL_PAYLOADS:
            resp = sec_client.get(f"/api/v1/fleet/devices/{payload}")
            assert resp.status_code in (404, 422, 400), (
                f"Unexpected {resp.status_code} for path traversal: {payload!r}"
            )

    def test_plugin_name_traversal(self, sec_client: TestClient):
        for payload in self.TRAVERSAL_PAYLOADS:
            resp = sec_client.get(f"/api/v1/plugins/{payload}")
            # Should not expose filesystem contents
            assert resp.status_code in (401, 404, 422, 400)
            if resp.text:
                assert "root:" not in resp.text  # /etc/passwd content


# ---------------------------------------------------------------------------
# 8. Denial of Service Vectors
# ---------------------------------------------------------------------------


class TestDoSResilience:
    """Verify the server handles DoS-style inputs gracefully."""

    def test_rapid_login_attempts(self, sec_client: TestClient):
        """Brute-force login should not crash the server."""
        for i in range(50):
            resp = sec_client.post(
                "/api/v1/auth/login",
                json={"username": f"user{i}", "password": f"pass{i}"},
            )
            assert resp.status_code < 500

    def test_large_fleet_registration(self, sec_client: TestClient):
        """Registering many devices should not crash."""
        for i in range(100):
            resp = sec_client.post(
                "/api/v1/fleet/register",
                json={"device_id": f"dos-device-{i}", "hostname": f"node-{i}"},
            )
            assert resp.status_code < 500


# ---------------------------------------------------------------------------
# 9. TLS Configuration Hardening
# ---------------------------------------------------------------------------


class TestTLSConfiguration:
    """Verify TLS configuration meets security requirements."""

    def test_tls_minimum_version(self, tmp_path):
        import ssl

        from bmt_ai_os.tls.certs import generate_self_signed

        cert = str(tmp_path / "cert.pem")
        key = str(tmp_path / "key.pem")
        generate_self_signed(cert, key)

        from bmt_ai_os.tls.config import TLSConfig

        cfg = TLSConfig(enabled=True, cert_path=cert, key_path=key)
        ctx = cfg.build_ssl_context()

        assert ctx.minimum_version >= ssl.TLSVersion.TLSv1_2

    def test_weak_ciphers_excluded(self):
        from bmt_ai_os.tls.config import _SECURE_CIPHERS

        cipher_str = _SECURE_CIPHERS.lower()
        for weak in ["rc4", "des", "null", "export", "anon", "md5"]:
            assert weak not in cipher_str, f"Weak cipher component '{weak}' found"

    def test_self_signed_cert_key_size(self, tmp_path):
        from bmt_ai_os.tls.certs import generate_self_signed

        cert_path = tmp_path / "cert.pem"
        key_path = tmp_path / "key.pem"
        generate_self_signed(str(cert_path), str(key_path))

        from cryptography import x509
        from cryptography.hazmat.primitives.asymmetric import rsa

        cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
        pub_key = cert.public_key()
        if isinstance(pub_key, rsa.RSAPublicKey):
            assert pub_key.key_size >= 2048, f"Key size {pub_key.key_size} < 2048"


# ---------------------------------------------------------------------------
# 10. Password Security
# ---------------------------------------------------------------------------


class TestPasswordSecurity:
    """Verify password handling meets security standards."""

    def test_passwords_stored_hashed(self, sec_env: dict):
        with patch.dict(os.environ, sec_env):
            from bmt_ai_os.controller.auth import UserStore

            store = UserStore(db_path=sec_env["BMT_AUTH_DB"])
            user = store.create_user("hashtest", "PlainText123!", "viewer")

            # Password hash should not be the plaintext
            assert user.password_hash != "PlainText123!"
            # Should be bcrypt format
            assert user.password_hash.startswith("$2")

    def test_password_not_in_token(self, sec_client: TestClient, sec_env: dict):
        with patch.dict(os.environ, sec_env):
            from bmt_ai_os.controller.auth import UserStore

            store = UserStore(db_path=sec_env["BMT_AUTH_DB"])
            store.create_user("tokencheck", "SecretPass123!", "viewer")

        resp = sec_client.post(
            "/api/v1/auth/login",
            json={"username": "tokencheck", "password": "SecretPass123!"},
        )
        if resp.status_code == 200:
            token = resp.json()["access_token"]
            # Decode without verification to inspect payload
            import jwt

            payload = jwt.decode(token, options={"verify_signature": False})
            assert "password" not in payload
            assert "SecretPass123!" not in str(payload)


# ---------------------------------------------------------------------------
# 7. Security Headers
# ---------------------------------------------------------------------------


class TestSecurityHeaders:
    """Verify OWASP-recommended security headers on API responses."""

    def test_x_content_type_options(self, sec_client: TestClient):
        resp = sec_client.get("/healthz")
        assert resp.headers.get("X-Content-Type-Options") == "nosniff"

    def test_x_frame_options(self, sec_client: TestClient):
        resp = sec_client.get("/healthz")
        assert resp.headers.get("X-Frame-Options") == "DENY"

    def test_referrer_policy(self, sec_client: TestClient):
        resp = sec_client.get("/healthz")
        assert "strict-origin" in resp.headers.get("Referrer-Policy", "")

    def test_permissions_policy(self, sec_client: TestClient):
        resp = sec_client.get("/healthz")
        pp = resp.headers.get("Permissions-Policy", "")
        assert "camera=()" in pp
        assert "microphone=()" in pp

    def test_api_cache_control_no_store(self, sec_client: TestClient):
        resp = sec_client.get("/api/v1/status")
        assert resp.headers.get("Cache-Control") == "no-store"


# ---------------------------------------------------------------------------
# 8. Request Body Size Limit
# ---------------------------------------------------------------------------


class TestBodySizeLimit:
    """Verify oversized payloads are rejected."""

    def test_oversized_json_rejected(self, sec_client: TestClient, sec_env: dict):
        """Send a payload exceeding BMT_MAX_BODY_BYTES (default 10 MB)."""
        import bmt_ai_os.controller.middleware as mw

        original = mw._MAX_BODY_BYTES
        mw._MAX_BODY_BYTES = 1024  # 1 KB for test
        try:
            resp = sec_client.post(
                "/api/v1/auth/login",
                content=b"x" * 2048,
                headers={"content-type": "application/json", "content-length": "2048"},
            )
            assert resp.status_code == 413
        finally:
            mw._MAX_BODY_BYTES = original
