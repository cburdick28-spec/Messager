import asyncio
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from aiohttp import web


BASE_DIR = Path(__file__).parent
STATIC_DIR = BASE_DIR / "static"

connected_users: dict[str, web.WebSocketResponse] = {}
groups: dict[str, set[str]] = defaultdict(set)
history: dict[str, list[dict]] = defaultdict(list)
state_lock = asyncio.Lock()


def direct_conversation_id(user_a: str, user_b: str) -> str:
    a, b = sorted([user_a, user_b])
    return f"dm:{a}:{b}"


def group_conversation_id(group_name: str) -> str:
    return f"group:{group_name}"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def group_payload() -> list[dict]:
    return [
        {"name": name, "members": sorted(members)}
        for name, members in sorted(groups.items(), key=lambda item: item[0].lower())
    ]


async def safe_send(ws: web.WebSocketResponse, payload: dict) -> None:
    if not ws.closed:
        await ws.send_json(payload)


async def broadcast(payload: dict) -> None:
    for ws in list(connected_users.values()):
        await safe_send(ws, payload)


async def broadcast_users() -> None:
    await broadcast({"type": "users", "users": sorted(connected_users.keys())})


async def broadcast_groups() -> None:
    await broadcast({"type": "groups", "groups": group_payload()})


def save_message(conversation_id: str, message: dict) -> None:
    history[conversation_id].append(message)
    if len(history[conversation_id]) > 300:
        history[conversation_id] = history[conversation_id][-300:]


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

            if msg_type == "register":
                requested = str(payload.get("username", "")).strip()
                if not requested:
                    await safe_send(ws, {"type": "error", "message": "Username is required."})
                    continue

                async with state_lock:
                    if requested in connected_users:
                        await safe_send(ws, {"type": "error", "message": "Username already in use."})
                        continue
                    username = requested
                    connected_users[username] = ws

                await safe_send(
                    ws,
                    {
                        "type": "init",
                        "username": username,
                        "users": sorted(connected_users.keys()),
                        "groups": group_payload(),
                    },
                )
                await broadcast_users()
                await broadcast_groups()
                continue

            if not username:
                await safe_send(ws, {"type": "error", "message": "Register first."})
                continue

            if msg_type == "create_group":
                group_name = str(payload.get("name", "")).strip()
                if not group_name:
                    await safe_send(ws, {"type": "error", "message": "Group name is required."})
                    continue

                async with state_lock:
                    if group_name in groups:
                        await safe_send(ws, {"type": "error", "message": "Group already exists."})
                        continue
                    groups[group_name].add(username)

                await broadcast_groups()
                await safe_send(ws, {"type": "info", "message": f"Created group '{group_name}'."})
                continue

            if msg_type == "join_group":
                group_name = str(payload.get("name", "")).strip()
                if group_name not in groups:
                    await safe_send(ws, {"type": "error", "message": "Group does not exist."})
                    continue

                async with state_lock:
                    groups[group_name].add(username)

                convo_id = group_conversation_id(group_name)
                await safe_send(
                    ws,
                    {"type": "history", "conversationId": convo_id, "messages": history.get(convo_id, [])},
                )
                await broadcast_groups()
                continue

            if msg_type == "send_dm":
                to_user = str(payload.get("to", "")).strip()
                text = str(payload.get("text", "")).strip()
                if not to_user or not text:
                    await safe_send(ws, {"type": "error", "message": "Recipient and message are required."})
                    continue

                convo_id = direct_conversation_id(username, to_user)
                chat_message = {
                    "conversationId": convo_id,
                    "kind": "dm",
                    "from": username,
                    "to": to_user,
                    "text": text,
                    "timestamp": now_iso(),
                }
                save_message(convo_id, chat_message)

                await safe_send(ws, {"type": "message", "message": chat_message})
                if to_user in connected_users:
                    await safe_send(connected_users[to_user], {"type": "message", "message": chat_message})
                continue

            if msg_type == "send_group":
                group_name = str(payload.get("group", "")).strip()
                text = str(payload.get("text", "")).strip()
                if not group_name or not text:
                    await safe_send(ws, {"type": "error", "message": "Group and message are required."})
                    continue
                if group_name not in groups or username not in groups[group_name]:
                    await safe_send(ws, {"type": "error", "message": "Join the group before messaging."})
                    continue

                convo_id = group_conversation_id(group_name)
                chat_message = {
                    "conversationId": convo_id,
                    "kind": "group",
                    "group": group_name,
                    "from": username,
                    "text": text,
                    "timestamp": now_iso(),
                }
                save_message(convo_id, chat_message)

                for member in groups[group_name]:
                    member_ws = connected_users.get(member)
                    if member_ws:
                        await safe_send(member_ws, {"type": "message", "message": chat_message})
                continue

            if msg_type == "fetch_history":
                convo_id = str(payload.get("conversationId", "")).strip()
                await safe_send(
                    ws,
                    {"type": "history", "conversationId": convo_id, "messages": history.get(convo_id, [])},
                )
                continue

            await safe_send(ws, {"type": "error", "message": "Unknown action."})
    finally:
        if username:
            async with state_lock:
                connected_users.pop(username, None)
                empty_groups = []
                for group_name, members in groups.items():
                    members.discard(username)
                    if not members:
                        empty_groups.append(group_name)
                for group_name in empty_groups:
                    groups.pop(group_name, None)
            await broadcast_users()
            await broadcast_groups()

    return ws


def create_app() -> web.Application:
    app = web.Application()
    app.add_routes([web.get("/", index_handler), web.get("/ws", ws_handler)])
    app.router.add_static("/static/", str(STATIC_DIR))
    return app


if __name__ == "__main__":
    web.run_app(create_app(), host="0.0.0.0", port=8080)
