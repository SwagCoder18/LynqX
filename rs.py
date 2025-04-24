# relay_server.py
#!/usr/bin/env python3
"""
P2P Chat Relay using HTTP REST + Server-Sent Events (SSE)

USAGE:
  pip install fastapi uvicorn
  PORT=8000 uvicorn relay_server:app --host 0.0.0.0 --port $PORT
"""
import os
import uuid
import json
import asyncio
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

app = FastAPI()
ROOMS = {}

class Message(BaseModel):
    type: str
    data: str
    filename: str = None
    size: int = None

@app.post("/create")
async def create_room():
    rid = uuid.uuid4().hex[:6]
    ROOMS[rid] = []
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
    for q in list(ROOMS[room_id]):
        await q.put(message.dict())
    return {"status": "ok"}

@app.get("/rooms/{room_id}/stream")
async def stream(room_id: str):
    if room_id not in ROOMS:
        raise HTTPException(status_code=404, detail="Room not found")
    q = asyncio.Queue()
    ROOMS[room_id].append(q)

    async def event_generator():
        try:
            while True:
                msg = await q.get()
                payload = json.dumps(msg)
                yield f"data: {payload}\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            ROOMS[room_id].remove(q)

    return StreamingResponse(event_generator(), media_type="text/event-stream")

@app.get("/health")
async def health():
    return {"status": "ok"}
