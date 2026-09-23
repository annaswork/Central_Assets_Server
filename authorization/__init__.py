"""Authorization package public exports."""

from authorization.admin_session import (
    authenticate_admin_user,
    clear_admin_session_cookie,
    get_current_admin_session,
    set_admin_session_cookie,
)
from authorization.api_key import (
    activate_api_key,
    delete_api_key,
    issue_api_key,
    revoke_api_key,
    rotate_api_key,
    verify_api_key,
)
from authorization.encryption import (
    generate_key_pair,
    hash_password,
    hash_secret,
    read_session,
    sign_session,
    verify_password,
    verify_secret,
)
from authorization.instance_guard import get_instance_filter
from authorization.rate_limiter import check_rate_limit
from authorization.scopes import require_scope

__all__ = [
    "activate_api_key",
    "authenticate_admin_user",
    "check_rate_limit",
    "clear_admin_session_cookie",
    "delete_api_key",
    "generate_key_pair",
    "get_current_admin_session",
    "get_instance_filter",
    "hash_password",
    "hash_secret",
    "issue_api_key",
    "read_session",
    "require_scope",
    "revoke_api_key",
    "rotate_api_key",
    "set_admin_session_cookie",
    "sign_session",
    "verify_api_key",
    "verify_password",
    "verify_secret",
]
