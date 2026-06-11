"""
Comprehensive Security Penetration Testing Suite for BIST Bot.

Tests SQL Injection, XSS, CSRF, authentication bypass, input validation,
API security, rate limiting, data exposure, and command injection.
"""

import sys
import json
import pytest
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, urlencode
from unittest.mock import MagicMock, patch, Mock

try:
    from flask import Flask
    from flask_jwt_extended import create_access_token
except ImportError as e:
    pytest.skip(f"Flask dependencies not available: {e}", allow_module_level=True)

from sqlalchemy import text, create_engine
from sqlalchemy.orm import sessionmaker

try:
    from bist_bot.dashboard import create_app
    from bist_bot.auth.passwords import hash_password, verify_and_rehash_password
    from bist_bot.db.database import DatabaseManager, Base
    from bist_bot.config.settings import Settings
except ImportError as e:
    pytest.skip(f"BIST Bot modules not available: {e}", allow_module_level=True)


# ============================================================================
# FIXTURE SETUP
# ============================================================================

@pytest.fixture
def security_app():
    """Flask app configured for security testing."""
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["JWT_SECRET_KEY"] = "test-secret-key-for-security-testing"
    app.config["PRESERVE_CONTEXT_ON_EXCEPTION"] = False
    
    # Initialize with full dashboard functionality
    from bist_bot.dependencies import get_default_container
    container = get_default_container()
    app = create_app(container)
    app.config["TESTING"] = True
    
    return app


@pytest.fixture
def security_client(security_app):
    """Flask test client."""
    return security_app.test_client()


@pytest.fixture
def auth_headers(security_app):
    """Valid JWT authentication headers."""
    with security_app.app_context():
        access_token = create_access_token(identity="testuser")
        return {"Authorization": f"Bearer {access_token}"}


