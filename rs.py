#!/usr/bin/env python3
"""
P2P Chat Relay using HTTP REST + Server-Sent Events (SSE)

USAGE:
  pip install fastapi uvicorn
  uvicorn rs:app --host 0.0.0.0 --port 8000
"""
import os
import uuid
import json
import asyncio
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

app = FastAPI()
ROOMS = {}  # {room_id: {"clients": [queue], "messages": [message]}}
CLEANUP_INTERVAL = 5  # seconds
MAX_HISTORY = 50  # Max messages to store per room

class Message(BaseModel):
    type: str
    data: str
    filename: str = None
    size: int = None
    client_id: str = None
    nickname: str = None

@app.post("/create")
async def create_room():
    rid = uuid.uuid4().hex[:6]
    ROOMS[rid] = {"clients": [], "messages": []}
    print(f"[Server] Created room: {rid}")
    return {"room_id": rid}

@app.get("/rooms/{room_id}")
async def room_exists(room_id: str):
    if room_id not in ROOMS:
        raise HTTPException(status_code=404, detail="Room not found")
    return {"status": "ok", "room_id": room_id}

@app.post("/rooms/{room_id}/send")
async def send_message(room_id: str, message: Message):
    if room_id not in ROOMS:
        raise HTTPException(status_code=404, detail="Room not found")
    # Store message (except typing events)
    if message.type != "typing":
        ROOMS[room_id]["messages"].append(message.dict())
        ROOMS[room_id]["messages"] = ROOMS[room_id]["messages"][-MAX_HISTORY:]  # Keep last 50
    for q in list(ROOMS[room_id]["clients"]):
        await q.put(message.dict())
    return {"status": "ok"}

@app.post("/rooms/{room_id}/typing")
async def send_typing(room_id: str, message: Message):
    if room_id not in ROOMS:
        raise HTTPException(status_code=404, detail="Room not found")
    message.type = "typing"
    for q in list(ROOMS[room_id]["clients"]):
        await q.put(message.dict())
    return {"status": "ok"}

@app.get("/rooms/{room_id}/stream")
async def stream(room_id: str):
    if room_id not in ROOMS:
        raise HTTPException(status_code=404, detail="Room not found")
    q = asyncio.Queue()
    ROOMS[room_id]["clients"].append(q)

    # Broadcast updated client count to all clients (including the new one)
    client_count = len(ROOMS[room_id]["clients"])
    client_count_msg = {"type": "client_count", "count": client_count}
    for queue in list(ROOMS[room_id]["clients"]):
        await queue.put(client_count_msg)

    async def event_generator():
        try:
            # Send message history
            for msg in ROOMS[room_id]["messages"]:
                payload = json.dumps(msg)
                yield f"data: {payload}\n\n"
                await asyncio.sleep(0.01)  # Prevent overwhelming client
            # Stream new messages
            while True:
                msg = await q.get()
                payload = json.dumps(msg)
                yield f"data: {payload}\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            ROOMS[room_id]["clients"].remove(q)
            # Broadcast updated client count after a client disconnects
            client_count = len(ROOMS[room_id]["clients"])
            client_count_msg = {"type": "client_count", "count": client_count}
            for queue in list(ROOMS[room_id]["clients"]):
                await queue.put(client_count_msg)

    return StreamingResponse(event_generator(), media_type="text/event-stream")

@app.get("/health")
async def health():
    return {"status": "ok"}

# Periodic cleanup task to remove empty rooms
async def cleanup_rooms():
    while True:
        await asyncio.sleep(CLEANUP_INTERVAL)
        to_delete = [room for room, data in ROOMS.items() if not data["clients"]]
        for room in to_delete:
            print(f"[Cleanup] Removing empty room: {room}")
            del ROOMS[room]

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(cleanup_rooms())
