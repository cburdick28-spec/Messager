import asyncio
import hashlib
import json
import os
import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from aiohttp import web


BASE_DIR = Path(__file__).parent
STATIC_DIR = BASE_DIR / "static"
DB_PATH = BASE_DIR / "chat.db"

connected_users: dict[str, web.WebSocketResponse] = {}
state_lock = asyncio.Lock()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def direct_conversation_id(user_a: str, user_b: str) -> str:
    a, b = sorted([user_a, user_b])
    return f"dm:{a}:{b}"


def group_conversation_id(group_name: str) -> str:
    return f"group:{group_name}"


def db_connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with db_connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                username TEXT PRIMARY KEY,
                salt TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS chat_groups (
                name TEXT PRIMARY KEY,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS group_members (
                group_name TEXT NOT NULL,
                username TEXT NOT NULL,
                joined_at TEXT NOT NULL,
                PRIMARY KEY (group_name, username),
                FOREIGN KEY (group_name) REFERENCES chat_groups(name),
                FOREIGN KEY (username) REFERENCES users(username)
            );

            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                sender TEXT NOT NULL,
                recipient TEXT,
                group_name TEXT,
                text TEXT NOT NULL,
                timestamp TEXT NOT NULL
            );
            """
        )


def hash_password(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        bytes.fromhex(salt),
        120_000,
    ).hex()


def create_user(username: str, password: str) -> tuple[bool, str]:
    with db_connect() as conn:
        existing = conn.execute(
            "SELECT 1 FROM users WHERE username = ?",
            (username,),
        ).fetchone()
        if existing:
            return False, "Username already exists."
        salt = secrets.token_hex(16)
        password_hash = hash_password(password, salt)
        conn.execute(
            "INSERT INTO users (username, salt, password_hash, created_at) VALUES (?, ?, ?, ?)",
            (username, salt, password_hash, now_iso()),
        )
    return True, "Account created."


def verify_user(username: str, password: str) -> bool:
    with db_connect() as conn:
        row = conn.execute(
            "SELECT salt, password_hash FROM users WHERE username = ?",
            (username,),
        ).fetchone()
    if not row:
        return False
    return hash_password(password, row["salt"]) == row["password_hash"]


def user_exists(username: str) -> bool:
    with db_connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM users WHERE username = ?",
            (username,),
        ).fetchone()
    return bool(row)


def all_users_payload() -> list[dict]:
    with db_connect() as conn:
        rows = conn.execute("SELECT username FROM users ORDER BY lower(username)").fetchall()
    online = set(connected_users.keys())
    return [{"username": row["username"], "online": row["username"] in online} for row in rows]


def groups_payload() -> list[dict]:
    with db_connect() as conn:
        groups = conn.execute("SELECT name FROM chat_groups ORDER BY lower(name)").fetchall()
        result = []
        for group in groups:
            members = conn.execute(
                "SELECT username FROM group_members WHERE group_name = ? ORDER BY lower(username)",
                (group["name"],),
            ).fetchall()
            result.append({"name": group["name"], "members": [m["username"] for m in members]})
    return result


def create_group(group_name: str, username: str) -> tuple[bool, str]:
    with db_connect() as conn:
        existing = conn.execute(
            "SELECT 1 FROM chat_groups WHERE name = ?",
            (group_name,),
        ).fetchone()
        if existing:
            return False, "Group already exists."
        conn.execute(
            "INSERT INTO chat_groups (name, created_at) VALUES (?, ?)",
            (group_name, now_iso()),
        )
        conn.execute(
            "INSERT INTO group_members (group_name, username, joined_at) VALUES (?, ?, ?)",
            (group_name, username, now_iso()),
        )
    return True, f"Created group '{group_name}'."


def join_group(group_name: str, username: str) -> tuple[bool, str]:
    with db_connect() as conn:
        group = conn.execute(
            "SELECT 1 FROM chat_groups WHERE name = ?",
            (group_name,),
        ).fetchone()
        if not group:
            return False, "Group does not exist."
        existing = conn.execute(
            "SELECT 1 FROM group_members WHERE group_name = ? AND username = ?",
            (group_name, username),
        ).fetchone()
        if not existing:
            conn.execute(
                "INSERT INTO group_members (group_name, username, joined_at) VALUES (?, ?, ?)",
                (group_name, username, now_iso()),
            )
    return True, "Joined group."


def group_has_member(group_name: str, username: str) -> bool:
    with db_connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM group_members WHERE group_name = ? AND username = ?",
            (group_name, username),
        ).fetchone()
    return bool(row)


def group_members(group_name: str) -> list[str]:
    with db_connect() as conn:
        rows = conn.execute(
            "SELECT username FROM group_members WHERE group_name = ?",
            (group_name,),
        ).fetchall()
    return [row["username"] for row in rows]


def save_message(message: dict) -> None:
    with db_connect() as conn:
        conn.execute(
            """
            INSERT INTO messages (conversation_id, kind, sender, recipient, group_name, text, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                message["conversationId"],
                message["kind"],
                message["from"],
                message.get("to"),
                message.get("group"),
                message["text"],
                message["timestamp"],
            ),
        )


def history_for(conversation_id: str) -> list[dict]:
    with db_connect() as conn:
        rows = conn.execute(
            """
            SELECT conversation_id, kind, sender, recipient, group_name, text, timestamp
            FROM messages
            WHERE conversation_id = ?
            ORDER BY id ASC
            LIMIT 500
            """,
            (conversation_id,),
        ).fetchall()

    return [
        {
            "conversationId": row["conversation_id"],
            "kind": row["kind"],
            "from": row["sender"],
            "to": row["recipient"],
            "group": row["group_name"],
            "text": row["text"],
            "timestamp": row["timestamp"],
        }
        for row in rows
    ]