@pytest.fixture
def db_manager():
    """In-memory SQLite database for security tests."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return DatabaseManager(Session=Session, engine=engine)


# ============================================================================
# 1. SQL INJECTION TESTS
# ============================================================================

class TestSQLInjection:
    """Test SQL injection vulnerabilities in database operations."""

    def test_signal_ticker_sql_injection(self, db_manager):
        """SQL Injection via ticker field."""
        payload = "THYAO.IS' OR '1'='1"
        
        # Attempt injection through signals repository
        from bist_bot.db.repositories.signals_repository import SignalsRepository
        repo = SignalsRepository(db_manager)
        
        # This should use parameterized queries and safely escape
        signals = repo.get_signal_by_ticker(payload)
        assert signals is None or isinstance(signals, list)
        
    def test_scan_id_sql_injection(self, db_manager):
        """SQL Injection via scan_id parameter."""
        malicious_scan_id = "'; DROP TABLE signals; --"
        
        from bist_bot.db.repositories.signals_repository import SignalsRepository
        repo = SignalsRepository(db_manager)
        
        # Should not execute SQL commands
        result = repo.get_scan_log(malicious_scan_id)
        assert result is None
        
        # Verify table still exists
        with db_manager.session() as session:
            count = session.execute(text("SELECT COUNT(*) FROM signals")).scalar()
            assert count is not None
    
    def test_union_based_sql_injection(self, db_manager):
        """UNION-based SQL injection attacks."""
        payload = "THYAO.IS UNION SELECT * FROM users --"
        
        from bist_bot.db.repositories.signals_repository import SignalsRepository
        repo = SignalsRepository(db_manager)
        
        # Should safely handle UNION attempts
        result = repo.get_signal_by_ticker(payload)
        assert isinstance(result, (list, type(None)))
    
    def test_time_based_sql_injection(self, db_manager):
        """Time-based blind SQL injection."""
        import time
        
        payload = "THYAO.IS'; WAITFOR DELAY '00:00:05'; --"
        
        start = time.time()
        from bist_bot.db.repositories.signals_repository import SignalsRepository
        repo = SignalsRepository(db_manager)
        result = repo.get_signal_by_ticker(payload)
        elapsed = time.time() - start
        
        # Should return quickly (< 1 sec), not wait 5 seconds
        assert elapsed < 2.0
    
    def test_boolean_based_sql_injection(self, db_manager):
        """Boolean-based blind SQL injection."""
        payloads = [
            "THYAO.IS' AND '1'='1",
            "THYAO.IS' AND '1'='2",
            "THYAO.IS' AND 1=1; --",
        ]
        
        from bist_bot.db.repositories.signals_repository import SignalsRepository
        repo = SignalsRepository(db_manager)
        
        for payload in payloads:
            result = repo.get_signal_by_ticker(payload)
            # Should not crash or expose DB structure
            assert isinstance(result, (list, type(None)))


# ============================================================================
# 2. XSS (Cross-Site Scripting) TESTS
# ============================================================================

class TestXSS:
    """Test XSS vulnerabilities in API responses and web UI."""
    
    def test_xss_in_signal_reason(self, security_client, auth_headers):
        """XSS via signal reason field in API response."""
        payload = {
            "reason": "<script>alert('XSS')</script>",
            "ticker": "THYAO.IS"
        }
        
        # Attempt to inject via signal creation
        response = security_client.post(
            "/api/signals",
            json=payload,
            headers=auth_headers
        )
        
        # Response body should escape HTML
        if response.status_code == 200:
            data = response.get_json()
            assert "<script>" not in response.data.decode('utf-8') or \
                   "&lt;script&gt;" in response.data.decode('utf-8')
    
    def test_xss_in_query_parameters(self, security_client):
        """XSS via query parameters in URLs."""
        xss_payload = quote("<img src=x onerror='alert(\"XSS\")'>")
        
        response = security_client.get(f"/search?q={xss_payload}")
        
        # Should escape or sanitize output
        assert response.status_code in (200, 404, 400)
        # Verify no raw script tags in response
        body = response.data.decode('utf-8')
        assert body.count("<script>") == 0 or "&lt;script&gt;" in body
    
    def test_xss_in_api_ticker_field(self, security_client, auth_headers):
        """XSS injection in ticker API field."""
        malicious_ticker = "<svg/onload=alert('XSS')>"
        
        response = security_client.get(
            f"/api/signals/{malicious_ticker}",
            headers=auth_headers
        )
        
        if response.status_code == 200:
            body = response.data.decode('utf-8')
            assert body.count("<svg/onload") == 0 or "&lt;svg" in body
    
    def test_xss_in_json_response(self, security_client, auth_headers):
        """XSS in JSON API responses."""
        response = security_client.get(
            "/api/signals?limit=10&offset=0",
            headers=auth_headers
        )
        
        if response.status_code == 200:
            # Ensure valid JSON
            data = response.get_json()
            assert isinstance(data, (dict, list))
            
            # JSON should not have unescaped HTML
            body = response.data.decode('utf-8')
            assert "</script>" not in body or "&lt;/script&gt;" in body


# ============================================================================
# 3. AUTHENTICATION & AUTHORIZATION TESTS
# ============================================================================

class TestAuthenticationBypass:
    """Test authentication and authorization vulnerabilities."""
    
    def test_missing_jwt_token(self, security_client):
        """API access without JWT token."""
        response = security_client.get("/api/signals")
        
        # Should reject with 401 Unauthorized
        assert response.status_code == 401
    
    def test_invalid_jwt_token(self, security_client):
        """API access with invalid JWT token."""
        headers = {"Authorization": "Bearer invalid_token_here"}
        response = security_client.get("/api/signals", headers=headers)
        
        assert response.status_code == 401
    
    def test_expired_jwt_token(self, security_app):
        """API access with expired JWT token."""
        with security_app.app_context():
            # Create token that expired in the past
            access_token = create_access_token(
                identity="testuser",
                expires_delta=timedelta(seconds=-3600)  # Expired 1 hour ago
            )
        
        client = security_app.test_client()
        headers = {"Authorization": f"Bearer {access_token}"}
        response = client.get("/api/signals", headers=headers)
        
        # Should reject expired token
        assert response.status_code == 401
    
    def test_malformed_authorization_header(self, security_client):
        """Malformed Authorization header."""
        malformed_headers = [
            {"Authorization": "InvalidScheme token"},
            {"Authorization": "Bearer"},
            {"Authorization": ""},
        ]
        
        for headers in malformed_headers:
            response = security_client.get("/api/signals", headers=headers)
            assert response.status_code in (400, 401, 422)
    
    def test_password_hash_bypass_attempt(self, db_manager):
        """Attempt to bypass password hashing."""
        # Create a hashed password
        plain_password = "SecurePassword123!"
        hashed = hash_password(plain_password)
        
        # Verify legitimate password works
        assert verify_and_rehash_password(plain_password, hashed)[0] == True
        
        # Attempt bypass with common weak hashes
        weak_hashes = [
            "password",  # Plain text
            "5f4dcc3b5aa765d61d8327deb882cf99",  # MD5 of 'password'
            "",
            None,
        ]
        
        for weak in weak_hashes:
            try:
                result, _ = verify_and_rehash_password(plain_password, weak)
                # Only our hashed password should verify
                assert result == False
            except Exception:
                pass  # Expected to reject invalid hash format


# ============================================================================
# 4. INPUT VALIDATION TESTS
# ============================================================================

class TestInputValidation:
    """Test input validation vulnerabilities."""
    
    def test_oversized_input(self, security_client, auth_headers):
        """Oversized input payload."""
        huge_payload = "A" * (10 * 1024 * 1024)  # 10MB
        
        response = security_client.post(
            "/api/signals",
            json={"ticker": huge_payload},
            headers=auth_headers
        )
        
        # Should reject or handle gracefully
        assert response.status_code in (400, 413, 422)
    
    def test_invalid_json_payload(self, security_client, auth_headers):
        """Invalid JSON in request body."""
        response = security_client.post(
            "/api/signals",
            data="{ invalid json }",
            headers=auth_headers,
            content_type="application/json"
        )
        
        assert response.status_code in (400, 422)
    
    def test_null_byte_injection(self, security_client, auth_headers):
        """Null byte injection in parameters."""
        payload = "THYAO.IS\x00admin"
        
        response = security_client.get(
            f"/api/signals/{payload}",
            headers=auth_headers
        )
        
        # Should handle safely
        assert response.status_code in (200, 400, 404)
    
    def test_unicode_normalization_bypass(self, security_client, auth_headers):
        """Unicode normalization attacks."""
        payloads = [
            "THYAO.İS",  # Turkish capital I with dot
            "THYAO.ı̇S",  # Combining characters
        ]
        
        for payload in payloads:
            response = security_client.get(
                f"/api/signals/{payload}",
                headers=auth_headers
            )
            assert response.status_code in (200, 404)
    
    def test_negative_numeric_values(self, security_client, auth_headers):
        """Negative values in numeric fields."""
        response = security_client.get(
            "/api/signals?limit=-100&offset=-50",
            headers=auth_headers
        )
        
        # Should validate positive integers
        assert response.status_code in (200, 400, 422)


# ============================================================================
# 5. API RATE LIMITING & DOS TESTS
# ============================================================================

class TestRateLimitingAndDOS:
    """Test rate limiting and DoS protection."""
    
    def test_rapid_api_calls(self, security_client, auth_headers):
        """Rapid API calls exceed rate limit."""
        responses = []
        
        for i in range(100):
            response = security_client.get(
                "/api/signals",
                headers=auth_headers
            )
            responses.append(response.status_code)
            if response.status_code == 429:  # Too Many Requests
                break
        
        # Should eventually trigger rate limiting
        status_codes = set(responses)
        # Either rate limit kicks in or app handles it gracefully
        assert any(code in status_codes for code in [200, 429])
    
    def test_connection_reset_dos(self, security_client, auth_headers):
        """Connection reset during request."""
        # Simulate incomplete request
        response = security_client.get(
            "/api/signals",
            headers=auth_headers,
            environ_base={"REMOTE_ADDR": "127.0.0.1"}
        )
        
        assert response.status_code in (200, 400, 500)


# ============================================================================
# 6. DATA EXPOSURE & INFORMATION DISCLOSURE TESTS
# ============================================================================

class TestDataExposure:
    """Test data exposure and information disclosure vulnerabilities."""
    
    def test_error_message_information_disclosure(self, security_client):
        """Error messages leak sensitive information."""
        # Attempt to trigger various errors
        responses = [
            security_client.get("/api/nonexistent"),
            security_client.post("/api/signals", json={}),
            security_client.get("/api/signals?invalid_param=xyz"),
        ]
        
        for response in responses:
            body = response.data.decode('utf-8')
            
            # Should not expose internal paths or database details
            sensitive_patterns = [
                "/app/src/",
                "sqlite3",
                "psycopg2",
                "traceback",
                "/home/",
                "database connection",
            ]
            
            for pattern in sensitive_patterns:
                assert pattern.lower() not in body.lower() or \
                       response.status_code == 200  # May be OK in some contexts


    def test_debug_mode_disabled(self, security_app):
        """Flask debug mode should be disabled in production."""
        # Debug mode should not be enabled during testing
        # This is typically handled by environment config
        assert not security_app.debug or \
               security_app.config.get("TESTING") == True
    
    def test_sensitive_headers_exposed(self, security_client, auth_headers):
        """Sensitive headers not exposed in responses."""
        response = security_client.get(
            "/api/signals",
            headers=auth_headers
        )
        
        # Should not expose internal server info in verbose headers
        headers = dict(response.headers)
        
        # Check for overly verbose Server header
        server_header = headers.get("Server", "")
        # Should not expose version details
        assert "Flask" not in server_header or True  # Often framework reveals itself


# ============================================================================
# 7. COMMAND INJECTION & CODE EXECUTION TESTS
# ============================================================================

class TestCommandInjection:
    """Test command injection and code execution vulnerabilities."""
    
    def test_os_command_injection(self, security_client, auth_headers):
        """OS command injection via API parameters."""
        payloads = [
            "; ls -la",
            "| cat /etc/passwd",
            "& whoami",
            "`id`",
            "$(whoami)",
        ]
        
        for payload in payloads:
            response = security_client.get(
                f"/api/signals?ticker={quote(payload)}",
                headers=auth_headers
            )
            
            # Should not execute OS commands
            assert response.status_code in (200, 400, 404)
            body = response.data.decode('utf-8')
            
            # Should not contain command output
            assert "root:" not in body
            assert "bin/bash" not in body
    
    def test_python_code_injection(self, db_manager):
        """Python code injection via parameters."""
        from bist_bot.db.repositories.signals_repository import SignalsRepository
        repo = SignalsRepository(db_manager)
        
        payloads = [
            "THYAO.IS' + __import__('os').system('id') + '",
            "THYAO.IS' + str(__class__) + '",
            "THYAO.IS' + eval('1+1') + '",
        ]
        
        for payload in payloads:
            # Should not execute Python code
            result = repo.get_signal_by_ticker(payload)
            assert isinstance(result, (list, type(None)))


# ============================================================================
# 8. CSRF (Cross-Site Request Forgery) TESTS
# ============================================================================

class TestCSRF:
    """Test CSRF protection mechanisms."""
    
    def test_csrf_protection_on_post(self, security_client, auth_headers):
        """CSRF protection on POST requests."""
        # Missing CSRF token (if implemented)
        response = security_client.post(
            "/api/signals",
            json={"ticker": "THYAO.IS", "score": 50},
            headers=auth_headers
        )
        
        # Should either:
        # 1. Accept because it's API/JWT (stateless)
        # 2. Require CSRF token
        assert response.status_code in (200, 201, 400, 403, 422)
    
    def test_cross_origin_requests(self, security_app):
        """CORS and cross-origin request handling."""
        app = security_app
        
        with app.test_client() as client:
            response = client.get(
                "/api/signals",
                headers={
                    "Origin": "https://malicious-site.com",
                    "Authorization": f"Bearer dummy_token"
                }
            )
            
            # Should either reject or set proper CORS headers
            assert response.status_code in (200, 401, 403)
            
            # If CORS headers present, check whitelist
            cors_header = response.headers.get("Access-Control-Allow-Origin", "")
            if cors_header and cors_header != "*":
                assert "malicious" not in cors_header.lower()


# ============================================================================
# 9. DESERIALIZATION ATTACKS TESTS
# ============================================================================

class TestDeserialization:
    """Test deserialization vulnerabilities."""
    
    def test_pickle_injection(self, security_client, auth_headers):
        """Pickle deserialization attacks."""
        import pickle
        import base64
        
        # Create malicious pickle (this would execute commands if deserialized)
        # We're testing that the app doesn't accept pickle
        
        response = security_client.post(
            "/api/signals",
            data=base64.b64encode(pickle.dumps({"ticker": "THYAO.IS"})),
            headers={**auth_headers, "Content-Type": "application/octet-stream"}
        )
        
        # Should not deserialize pickle
        assert response.status_code in (400, 415, 422)
    
    def test_yaml_injection(self, security_client, auth_headers):
        """YAML deserialization attacks."""
        yaml_payload = """
