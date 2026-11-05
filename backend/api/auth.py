"""
Telegram WebApp Authentication Guard.
Cryptographically verifies Telegram initData via HMAC-SHA256 signature
and validates auth_date freshness (<= 24 hours).
"""

import hashlib
import hmac
import json
import logging
import os
import time
import urllib.parse
from typing import Any, Dict, Optional

from fastapi import Header, HTTPException

logger = logging.getLogger(__name__)


def verify_telegram_init_data(
    init_data_raw: str,
    bot_token: Optional[str] = None,
    max_age_seconds: int = 86400,
) -> Optional[Dict[str, Any]]:
    """
    Verify the cryptographic signature of Telegram WebApp initData.
    Returns parsed user dict upon success, or None if invalid or expired.
    """
    token = bot_token or os.getenv("TELEGRAM_BOT_TOKEN")
    if not token or not init_data_raw or not init_data_raw.strip():
        return None

    try:
        # Parse query string parameters preserving values
        parsed_qsl = urllib.parse.parse_qsl(init_data_raw.strip(), keep_blank_values=True)
        params_dict = dict(parsed_qsl)
    except Exception as exc:
        logger.warning("Failed to parse Telegram initData: %s", exc)
        return None

    hash_val = params_dict.get("hash")
    if not hash_val:
        return None

    # Check auth_date expiration (<= 24 hours)
    try:
        auth_date = int(params_dict.get("auth_date", 0))
    except (ValueError, TypeError):
        return None

    current_time = int(time.time())
    if current_time - auth_date > max_age_seconds:
        logger.info("Telegram initData expired (auth_date: %d, now: %d)", auth_date, current_time)
        return None

    # Build data_check_string sorted by key (excluding 'hash')
    sorted_items = sorted((k, v) for k, v in parsed_qsl if k != "hash")
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted_items)

    # Calculate HMAC-SHA256 signature
    secret_key = hmac.new(b"WebAppData", token.encode("utf-8"), hashlib.sha256).digest()
    calculated_hash = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(calculated_hash, hash_val):
        logger.warning("Telegram initData HMAC signature mismatch")
        return None

    # Extract user payload
    user_raw = params_dict.get("user")
    if not user_raw:
        return None

    try:
        user_data = json.loads(user_raw)
        if not isinstance(user_data, dict) or "id" not in user_data:
            return None
        return user_data
    except Exception as exc:
        logger.warning("Failed to parse user JSON in Telegram initData: %s", exc)
        return None


def get_current_telegram_user(
    authorization: Optional[str] = Header(None),
    x_telegram_init_data: Optional[str] = Header(None),
) -> Optional[Dict[str, Any]]:
    """
    Dependency to optionally retrieve verified Telegram user data.
    Extracts initData from 'Authorization: Telegram <initData>' or 'X-Telegram-Init-Data'.
    Returns verified user dictionary or None.
    """
    raw_data: Optional[str] = None
    if authorization and authorization.startswith("Telegram "):
        raw_data = authorization[len("Telegram "):].strip()
    elif x_telegram_init_data:
        raw_data = x_telegram_init_data.strip()

    if not raw_data:
        return None

    return verify_telegram_init_data(raw_data)


def require_telegram_user(
    authorization: Optional[str] = Header(None),
    x_telegram_init_data: Optional[str] = Header(None),
) -> Dict[str, Any]:
    """
    Dependency requiring a valid, verified Telegram user.
    Raises HTTP 401 Unauthorized if missing, invalid, or expired.
    """
    user = get_current_telegram_user(authorization, x_telegram_init_data)
    if not user:
        raise HTTPException(
            status_code=401,
            detail="Valid Telegram WebApp authorization required (HMAC signature invalid or expired)",
        )
    return user
