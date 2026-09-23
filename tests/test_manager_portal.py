"""Comprehensive integration tests for the Manager portal and Admin management of Managers."""

import pytest
import pyotp
from motor.motor_asyncio import AsyncIOMotorClient

from config.settings import settings
from controller.admin_manager_controller import (
    admin_reply_message,
    apply_message_proposal_to_central,
    approve_access_request,
    deny_access_request,
    get_thread_messages,
    grant_instance_access,
    list_access_requests,
    list_managers,
    list_message_threads,
    revoke_instance_access,
)
from controller.app_instance_controller import create_app_instance, get_app_instance
from controller.category_controller import create_category
from controller.manager_controller import (
    change_manager_password,
    check_username_available,
    confirm_and_enable_manager_2fa,
    create_access_request,
    create_manager_key,
    delete_manager_key,
    disable_manager_2fa,
    get_manager_accessible_instance_ids,
    get_manager_by_id,
    get_manager_dashboard_counts,
    initiate_manager_2fa,
    list_manager_keys,
    login_manager,
    register_manager,
    revoke_manager_key,
    send_manager_message,
    update_manager_key_rate_limit,
    update_manager_profile,
    verify_manager_instance_access,
    verify_manager_login_2fa,
)
from controller.reference_controller import add_references
from database.collections import (
    API_KEYS,
    APP_INSTANCE_ACCESS,
    APP_INSTANCE_ACCESS_REQUESTS,
    APP_INSTANCES,
    CATEGORIES,
    INSTANCE_CATEGORIES,
    MANAGERS,
    MESSAGES,
)
from database.models.api_key import ApiKeyCreate
from database.models.app_instance import AppInstanceCreate
from database.models.category import CategoryCreate
from database.models.manager_user import ManagerUserCreate
from utils.errors import ConflictError, ForbiddenError, UnauthorizedError, ValidationError


@pytest.fixture(scope="module")
def anyio_backend():
    return "asyncio"


@pytest.fixture(scope="module")
async def db():
    client = AsyncIOMotorClient(settings.mongodb_uri)
    database = client[settings.mongodb_db_name]
    yield database
    # Clean up test manager data
    await database[MANAGERS].delete_many({"username": {"$regex": "^test_"}})
    await database[APP_INSTANCES].delete_many({"name": {"$regex": "^Test App Mgr"}})
    await database[MESSAGES].delete_many({"content": {"$regex": "^Test message|^badge_test|^Unread message"}})
    await database[CATEGORIES].delete_many({"name": {"$regex": "^Test Central Cat"}})
    client.close()


# =========================================================================
# 1. Registration, Username Uniqueness & Status
# =========================================================================

@pytest.mark.anyio
async def test_username_availability_and_registration(db):
    u1 = "test_mgr_alpha"
    # Clean prior run if any
    await db[MANAGERS].delete_many({"username": {"$in": [u1, "test_mgr_beta"]}})

    # Check available
    check1 = await check_username_available(db, u1)
    assert check1["available"] is True

    # Register manager
    data = ManagerUserCreate(
        username=u1,
        email="alpha@example.com",
        password="Password123!",
        confirm_password="Password123!",
    )
    created = await register_manager(db, data)
    assert created["username"] == u1
    assert created["role"] == "manager"
    assert created["status"] == "active"
    assert created["is_active"] is True

    # Check available again -> False
    check2 = await check_username_available(db, u1)
    assert check2["available"] is False

    # Attempt duplicate registration -> ConflictError
    with pytest.raises(ConflictError):
        await register_manager(db, data)


# =========================================================================
# 2. Authentication & 2FA Lifecycle
# =========================================================================