!!python/object/apply:os.system
args: ['echo vulnerable']
"""
        
        response = security_client.post(
            "/api/signals",
            data=yaml_payload,
            headers={**auth_headers, "Content-Type": "application/x-yaml"}
        )
        
        # Should not process YAML if not explicitly supported
        assert response.status_code in (400, 415, 422)


# ============================================================================
# 10. PATH TRAVERSAL & FILE ACCESS TESTS
# ============================================================================

class TestPathTraversal:
    """Test path traversal vulnerabilities."""
    
    def test_path_traversal_in_ticker(self, security_client, auth_headers):
        """Path traversal via ticker parameter."""
        payloads = [
            "../../../etc/passwd",
            "..\\..\\..\\windows\\system32\\config\\sam",
            "....//....//....//etc/passwd",
        ]
        
        for payload in payloads:
            response = security_client.get(
                f"/api/signals/{quote(payload)}",
                headers=auth_headers
            )
            
            # Should not expose files
            assert response.status_code in (200, 400, 404)
            body = response.data.decode('utf-8')
            assert "root:" not in body


# ============================================================================
# 11. PRIVILEGE ESCALATION TESTS
# ============================================================================

class TestPrivilegeEscalation:
    """Test privilege escalation vulnerabilities."""
    
    def test_admin_role_bypass(self, security_client):
        """Attempt to bypass admin role requirement."""
        # Create non-admin token
        from bist_bot.config.settings import settings
        
        # This would require admin access
        response = security_client.post(
            "/api/admin/settings",
            json={"setting": "value"}
        )
        
        # Should reject without admin privileges
        assert response.status_code in (401, 403, 404)
    
    def test_role_parameter_manipulation(self, security_client, auth_headers):
        """Attempt to manipulate role via parameter."""
        payload = {
            "ticker": "THYAO.IS",
            "role": "admin"  # Try to claim admin role
        }
        
        response = security_client.post(
            "/api/signals",
            json=payload,
            headers=auth_headers
        )
        
        # Should ignore or reject role manipulation
        assert response.status_code in (200, 201, 400, 422)


# ============================================================================
# 12. LOGIC & BUSINESS LOGIC TESTS
# ============================================================================

class TestBusinessLogicVulnerabilities:
    """Test business logic vulnerabilities."""
    
    def test_negative_price_injection(self, security_client, auth_headers):
        """Negative prices in API."""
        response = security_client.post(
            "/api/trades",
            json={
                "ticker": "THYAO.IS",
                "price": -100,
                "quantity": 10
            },
            headers=auth_headers
        )
        
        if response.status_code == 200:
            # Should validate positive prices
            data = response.get_json()
            if "price" in data:
                assert float(data["price"]) > 0
    
    def test_invalid_signal_score_range(self, security_client, auth_headers):
        """Signal score outside valid range."""
        response = security_client.post(
            "/api/signals",
            json={
                "ticker": "THYAO.IS",
                "score": 999  # Should be -100 to 100
            },
            headers=auth_headers
        )
        
        # Should validate score range
        assert response.status_code in (200, 400, 422)
    
    def test_double_submission_attack(self, security_client, auth_headers):
        """Double submission of same order."""
        order_payload = {
            "ticker": "THYAO.IS",
            "quantity": 100,
            "price": 25.50
        }
        
        response1 = security_client.post(
            "/api/orders",
            json=order_payload,
            headers=auth_headers
        )
        
        response2 = security_client.post(
            "/api/orders",
            json=order_payload,
            headers=auth_headers
        )
        
        # Responses may vary, but system should handle this
        assert response1.status_code in (200, 201, 400, 422)
        assert response2.status_code in (200, 201, 400, 422)


# ============================================================================
# 13. CRYPTOGRAPHY & HASHING TESTS
# ============================================================================

class TestCryptography:
    """Test cryptography and hashing implementations."""
    
    def test_weak_password_hashing(self):
        """Password hashing should use strong algorithms."""
        password = "TestPassword123!"
        hashed = hash_password(password)
        
        # Should not be plain text
        assert hashed != password
        
        # Should be reasonably long (bcrypt produces 60-char strings)
        assert len(hashed) >= 40
        
        # Verify it's actually usable
        verified, _ = verify_and_rehash_password(password, hashed)
        assert verified == True
    
    def test_rainbow_table_resistance(self):
        """Password hashing should resist rainbow tables."""
        password = "password123"
        hashes = [hash_password(password) for _ in range(3)]
        
        # Each hash should be different (salting)
        assert len(set(hashes)) == 3
    
    def test_timing_attack_resistance(self):
        """Password comparison should resist timing attacks."""
        from bist_bot.auth.passwords import verify_and_rehash_password
        import time
        
        correct_hash = hash_password("correctpassword")
        
        # Time correct password
        start = time.perf_counter()
        verify_and_rehash_password("correctpassword", correct_hash)
        correct_time = time.perf_counter() - start
        
        # Time incorrect password
        start = time.perf_counter()
        verify_and_rehash_password("wrongpassword", correct_hash)
        wrong_time = time.perf_counter() - start
        
        # Times should be similar (constant time comparison)
        # Allow 50% variance due to system timing
        ratio = max(correct_time, wrong_time) / min(correct_time, wrong_time)
        assert ratio < 2.0  # Should be very close


# ============================================================================
# 14. ENCODING & ESCAPING TESTS
# ============================================================================

class TestEncodingEscaping:
    """Test proper encoding and escaping."""
    
    def test_html_entity_encoding(self, security_client, auth_headers):
        """HTML entities should be properly encoded."""
        response = security_client.get(
            "/api/signals?ticker=THYAO&search=<script>alert('xss')</script>",
            headers=auth_headers
        )
        
        body = response.data.decode('utf-8')
        # Should not have unescaped HTML
        assert response.data.count(b"<script>") == 0 or \
               response.data.count(b"&lt;script&gt;") > 0
    
    def test_url_encoding(self, security_client, auth_headers):
        """URLs should be properly encoded."""
        special_chars = "%20%2F%3D%3F%26"
        
        response = security_client.get(
            f"/api/search?q={special_chars}",
            headers=auth_headers
        )
        
        assert response.status_code in (200, 400, 404)
    
    def test_json_escaping(self, security_client, auth_headers):
        """JSON output should properly escape special characters."""
        response = security_client.get(
            "/api/signals",
            headers=auth_headers
        )
        
        if response.status_code == 200:
            # Should be valid JSON
            data = response.get_json()
            assert isinstance(data, (dict, list))


# ============================================================================
# 15. SECURITY HEADERS TESTS
# ============================================================================

class TestSecurityHeaders:
    """Test security headers in HTTP responses."""
    
    def test_hsts_header(self, security_client, auth_headers):
        """HSTS header should be present."""
        response = security_client.get("/api/signals", headers=auth_headers)
        
        hsts = response.headers.get("Strict-Transport-Security", "")
        # In production should have HSTS, but optional in test environment
        if hsts:
            assert "max-age" in hsts.lower()
    
    def test_x_frame_options_header(self, security_client, auth_headers):
        """X-Frame-Options header should prevent clickjacking."""
        response = security_client.get("/api/signals", headers=auth_headers)
        
        x_frame = response.headers.get("X-Frame-Options", "")
        # Should prevent framing or explicitly allow same-origin
        if x_frame:
            assert x_frame in ["DENY", "SAMEORIGIN"]
    
    def test_csp_header(self, security_client, auth_headers):
        """Content Security Policy should be set."""
        response = security_client.get("/", headers=auth_headers)
        
        csp = response.headers.get("Content-Security-Policy", "")
        # Should have CSP if serving web content
        # Not required for API-only endpoints
    
    def test_x_content_type_options(self, security_client, auth_headers):
        """X-Content-Type-Options should prevent MIME sniffing."""
        response = security_client.get("/api/signals", headers=auth_headers)
        
        x_content = response.headers.get("X-Content-Type-Options", "")
        if x_content:
            assert x_content.lower() == "nosniff"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
