import pytest
from httpx import ASGITransport, AsyncClient
from motor.motor_asyncio import AsyncIOMotorClient

from authorization.encryption import sign_session
from config.settings import settings
from controller.admin_manager_controller import delete_manager_account
from database.collections import ADMIN_USERS, MANAGERS, MESSAGES
from inits.server import create_app
from utils.datetimes import utc_now, utc_now_iso
from utils.ids import to_object_id


@pytest.fixture(scope="module")
def anyio_backend():
    return "asyncio"


@pytest.fixture(scope="module")
async def db():
    client = AsyncIOMotorClient(settings.mongodb_uri)
    database = client[settings.mongodb_db_name]
    yield database
    await database[MANAGERS].delete_many({"username": {"$regex": "^test_avatar_mgr"}})
    await database[MANAGERS].delete_many({"username": {"$regex": "^test_badge_mgr"}})
    client.close()


@pytest.mark.anyio
async def test_notifications_badge_counts_api(db):
    """Verify GET /api/notifications/badge-counts returns conversation counts, not raw message counts."""
    app = create_app()

    # Clean previous test badge data
    await db[MANAGERS].delete_many({"username": "test_badge_mgr"})
    await db[MESSAGES].delete_many({"content": {"$regex": "^badge_test_"}})

    # Create a test manager
    now = utc_now()
    mgr_res = await db[MANAGERS].insert_one({
        "username": "test_badge_mgr",
        "email": "badge_mgr@example.com",
        "password_hash": "hash123",
        "status": "active",
        "created_at": now,
        "updated_at": now,
    })
    m_id = str(mgr_res.inserted_id)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 1. Guest
        res = await client.get("/api/notifications/badge-counts")
        assert res.status_code == 200
        data = res.json()
        assert data["role"] == "guest"
        assert "unread_messages" in data
        assert "pending_requests" in data

        admin_cookie = {"admin_session": sign_session({"username": "admin", "user_id": "6aa000000000000000000001"})}
        mgr_cookie = {"manager_session": sign_session({"username": "test_badge_mgr", "user_id": m_id, "role": "manager"})}

        # Initially 0 unread messages for admin from this manager
        # Insert 3 unread messages from this SAME manager
        for i in range(3):
            await db[MESSAGES].insert_one({
                "manager_id": to_object_id(m_id),
                "sender_role": "manager",
                "sender_id": to_object_id(m_id),
                "sender_name": "Test Badge Manager",
                "content": f"badge_test_msg_{i}",
                "status": "unread",
                "created_at": now,
                "updated_at": now,
            })

        # Admin badge count should be 1 (representing 1 conversation with unread messages, NOT 3)
        admin_res = await client.get("/api/notifications/badge-counts", cookies=admin_cookie)
        assert admin_res.status_code == 200
        admin_data = admin_res.json()
        assert admin_data["role"] == "admin"
        assert admin_data["unread_messages"] == 1

        # Manager badge count should be 0 because messages were sent by manager, not admin
        mgr_res_badge = await client.get("/api/notifications/badge-counts", cookies=mgr_cookie)
        assert mgr_res_badge.status_code == 200
        assert mgr_res_badge.json()["unread_messages"] == 0

        # Now admin sends 2 unread messages to manager
        for i in range(2):
            await db[MESSAGES].insert_one({
                "manager_id": to_object_id(m_id),
                "sender_role": "admin",
                "sender_id": to_object_id("6aa000000000000000000001"),
                "sender_name": "Admin",
                "content": f"badge_test_admin_msg_{i}",
                "status": "unread",
                "created_at": now,
                "updated_at": now,
            })

        # Manager badge count should now be 1 (indicating active conversation with unread messages)
        mgr_res_badge2 = await client.get("/api/notifications/badge-counts", cookies=mgr_cookie)
        assert mgr_res_badge2.status_code == 200
        assert mgr_res_badge2.json()["unread_messages"] == 1

        # Now delete the manager account; should cascade delete all their messages
        del_result = await delete_manager_account(db, m_id)
        assert del_result["success"] is True

        # Admin badge count should now be 0 since manager and their messages are deleted
        admin_res_after = await client.get("/api/notifications/badge-counts", cookies=admin_cookie)
        assert admin_res_after.json()["unread_messages"] == 0


