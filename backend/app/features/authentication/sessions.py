"""Durable sessions and login throttling using the existing operations store."""
import hashlib
import hmac
import time

from fastapi import HTTPException
from sqlalchemy import delete, select, text

from ...config import settings
from ...models.operations import OperationsSetting
from ..operations import store


def credential_stamp(user):
    material = f"{user.id}:{user.username}:{user.hashed_password}"
    return hmac.new(settings.SECRET_KEY.encode(), material.encode(), hashlib.sha256).hexdigest()


def create(jti, user, expires_at, *, client=""):
    now = int(time.time())
    store.set_setting("auth_session:" + jti, {
        "user_id": user.id, "credential_stamp": credential_stamp(user),
        "expires_at": int(expires_at), "created_at": now, "last_seen": now,
        "client": str(client)[:120],
    })


def valid(jti, user, *, touch=True):
    now = int(time.time())
    with store._sessions.begin() as db:
        row = db.scalar(select(OperationsSetting).where(
            OperationsSetting.key == "auth_session:" + jti).with_for_update())
        record = row.value if row else None
        if not isinstance(record, dict) or record.get("expires_at", 0) <= now:
            return False
        if now - record.get("last_seen", now) > settings.AUTH_IDLE_TIMEOUT_SECONDS:
            return False
        if record.get("user_id") != user.id or not hmac.compare_digest(
            str(record.get("credential_stamp", "")), credential_stamp(user)
        ):
            return False
        if touch and now - record.get("last_seen", 0) >= 60:
            row.value = {**record, "last_seen": now}
        return True


def revoke(jti):
    with store._sessions.begin() as db:
        db.execute(delete(OperationsSetting).where(OperationsSetting.key == "auth_session:" + jti))


def list_for(user, current_jti):
    now = int(time.time())
    with store._sessions() as db:
        rows = db.scalars(select(OperationsSetting).where(
            OperationsSetting.key.startswith("auth_session:")
        )).all()
    result = []
    for row in rows:
        value = row.value
        if not isinstance(value, dict) or value.get("user_id") != user.id:
            continue
        if value.get("expires_at", 0) <= now or now - value.get("last_seen", now) > settings.AUTH_IDLE_TIMEOUT_SECONDS:
            continue
        if not hmac.compare_digest(str(value.get("credential_stamp", "")), credential_stamp(user)):
            continue
        result.append({"id": row.key.removeprefix("auth_session:"),
                       "created_at": value.get("created_at"), "last_seen": value.get("last_seen"),
                       "expires_at": value["expires_at"], "client": value.get("client", ""),
                       "current": row.key == "auth_session:" + current_jti})
    return sorted(result, key=lambda item: item["created_at"] or 0, reverse=True)


def revoke_for(user, target_jti, *, current_jti=None):
    if target_jti == current_jti:
        return False
    with store._sessions.begin() as db:
        row = db.get(OperationsSetting, "auth_session:" + target_jti)
        if not row or not isinstance(row.value, dict) or row.value.get("user_id") != user.id:
            return False
        db.delete(row)
    return True


def create_ws_ticket(jti, expires_at):
    store.set_setting("auth_ws_ticket:" + jti, {"expires_at": int(expires_at)})


def consume_ws_ticket(jti):
    with store._sessions.begin() as db:
        result = db.execute(delete(OperationsSetting).where(
            OperationsSetting.key == "auth_ws_ticket:" + jti,
            OperationsSetting.value["expires_at"].as_integer() > int(time.time()),
        ).returning(OperationsSetting.key))
        return result.scalar_one_or_none() is not None


def prune(now=None):
    with store._sessions.begin() as db:
        return db.execute(delete(OperationsSetting).where(
            OperationsSetting.key.startswith("auth_"),
            OperationsSetting.value["expires_at"].as_integer() <= int(now or time.time()),
        )).rowcount


def check_login(ip, username):
    """Count attempts before bcrypt, across workers, including loopback clients.

    PostgreSQL advisory transaction locks also serialize first-row insertion.
    A fixed ten-minute window allows recovery without permanent account locks.
    """
    now = int(time.time())
    window = now // 600
    retry_after = 600 - now % 600
    with store._sessions.begin() as db:
        blocked = False
        for scope, identity, limit in (("ip", ip, 30), ("account", username, 10)):
            digest = hmac.new(settings.SECRET_KEY.encode(), identity.encode(), hashlib.sha256).hexdigest()
            key = f"auth_throttle:{scope}:{digest}:{window}"
            if db.bind.dialect.name == "postgresql":
                lock_id = int.from_bytes(hashlib.sha256(key.encode()).digest()[:8], "big", signed=True)
                db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_id})
            row = db.get(OperationsSetting, key)
            count = (row.value.get("count", 0) if row else 0) + 1
            blocked = blocked or count > limit
            value = {"count": count, "expires_at": (window + 1) * 600}
            if row is None:
                db.add(OperationsSetting(key=key, value=value))
            else:
                row.value = value
    if blocked:
        raise HTTPException(429, "Too many login attempts. Try again later.",
                            headers={"Retry-After": str(retry_after)})