@pytest.mark.anyio
async def test_manager_auth_and_2fa_flow(db):
    username = "test_mgr_2fa_user"
    await db[MANAGERS].delete_many({"username": username})

    # Register
    reg_data = ManagerUserCreate(
        username=username,
        email="2fa_test@example.com",
        password="SecurePassword999",
        confirm_password="SecurePassword999",
    )
    user = await register_manager(db, reg_data)
    user_id = user["id"]

    # Direct password login without 2FA
    login_user = await login_manager(db, username, "SecurePassword999")
    assert login_user["username"] == username
    assert login_user.get("is_2fa_enabled") is False

    # Initiate 2FA
    setup_data = await initiate_manager_2fa(db, user_id)
    secret = setup_data["secret"]
    assert secret is not None
    assert setup_data["qr_code_url"].startswith("data:image/png;base64,")

    # Generate valid TOTP code using pyotp
    totp = pyotp.TOTP(secret)
    valid_code = totp.now()

    # Confirm and enable 2FA
    backup_codes = await confirm_and_enable_manager_2fa(db, user_id, valid_code)
    assert len(backup_codes) == 8
    first_backup_code = backup_codes[0]

    # Check updated manager doc
    updated = await get_manager_by_id(db, user_id)
    assert updated["is_2fa_enabled"] is True

    # Verify login 2FA with valid TOTP code
    verified = await verify_manager_login_2fa(db, user_id, totp.now())
    assert verified["username"] == username

    # Verify login 2FA with single-use backup code
    backup_verified = await verify_manager_login_2fa(db, user_id, first_backup_code)
    assert backup_verified["username"] == username

    # Try reusing the same backup code -> UnauthorizedError
    with pytest.raises(UnauthorizedError):
        await verify_manager_login_2fa(db, user_id, first_backup_code)

    # Disable 2FA with password
    disabled = await disable_manager_2fa(db, user_id, "SecurePassword999")
    assert disabled is True

    # Check 2FA disabled
    mgr_after = await get_manager_by_id(db, user_id)
    assert mgr_after["is_2fa_enabled"] is False


# =========================================================================
# 3. Cross-Manager Access Isolation
# =========================================================================

@pytest.mark.anyio
async def test_cross_manager_isolation(db):
    u_m1 = "test_mgr_iso_1"
    u_m2 = "test_mgr_iso_2"
    await db[MANAGERS].delete_many({"username": {"$in": [u_m1, u_m2]}})

    m1 = await register_manager(db, ManagerUserCreate(username=u_m1, password="Password123!"))
    m2 = await register_manager(db, ManagerUserCreate(username=u_m2, password="Password123!"))
    m1_id = m1["id"]
    m2_id = m2["id"]

    # M1 creates App Instance 1
    app1 = await create_app_instance(
        db, AppInstanceCreate(name="Test App Mgr 1", package_name="com.test.mgr1", owner_id=m1_id)
    )
    # M2 creates App Instance 2
    app2 = await create_app_instance(
        db, AppInstanceCreate(name="Test App Mgr 2", package_name="com.test.mgr2", owner_id=m2_id)
    )

    # Scoping check: M1 only sees app1
    m1_accessible = await get_manager_accessible_instance_ids(db, m1_id)
    assert app1["id"] in m1_accessible
    assert app2["id"] not in m1_accessible

    # Scoping check: M2 only sees app2
    m2_accessible = await get_manager_accessible_instance_ids(db, m2_id)
    assert app2["id"] in m2_accessible
    assert app1["id"] not in m2_accessible

    # M1 accessing app2 -> ForbiddenError
    with pytest.raises(ForbiddenError):
        await verify_manager_instance_access(db, manager_id=m1_id, instance_id=app2["id"])

    # M1 creating key for app2 -> ForbiddenError
    with pytest.raises(ForbiddenError):
        await create_manager_key(
            db,
            manager_id=m1_id,
            data=ApiKeyCreate(name="M1 Malicious Key", app_instance_id=app2["id"]),
        )

    # M2 creates key for app2
    m2_key = await create_manager_key(
        db,
        manager_id=m2_id,
        data=ApiKeyCreate(name="M2 Legitimate Key", app_instance_id=app2["id"]),
    )

    # M1 listing keys -> cannot see M2's key
    m1_keys = await list_manager_keys(db, m1_id)
    assert not any(k["id"] == m2_key.id for k in m1_keys)

    # M1 revoking M2's key -> ForbiddenError
    with pytest.raises(ForbiddenError):
        await revoke_manager_key(db, manager_id=m1_id, key_id=m2_key.id)

    # M1 deleting M2's key -> ForbiddenError
    with pytest.raises(ForbiddenError):
        await delete_manager_key(db, manager_id=m1_id, key_id=m2_key.id)