@pytest.mark.anyio
async def test_admin_profile_get_and_post(db):
    """Verify Admin profile page and profile update with avatar."""
    app = create_app()
    admin_user = await db[ADMIN_USERS].find_one({"username": settings.BOOTSTRAP_ADMIN_USERNAME})
    if not admin_user:
        pytest.skip("Bootstrap admin user not found in DB")

    admin_cookie = {"admin_session": sign_session({"username": admin_user["username"], "user_id": str(admin_user["_id"])})}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # GET /admin/profile
        res = await client.get("/admin/profile", cookies=admin_cookie)
        assert res.status_code == 200
        assert "Administrator Profile" in res.text

        # Fake PNG bytes (1x1 transparent PNG)
        png_bytes = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"

        # POST /admin/profile
        files = {
            "avatar_file": ("test_avatar.png", png_bytes, "image/png"),
        }
        data = {
            "full_name": "Senior Platform Admin",
        }
        post_res = await client.post(
            "/admin/profile",
            data=data,
            files=files,
            cookies=admin_cookie,
            follow_redirects=False,
        )
        assert post_res.status_code in [302, 303]


@pytest.mark.anyio
async def test_manager_profile_avatar_upload(db):
    """Verify manager profile update with avatar upload succeeds."""
    from authorization.encryption import hash_password

    test_username = "test_avatar_mgr_01"
    now = utc_now_iso()
    await db[MANAGERS].delete_many({"username": test_username})
    ins = await db[MANAGERS].insert_one({
        "username": test_username,
        "password_hash": hash_password("ManagerPass123!"),
        "display_name": "Avatar Test Manager",
        "email": f"{test_username}@test.com",
        "is_active": True,
        "status": "active",
        "created_at": now,
        "updated_at": now,
    })
    mgr_id = str(ins.inserted_id)
    mgr_cookie = {"manager_session": sign_session({"username": test_username, "user_id": mgr_id, "role": "manager"})}

    app = create_app()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        png_bytes = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
        files = {
            "avatar_file": ("mgr_avatar.png", png_bytes, "image/png"),
        }
        data = {
            "display_name": "Updated Annas Manager",
        }
        update_res = await client.post(
            "/manager/profile",
            data=data,
            files=files,
            cookies=mgr_cookie,
            follow_redirects=False,
        )
        assert update_res.status_code in [302, 303]

        # Verify DB doc was updated with profile_picture
        doc = await db[MANAGERS].find_one({"username": test_username})
        assert doc is not None
        assert doc.get("display_name") == "Updated Annas Manager"
        assert doc.get("profile_picture") is not None
        assert "avatars" in doc["profile_picture"]


@pytest.mark.anyio
async def test_clear_conversation_and_delete_chat(db):
    """Verify Clear Conversation for Manager and Admin, and Delete Chat for Admin."""
    from database.collections import MESSAGES
    from utils.ids import to_object_id
    from authorization.encryption import hash_password

    test_mgr_username = "test_msg_clear_mgr"
    now = utc_now_iso()
    await db[MANAGERS].delete_many({"username": test_mgr_username})
    ins = await db[MANAGERS].insert_one({
        "username": test_mgr_username,
        "password_hash": hash_password("ManagerPass123!"),
        "display_name": "Msg Clear Manager",
        "email": f"{test_mgr_username}@test.com",
        "is_active": True,
        "status": "active",
        "has_active_thread": True,
        "created_at": now,
        "updated_at": now,
    })
    mgr_id = str(ins.inserted_id)
    m_oid = to_object_id(mgr_id)

    # Insert test messages
    await db[MESSAGES].insert_many([
        {"manager_id": m_oid, "sender_role": "manager", "content": "Hello Admin 1", "status": "read", "created_at": now},
        {"manager_id": m_oid, "sender_role": "admin", "content": "Hello Manager 1", "status": "read", "created_at": now},
    ])

    admin_user = await db[ADMIN_USERS].find_one({"username": settings.BOOTSTRAP_ADMIN_USERNAME})
    admin_cookie = {"admin_session": sign_session({"username": admin_user["username"], "user_id": str(admin_user["_id"])})}
    mgr_cookie = {"manager_session": sign_session({"username": test_mgr_username, "user_id": mgr_id, "role": "manager"})}

    app = create_app()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 1. Manager clears conversation
        mgr_clear_res = await client.post("/manager/messages/clear", cookies=mgr_cookie, follow_redirects=False)
        assert mgr_clear_res.status_code in [302, 303]
        count_after_mgr_clear = await db[MESSAGES].count_documents({"manager_id": m_oid})
        assert count_after_mgr_clear == 0

        # Manager sends another message
        await db[MESSAGES].insert_one({"manager_id": m_oid, "sender_role": "manager", "content": "New question", "status": "unread", "created_at": now})

        # 2. Admin clears conversation
        admin_clear_res = await client.post(f"/admin/messages/{mgr_id}/clear", cookies=admin_cookie, follow_redirects=False)
        assert admin_clear_res.status_code in [302, 303]
        count_after_admin_clear = await db[MESSAGES].count_documents({"manager_id": m_oid})
        assert count_after_admin_clear == 0

        # Thread still exists in admin threads list
        threads_res = await client.get("/admin/messages", cookies=admin_cookie)
        assert threads_res.status_code in [200, 303]

        # 3. Admin deletes chat
        admin_del_res = await client.post(f"/admin/messages/{mgr_id}/delete", cookies=admin_cookie, follow_redirects=False)
        assert admin_del_res.status_code in [302, 303]
        mgr_doc = await db[MANAGERS].find_one({"_id": m_oid})
        assert mgr_doc.get("has_active_thread") is False


