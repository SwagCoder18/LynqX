# relay_server.py
#!/usr/bin/env python3
"""
P2P Chat Relay using HTTP REST + Server-Sent Events (SSE) with system notifications and auto-cleanup

USAGE:
  pip install fastapi uvicorn
  uvicorn relay_server:app --host 0.0.0.0 --port 8000
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
CLEANUP_INTERVAL = 60  # seconds

class Message(BaseModel):
    type: str            # 'message', 'file', 'file-chunk', 'file-end', or 'system'
    data: str            # text or base64 chunk
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
    # broadcast user messages/file events
    for q in list(ROOMS[room_id]):
        await q.put(message.dict())
    return {"status": "ok"}

@app.get("/rooms/{room_id}/stream")
async def stream(room_id: str):
    if room_id not in ROOMS:
        raise HTTPException(status_code=404, detail="Room not found")
    q = asyncio.Queue()
    ROOMS[room_id].append(q)
    # notify join events
    # to joining client:
    await q.put({'type':'system', 'data':f"You joined room {room_id}. " 
                          f"Peers online: {len(ROOMS[room_id])-1}"})
    # to others:
    for peer in ROOMS[room_id]:
        if peer is not q:
            await peer.put({'type':'system', 'data':
                             f"A peer has joined. Total peers: {len(ROOMS[room_id])}"})

    async def event_generator():
        try:
            while True:
                msg = await q.get()
                yield f"data: {json.dumps(msg)}\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            # remove client and notify leave
            ROOMS[room_id].remove(q)
            for peer in ROOMS.get(room_id, []):
                await peer.put({'type':'system', 'data':
                                 f"A peer has left. Total peers: {len(ROOMS[room_id])}"})

    return StreamingResponse(event_generator(), media_type="text/event-stream")

@app.get("/health")
async def health():
    return {"status": "ok"}

# Periodic cleanup task to remove empty rooms
def cleanup_rooms_task():
    async def _cleanup():
        while True:
            await asyncio.sleep(CLEANUP_INTERVAL)
            to_delete = [room for room, clients in ROOMS.items() if not clients]
            for room in to_delete:
                print(f"[Cleanup] Removing empty room: {room}")
                del ROOMS[room]
    return _cleanup()

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(cleanup_rooms_task())