# =========================================================================
# 4. Central Data Importing & Scoped Dashboard Counts
# =========================================================================

@pytest.mark.anyio
async def test_central_import_and_scoped_counts(db):
    u_m3 = "test_mgr_iso_3"
    await db[MANAGERS].delete_many({"username": u_m3})
    m3 = await register_manager(db, ManagerUserCreate(username=u_m3, password="Password123!"))
    m3_id = m3["id"]

    # Create app instance for M3
    app3 = await create_app_instance(
        db, AppInstanceCreate(name="Test App Mgr 3", package_name="com.test.mgr3", owner_id=m3_id)
    )

    # Create a central category
    central_cat = await create_category(db, CategoryCreate(name="Test Central Cat 99"))

    # Initial counts -> 1 instance, 0 categories
    counts_before = await get_manager_dashboard_counts(db, m3_id)
    assert counts_before["instances"] == 1
    assert counts_before["categories"] == 0

    # Import central category into M3's app instance
    import_res = await add_references(
        db, app_instance_id=app3["id"], category_ids=[central_cat["id"]]
    )
    assert import_res["added_categories"] >= 1

    # Counts after -> categories should reflect imported reference
    counts_after = await get_manager_dashboard_counts(db, m3_id)
    assert counts_after["categories"] == 1


# =========================================================================
# 5. Admin Grant/Revoke & Access Request Queue
# =========================================================================

@pytest.mark.anyio
async def test_admin_access_grant_and_request_queue(db):
    u_m4 = "test_mgr_iso_4"
    await db[MANAGERS].delete_many({"username": u_m4})
    m4 = await register_manager(db, ManagerUserCreate(username=u_m4, password="Password123!"))
    m4_id = m4["id"]

    # Target instance created by admin/someone else
    shared_app = await create_app_instance(
        db, AppInstanceCreate(name="Test App Mgr Shared", package_name="com.test.shared")
    )
    shared_id = shared_app["id"]

    # M4 submits access request
    req = await create_access_request(db, manager_id=m4_id, app_instance_id=shared_id, notes="Need access for testing")
    assert req["status"] == "pending"

    # Admin reviews access requests
    requests = await list_access_requests(db, status="pending")
    matching = [r for r in requests if r["id"] == req["id"]]
    assert len(matching) == 1

    # Admin approves request
    appr = await approve_access_request(db, request_id=req["id"])
    assert appr["success"] is True

    # Verify M4 now has access to shared_app
    m4_accessible = await get_manager_accessible_instance_ids(db, m4_id)
    assert shared_id in m4_accessible

    # Admin revokes access
    rev = await revoke_instance_access(db, manager_id=m4_id, app_instance_id=shared_id)
    assert rev["success"] is True

    # Verify M4 no longer has access
    m4_accessible_after = await get_manager_accessible_instance_ids(db, m4_id)
    assert shared_id not in m4_accessible_after


# =========================================================================
# 6. Messaging & Proposal Application to Central Data
# =========================================================================

@pytest.mark.anyio
async def test_messaging_and_proposal_application(db):
    u_m5 = "test_mgr_iso_5"
    await db[MANAGERS].delete_many({"username": u_m5})
    m5 = await register_manager(db, ManagerUserCreate(username=u_m5, password="Password123!"))
    m5_id = m5["id"]

    # Manager sends message with category proposal
    msg = await send_manager_message(
        db,
        manager_id=m5_id,
        sender_name="Manager 5",
        content="Test message: Please add this new category",
        payload_type="category",
        data_payload={"name": "Test Central Cat Proposed"},
    )
    assert msg["status"] == "unread"
    assert msg["payload_type"] == "category"

    # Admin lists threads
    threads = await list_message_threads(db)
    matching_thread = [t for t in threads if t["manager_id"] == m5_id]
    assert len(matching_thread) == 1

    # Admin applies proposal to central data
    applied = await apply_message_proposal_to_central(db, message_id=msg["id"])
    assert applied["success"] is True
    assert applied["created_record"]["name"] == "Test Central Cat Proposed"

    # Verify category exists in central collection
    cat_in_db = await db[CATEGORIES].find_one({"name": "Test Central Cat Proposed"})
    assert cat_in_db is not None