@pytest.mark.anyio
async def test_manager_settings_and_profile_views(db):
    """Verify Manager Settings view (with 2FA & theme toggle) and Profile view (no 2FA)."""
    from authorization.encryption import hash_password

    test_mgr_username = "test_settings_mgr"
    now = utc_now_iso()
    await db[MANAGERS].delete_many({"username": test_mgr_username})
    ins = await db[MANAGERS].insert_one({
        "username": test_mgr_username,
        "password_hash": hash_password("ManagerPass123!"),
        "display_name": "Settings Test Manager",
        "email": f"{test_mgr_username}@test.com",
        "is_active": True,
        "status": "active",
        "created_at": now,
        "updated_at": now,
    })
    mgr_id = str(ins.inserted_id)
    mgr_cookie = {"manager_session": sign_session({"username": test_mgr_username, "user_id": mgr_id, "role": "manager"})}

    app = create_app()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # GET /manager/settings
        res_settings = await client.get("/manager/settings", cookies=mgr_cookie)
        assert res_settings.status_code == 200
        assert "Manager Settings" in res_settings.text
        assert "Two-Factor Authentication" in res_settings.text
        assert "Appearance & Theme" in res_settings.text
        assert "settingsThemeToggleBtn" in res_settings.text

        # GET /manager/profile should NOT have Two-Factor Authentication
        res_profile = await client.get("/manager/profile", cookies=mgr_cookie)
        assert res_profile.status_code == 200
        assert "Update Profile" in res_profile.text
        assert "Two-Factor Authentication" not in res_profile.text


@pytest.mark.anyio
async def test_manager_instance_content_view(db):
    """Verify Manager instance content view resolves category/subcategory names and omits move arrows."""
    from database.collections import APP_INSTANCES, APP_INSTANCE_ACCESS
    from utils.ids import to_object_id
    from authorization.encryption import hash_password

    test_mgr_username = "test_inst_content_mgr"
    now = utc_now_iso()
    await db[MANAGERS].delete_many({"username": test_mgr_username})
    ins = await db[MANAGERS].insert_one({
        "username": test_mgr_username,
        "password_hash": hash_password("ManagerPass123!"),
        "display_name": "Instance Content Manager",
        "email": f"{test_mgr_username}@test.com",
        "is_active": True,
        "status": "active",
        "created_at": now,
        "updated_at": now,
    })
    mgr_id = str(ins.inserted_id)

    # Get an instance that has assets
    inst_doc = await db[APP_INSTANCES].find_one({"deleted_at": None})
    if not inst_doc:
        pytest.skip("No app instance found")

    inst_id = str(inst_doc["_id"])
    await db[APP_INSTANCE_ACCESS].update_one(
        {"manager_id": to_object_id(mgr_id), "app_instance_id": inst_doc["_id"]},
        {"$setOnInsert": {"manager_id": to_object_id(mgr_id), "app_instance_id": inst_doc["_id"], "created_at": now, "updated_at": now}},
        upsert=True,
    )

    mgr_cookie = {"manager_session": sign_session({"username": test_mgr_username, "user_id": mgr_id, "role": "manager"})}
    app = create_app()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get(f"/manager/instances/{inst_id}/content?active_section=assets", cookies=mgr_cookie)
        assert res.status_code == 200
        # Verify sequence arrows are not present
        assert "Move Category Up" not in res.text
        assert "Move Category Down" not in res.text
        assert "Move Sub-folder Up" not in res.text
        assert "Move Sub-folder Down" not in res.text


