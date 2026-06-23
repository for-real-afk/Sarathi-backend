import sys
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

def run_tests():
    print("=== STARTING SAARTHI AUTHENTICATION & RBAC TESTING ===")
    
    # ── TEST 1: LOGIN WITH DEFAULT SEEDED USERS ──
    print("\n[Test 1] Testing logins for default seeded users...")
    
    # 1.1 Admin login
    res = client.post("/api/auth/login", json={"username_or_email": "admin", "password": "admin123"})
    assert res.status_code == 200, f"Admin login failed: {res.text}"
    admin_tokens = res.json()
    assert "access_token" in admin_tokens
    assert "refresh_token" in admin_tokens
    assert "ADMIN" in admin_tokens["roles"]
    print("✓ Admin login successful.")

    # 1.2 Volunteer login
    res = client.post("/api/auth/login", json={"username_or_email": "volunteer", "password": "volunteer123"})
    assert res.status_code == 200, f"Volunteer login failed: {res.text}"
    volunteer_tokens = res.json()
    assert "VOLUNTEER" in volunteer_tokens["roles"]
    print("✓ Volunteer login successful.")

    # 1.3 Citizen login
    res = client.post("/api/auth/login", json={"username_or_email": "citizen", "password": "citizen123"})
    assert res.status_code == 200, f"Citizen login failed: {res.text}"
    citizen_tokens = res.json()
    assert "CITIZEN" in citizen_tokens["roles"]
    print("✓ Citizen login successful.")

    # 1.4 Invalid credentials
    res = client.post("/api/auth/login", json={"username_or_email": "admin", "password": "wrongpassword"})
    assert res.status_code == 401, f"Expected 401 Unauthorized, got {res.status_code}"
    print("✓ Invalid credentials successfully rejected.")

    # ── TEST 2: AUTHORIZATION MIDDLEWARE ON PROTECTED ROUTES ──
    print("\n[Test 2] Testing access restrictions on protected prefixes...")

    headers_admin = {"Authorization": f"Bearer {admin_tokens['access_token']}"}
    headers_volunteer = {"Authorization": f"Bearer {volunteer_tokens['access_token']}"}
    headers_citizen = {"Authorization": f"Bearer {citizen_tokens['access_token']}"}

    # 2.1 Access without token
    for route in ["/admin/dashboard", "/volunteers/dashboard", "/citizens/dashboard", "/cases/dashboard"]:
        res = client.get(route)
        assert res.status_code == 401, f"Route {route} should reject anonymous requests, got {res.status_code}"
    print("✓ Anonymous requests blocked on all protected routes.")

    # 2.2 Access /admin prefix (Only ADMIN allowed)
    res = client.get("/admin/dashboard", headers=headers_admin)
    assert res.status_code == 200, f"Admin should access admin dashboard, got {res.status_code}"
    
    res = client.get("/admin/dashboard", headers=headers_volunteer)
    assert res.status_code == 403, f"Volunteer should be blocked from admin dashboard, got {res.status_code}"
    
    res = client.get("/admin/dashboard", headers=headers_citizen)
    assert res.status_code == 403, f"Citizen should be blocked from admin dashboard, got {res.status_code}"
    print("✓ Admin route access restrictions validated.")

    # 2.3 Access /volunteers prefix (ADMIN, CENTRAL_HUB, LOCAL_HUB allowed)
    res = client.get("/volunteers/dashboard", headers=headers_admin)
    assert res.status_code == 200, f"Admin should access volunteer portal, got {res.status_code}"

    res = client.get("/volunteers/dashboard", headers=headers_volunteer)
    assert res.status_code == 403, f"Volunteer should be blocked from volunteer portal, got {res.status_code}"

    res = client.get("/volunteers/dashboard", headers=headers_citizen)
    assert res.status_code == 403, f"Citizen should be blocked from volunteer portal, got {res.status_code}"
    print("✓ Volunteer route access restrictions validated.")

    # 2.4 Access /citizens prefix (ADMIN, CENTRAL_HUB, LOCAL_HUB, VOLUNTEER allowed)
    res = client.get("/citizens/dashboard", headers=headers_admin)
    assert res.status_code == 200, f"Admin should access citizen portal, got {res.status_code}"

    res = client.get("/citizens/dashboard", headers=headers_volunteer)
    assert res.status_code == 200, f"Volunteer should access citizen portal, got {res.status_code}"

    res = client.get("/citizens/dashboard", headers=headers_citizen)
    assert res.status_code == 403, f"Citizen should be blocked from citizen portal, got {res.status_code}"
    print("✓ Citizen route access restrictions validated.")

    # 2.5 Access /cases prefix (All authenticated roles allowed)
    res = client.get("/cases/dashboard", headers=headers_admin)
    assert res.status_code == 200, f"Admin should access cases, got {res.status_code}"

    res = client.get("/cases/dashboard", headers=headers_volunteer)
    assert res.status_code == 200, f"Volunteer should access cases, got {res.status_code}"

    res = client.get("/cases/dashboard", headers=headers_citizen)
    assert res.status_code == 200, f"Citizen should access cases, got {res.status_code}"
    print("✓ Cases route access restrictions validated.")

    # ── TEST 3: TOKEN REFRESH FLOW ──
    print("\n[Test 3] Testing token refresh...")
    res = client.post("/api/auth/refresh", json={"refresh_token": citizen_tokens["refresh_token"]})
    assert res.status_code == 200, f"Token refresh failed: {res.text}"
    refreshed_tokens = res.json()
    assert refreshed_tokens["access_token"] != citizen_tokens["access_token"]
    
    # Try using the new access token
    headers_new_citizen = {"Authorization": f"Bearer {refreshed_tokens['access_token']}"}
    res = client.get("/cases/dashboard", headers=headers_new_citizen)
    assert res.status_code == 200, "New access token should be valid"
    print("✓ Token refresh successfully validated.")

    # ── TEST 4: USER REGISTRATION ──
    print("\n[Test 4] Testing new user registration...")
    import uuid
    unique_suffix = str(uuid.uuid4())[:8]
    reg_payload = {
        "username": f"newlocalhub_{unique_suffix}",
        "email": f"newlocal_{unique_suffix}@saarthi.org",
        "password": "hubpassword123",
        "roles": ["LOCAL_HUB"]
    }
    res = client.post("/api/auth/register", json=reg_payload)
    assert res.status_code == 201, f"Registration failed: {res.text}"
    new_user_tokens = res.json()
    assert "LOCAL_HUB" in new_user_tokens["roles"]
    
    # Verify the new user can access /volunteers/dashboard (LOCAL_HUB is allowed)
    headers_new_user = {"Authorization": f"Bearer {new_user_tokens['access_token']}"}
    res = client.get("/volunteers/dashboard", headers=headers_new_user)
    assert res.status_code == 200, f"New LOCAL_HUB user should access volunteers portal, got {res.status_code}"
    print("✓ User registration and role mapping validated.")

    # ── TEST 5: PASSWORD RESET ──
    print("\n[Test 5] Testing password reset...")
    reset_payload = {
        "username_or_email": "citizen",
        "new_password": "newcitizenpassword123"
    }
    res = client.post("/api/auth/password-reset", json=reset_payload)
    assert res.status_code == 200, f"Password reset failed: {res.text}"
    
    # Attempt login with old password (should fail)
    res = client.post("/api/auth/login", json={"username_or_email": "citizen", "password": "citizen123"})
    assert res.status_code == 401, f"Old password should not work after reset, got {res.status_code}"

    # Login with new password (should succeed)
    res = client.post("/api/auth/login", json={"username_or_email": "citizen", "password": "newcitizenpassword123"})
    assert res.status_code == 200, f"Login with new password failed: {res.text}"
    print("✓ Password reset flow validated.")

    # ── TEST 6: LOGOUT AND TOKEN REVOCATION ──
    print("\n[Test 6] Testing logout and token revocation...")
    # Refresh token logout
    res = client.post("/api/auth/logout", json={"refresh_token": refreshed_tokens["refresh_token"]})
    assert res.status_code == 200, f"Logout failed: {res.text}"
    
    # Verify the logged out refresh token cannot be refreshed anymore
    res = client.post("/api/auth/refresh", json={"refresh_token": refreshed_tokens["refresh_token"]})
    assert res.status_code == 401, f"Revoked refresh token should be rejected, got {res.status_code}"
    print("✓ Logout and refresh token revocation validated.")

    print("\n==============================================")
    print("ALL AUTHENTICATION & RBAC TESTS PASSED SUCCESSFULLY!")
    print("==============================================")

if __name__ == "__main__":
    try:
        run_tests()
    except Exception as e:
        print(f"\n❌ ERROR OCCURRED: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