# =========================================================================
# 7. HTTP Endpoint & Cookie Session Verification
# =========================================================================

@pytest.mark.anyio
async def test_manager_http_endpoints(db):
    from httpx import ASGITransport, AsyncClient
    from inits.server import create_app

    app = create_app()
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Live username check endpoint
        res = await client.get("/api/manager/check-username?u=new_unique_mgr")
        assert res.status_code == 200
        assert res.json()["available"] is True

        # 2. Register page GET
        res_reg = await client.get("/manager/register")
        assert res_reg.status_code == 200
        assert "Create Manager Account" in res_reg.text

        # 3. Register POST
        u_http = "test_mgr_http_client"
        await db[MANAGERS].delete_many({"username": u_http})
        res_submit = await client.post(
            "/manager/register",
            data={
                "username": u_http,
                "email": "http_test@example.com",
                "password": "Password123!",
                "confirm_password": "Password123!",
            },
            follow_redirects=False,
        )
        assert res_submit.status_code == 303
        assert "manager_session" in res_submit.cookies

        # 4. Access manager dashboard with cookie
        res_dash = await client.get("/manager/dashboard", cookies=res_submit.cookies)
        assert res_dash.status_code == 200
        assert "Welcome" in res_dash.text

        # 5. Access read-only categories
        res_cats = await client.get("/manager/categories", cookies=res_submit.cookies)
        assert res_cats.status_code == 200
        assert "Central Categories" in res_cats.text

        # 6. Access read-only subcategories
        res_subs = await client.get("/manager/subcategories", cookies=res_submit.cookies)
        assert res_subs.status_code == 200
        assert "Central Subcategories" in res_subs.text

        # 7. Access read-only assets
        res_assets = await client.get("/manager/assets", cookies=res_submit.cookies)
        assert res_assets.status_code == 200
        assert "Central Creative Assets" in res_assets.text

        # 8. Access manager app instances
        res_inst = await client.get("/manager/instances", cookies=res_submit.cookies)
        assert res_inst.status_code == 200
        assert "App Instances" in res_inst.text

        # 9. Access manager API keys
        res_keys = await client.get("/manager/keys", cookies=res_submit.cookies)
        assert res_keys.status_code == 200
        assert "API Access Keys" in res_keys.text

        # 10. Access manager messages
        res_msgs = await client.get("/manager/messages", cookies=res_submit.cookies)
        assert res_msgs.status_code == 200
        assert "Messages & Central Proposals" in res_msgs.text

        # 11. Access manager profile
        res_prof = await client.get("/manager/profile", cookies=res_submit.cookies)
        assert res_prof.status_code == 200
        assert "Update Profile" in res_prof.text

        # 11b. Access manager settings
        res_sett = await client.get("/manager/settings", cookies=res_submit.cookies)
        assert res_sett.status_code == 200
        assert "Manager Settings" in res_sett.text

        # 12. Access manager analytics
        res_ana = await client.get("/manager/analytics", cookies=res_submit.cookies)
        assert res_ana.status_code == 200
        assert "Application Analytics" in res_ana.text

        # 13. Verify Manager CANNOT access Admin pages (Forbidden/Redirected)
        res_admin_attempt = await client.get("/admin/dashboard", cookies=res_submit.cookies, follow_redirects=False)
        # Should redirect to admin login because admin_session cookie is missing
        assert res_admin_attempt.status_code == 303
        assert "/admin/login" in res_admin_attempt.headers["location"]