async def safe_send(ws: web.WebSocketResponse, payload: dict) -> None:
    if not ws.closed:
        await ws.send_json(payload)


async def broadcast(payload: dict) -> None:
    for ws in list(connected_users.values()):
        await safe_send(ws, payload)


async def broadcast_users() -> None:
    await broadcast({"type": "users", "users": all_users_payload()})


async def broadcast_groups() -> None:
    await broadcast({"type": "groups", "groups": groups_payload()})


async def index_handler(_: web.Request) -> web.FileResponse:
    return web.FileResponse(STATIC_DIR / "index.html")


async def ws_handler(request: web.Request) -> web.WebSocketResponse:
    ws = web.WebSocketResponse(heartbeat=30)
    await ws.prepare(request)
    username = None

    try:
        async for msg in ws:
            if msg.type != web.WSMsgType.TEXT:
                continue

            try:
                payload = json.loads(msg.data)
            except json.JSONDecodeError:
                await safe_send(ws, {"type": "error", "message": "Invalid JSON payload."})
                continue

            msg_type = payload.get("type")

            if msg_type in {"register", "login"}:
                requested = str(payload.get("username", "")).strip()
                password = str(payload.get("password", "")).strip()
                if not requested or not password:
                    await safe_send(ws, {"type": "error", "message": "Username and password are required."})
                    continue
                if len(password) < 6:
                    await safe_send(ws, {"type": "error", "message": "Password must be at least 6 characters."})
                    continue

                async with state_lock:
                    if requested in connected_users:
                        await safe_send(ws, {"type": "error", "message": "That user is already online."})
                        continue

                    if msg_type == "register":
                        ok, text = create_user(requested, password)
                        if not ok:
                            await safe_send(ws, {"type": "error", "message": text})
                            continue
                    else:
                        if not verify_user(requested, password):
                            await safe_send(ws, {"type": "error", "message": "Invalid username or password."})
                            continue

                    username = requested
                    connected_users[username] = ws

                await safe_send(
                    ws,
                    {
                        "type": "init",
                        "username": username,
                        "users": all_users_payload(),
                        "groups": groups_payload(),
                    },
                )
                await broadcast_users()
                await broadcast_groups()
                continue

            if not username:
                await safe_send(ws, {"type": "error", "message": "Log in first."})
                continue

            if msg_type == "create_group":
                group_name = str(payload.get("name", "")).strip()
                if not group_name:
                    await safe_send(ws, {"type": "error", "message": "Group name is required."})
                    continue
                ok, text = create_group(group_name, username)
                if not ok:
                    await safe_send(ws, {"type": "error", "message": text})
                    continue
                await broadcast_groups()
                await safe_send(ws, {"type": "info", "message": text})
                continue

            if msg_type == "join_group":
                group_name = str(payload.get("name", "")).strip()
                ok, text = join_group(group_name, username)
                if not ok:
                    await safe_send(ws, {"type": "error", "message": text})
                    continue
                convo_id = group_conversation_id(group_name)
                await safe_send(
                    ws,
                    {"type": "history", "conversationId": convo_id, "messages": history_for(convo_id)},
                )
                await broadcast_groups()
                continue

            if msg_type == "send_dm":
                to_user = str(payload.get("to", "")).strip()
                text = str(payload.get("text", "")).strip()
                if not to_user or not text:
                    await safe_send(ws, {"type": "error", "message": "Recipient and message are required."})
                    continue
                if not user_exists(to_user):
                    await safe_send(ws, {"type": "error", "message": "User does not exist."})
                    continue

                message = {
                    "conversationId": direct_conversation_id(username, to_user),
                    "kind": "dm",
                    "from": username,
                    "to": to_user,
                    "text": text,
                    "timestamp": now_iso(),
                }
                save_message(message)

                await safe_send(ws, {"type": "message", "message": message})
                recipient_ws = connected_users.get(to_user)
                if recipient_ws:
                    await safe_send(recipient_ws, {"type": "message", "message": message})
                continue

            if msg_type == "send_group":
                group_name = str(payload.get("group", "")).strip()
                text = str(payload.get("text", "")).strip()
                if not group_name or not text:
                    await safe_send(ws, {"type": "error", "message": "Group and message are required."})
                    continue
                if not group_has_member(group_name, username):
                    await safe_send(ws, {"type": "error", "message": "Join the group before messaging."})
                    continue

                message = {
                    "conversationId": group_conversation_id(group_name),
                    "kind": "group",
                    "group": group_name,
                    "from": username,
                    "text": text,
                    "timestamp": now_iso(),
                }
                save_message(message)

                for member in group_members(group_name):
                    member_ws = connected_users.get(member)
                    if member_ws:
                        await safe_send(member_ws, {"type": "message", "message": message})
                continue

            if msg_type == "fetch_history":
                convo_id = str(payload.get("conversationId", "")).strip()
                await safe_send(
                    ws,
                    {"type": "history", "conversationId": convo_id, "messages": history_for(convo_id)},
                )
                continue

            await safe_send(ws, {"type": "error", "message": "Unknown action."})
    finally:
        if username:
            async with state_lock:
                connected_users.pop(username, None)
            await broadcast_users()

    return ws


def create_app() -> web.Application:
    init_db()
    app = web.Application()
    app.add_routes([web.get("/", index_handler), web.get("/ws", ws_handler)])
    app.router.add_static("/static/", str(STATIC_DIR))
    return app


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8080"))
    web.run_app(create_app(), host="0.0.0.0", port=port)