@pytest.mark.anyio
async def test_new_manager_features_and_notifications(db):
    """Test 5 new features: subcategory asset count, profile redirect toast, instance overrides/reordering, badges."""
    from httpx import ASGITransport, AsyncClient
    from inits.server import create_app
    from database.collections import APP_INSTANCE_ACCESS, APP_INSTANCE_ACCESS_REQUESTS, INSTANCE_ASSETS, ASSETS, APP_INSTANCES
    from authorization.encryption import sign_session
    from utils.datetimes import utc_now
    from utils.ids import to_object_id

    app = create_app()

    u_test = "test_feat_mgr"
    await db[MANAGERS].delete_many({"username": u_test})
    m = await register_manager(db, ManagerUserCreate(username=u_test, password="Password123!"))
    m_id = m["id"]
    mgr_cookie = {"manager_session": sign_session({"username": u_test, "user_id": m_id, "role": "manager"})}
    admin_cookie = {"admin_session": sign_session({"username": "admin", "user_id": "6aa000000000000000000001"})}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 1. Subcategory page asset count > 0
        res_subs = await client.get("/manager/subcategories", cookies=mgr_cookie)
        assert res_subs.status_code == 200

        # 2. Profile update redirects to dashboard with popup toast
        res_prof = await client.post(
            "/manager/profile",
            data={"display_name": "New Manager Display"},
            cookies=mgr_cookie,
            follow_redirects=False,
        )
        assert res_prof.status_code == 303
        assert res_prof.headers["location"] == "/manager/dashboard?msg=Profile+Updated+Successfully"

        res_dash = await client.get(res_prof.headers["location"], cookies=mgr_cookie)
        assert res_dash.status_code == 200
        assert "Profile Updated Successfully" in res_dash.text

        # 3. Manager instance overrides and reorder
        inst = await db[APP_INSTANCES].find_one({"deleted_at": None})
        if inst:
            inst_id = str(inst["_id"])
            await db[APP_INSTANCE_ACCESS].update_one(
                {"manager_id": to_object_id(m_id), "app_instance_id": inst["_id"]},
                {"$set": {"manager_id": to_object_id(m_id), "app_instance_id": inst["_id"]}},
                upsert=True,
            )
            # Find an instance asset
            sample_asset = await db[ASSETS].find_one({"deleted_at": None})
            if sample_asset:
                await db[INSTANCE_ASSETS].update_one(
                    {"app_instance_id": inst["_id"], "source_id": sample_asset["_id"]},
                    {"$set": {"app_instance_id": inst["_id"], "source_id": sample_asset["_id"], "is_enabled": True, "sequence": 1, "deleted_at": None}},
                    upsert=True,
                )
                target_asset_id = str(sample_asset["_id"])
                res_patch = await client.patch(
                    f"/manager/instances/{inst_id}/assets/{target_asset_id}/override",
                    json={"is_premium": True, "is_enabled": True, "sequence": 50},
                    cookies=mgr_cookie,
                )
                assert res_patch.status_code == 200
                assert res_patch.json()["success"] is True

                res_reorder = await client.post(
                    f"/manager/instances/{inst_id}/reorder",
                    json={"type": "asset", "ordered_ids": [target_asset_id]},
                    cookies=mgr_cookie,
                )
                assert res_reorder.status_code == 200

        # 4. Unread messages notification badges
        now = utc_now()
        await db[MESSAGES].insert_one({
            "manager_id": to_object_id(m_id),
            "sender_role": "manager",
            "sender_id": to_object_id(m_id),
            "sender_name": "Test Feat Manager",
            "content": "Unread message for badge check",
            "status": "unread",
            "created_at": now,
            "updated_at": now,
        })
        res_admin_dash = await client.get("/admin/dashboard", cookies=admin_cookie)
        assert res_admin_dash.status_code == 200
        assert "badge" in res_admin_dash.text

        # 5. Pending access request notification badge for Admin
        if inst:
            await db[APP_INSTANCE_ACCESS_REQUESTS].insert_one({
                "requesting_manager_id": to_object_id(m_id),
                "app_instance_id": inst["_id"],
                "status": "pending",
                "notes": "Access request for badge check",
                "created_at": now,
                "updated_at": now,
            })
            res_admin_dash2 = await client.get("/admin/dashboard", cookies=admin_cookie)
            assert res_admin_dash2.status_code == 200
            assert "badge" in res_admin_dash2.text

        # Cleanup
        await db[MANAGERS].delete_many({"username": u_test})
        await db[MESSAGES].delete_many({"content": "Unread message for badge check"})
        await db[APP_INSTANCE_ACCESS_REQUESTS].delete_many({"notes": "Access request for badge check"})

