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
import base64
from fastapi import FastAPI, HTTPException, Request, Header, Depends, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi import WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel
from datetime import datetime, timedelta
import jwt  # PyJWT

# --- JWT config
SECRET_KEY = "n4X_b_Bpj0nEolIANE9U9QYrfaYFngIEh-8NKO4XOIBtwdLHu8cDyHVH4NNMWiI9bUVfTq3l4TBYqX_O7Q3biQ"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

def authenticate_user(username: str, password: str) -> bool:
    # TODO: replace with real lookup + hashing
    return username == "alice" and password == "s3cr3t"

def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=15))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


ROOMS: dict[str, dict] = {}  # existing in‐memory structure
app = FastAPI()

CLEANUP_INTERVAL = 5  # seconds
MAX_HISTORY = 50  # Max messages to store per room

class Message(BaseModel):
    type: str
    data: str
    filename: str = None
    size: int = None
    client_id: str = None
    nickname: str = None
    current_size: int = None  # Added for file-chunk progress

@app.post("/token")
async def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends()):
    if not authenticate_user(form_data.username, form_data.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )
    access_token = create_access_token(
        {"sub": form_data.username},
        expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
    )
    return {"access_token": access_token, "token_type": "bearer"}

async def get_current_user(token: str = Depends(oauth2_scheme)):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise jwt.PyJWTError()
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
        )
    return username

@app.post("/create")
async def create_room():
    rid = uuid.uuid4().hex[:6]
    ROOMS[rid] = {"clients": [], "messages": [], "file_progress": {}}
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
    msg_dict = message.dict()
    # Track file transfer progress
    if message.type == "file":
        ROOMS[room_id]["file_progress"][message.filename] = {
            "current_size": 0,
            "sender_id": message.client_id  # Track the sender's client_id
        }
    elif message.type == "file-chunk":
        # Calculate the raw chunk size (after decoding base64)
        chunk_size = len(base64.b64decode(message.data))
        if message.filename in ROOMS[room_id]["file_progress"]:
            ROOMS[room_id]["file_progress"][message.filename]["current_size"] += chunk_size
            msg_dict["current_size"] = ROOMS[room_id]["file_progress"][message.filename]["current_size"]
    elif message.type in ("file-end", "file-cancel"):
        ROOMS[room_id]["file_progress"].pop(message.filename, None)

    # Store message (except typing events)
    if message.type != "typing":
        ROOMS[room_id]["messages"].append(msg_dict)
        ROOMS[room_id]["messages"] = ROOMS[room_id]["messages"][-MAX_HISTORY:]  # Keep last 50
    for q in list(ROOMS[room_id]["clients"]):
        await q.put(msg_dict)
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
async def stream(room_id: str, client_id: str):
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
                # skip echoing back to the sender
                if msg.get("client_id") == client_id:
                    continue
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

@app.get("/rooms/{room_id}/get_file_progress")
async def get_file_progress(room_id: str, client_id: str):
    if room_id not in ROOMS:
        raise HTTPException(status_code=404, detail="Room not found")
    ongoing_transfers = {}
    for filename, progress in ROOMS[room_id]["file_progress"].items():
        if progress["sender_id"] == client_id:
            ongoing_transfers[filename] = progress["current_size"]
    return {"ongoing_transfers": ongoing_transfers}

@app.post("/upload")
async def upload_file(request: Request, x_filename: str = Header(...)):
    os.makedirs("uploads", exist_ok=True)
    file_path = os.path.join("uploads", x_filename)

    try:
        with open(file_path, "wb") as out_file:
            async for chunk in request.stream():
                out_file.write(chunk)
        print(f"[Server] Uploaded file: {x_filename}")
        return JSONResponse({"status": "ok", "filename": x_filename})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

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

# ----------------------------------------------------------------
# WebSocket endpoint for streaming raw file bytes
@app.websocket("/ws/{room_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    room_id: str,
    token: str = Depends(get_current_user)
):
    await websocket.accept()
    room = ROOMS.setdefault(room_id, {"clients": [], "messages": [], "file_progress": {}})
    room["clients"].append(websocket)
    try:
        # 2) Notify everyone: file start
        await broadcast(room_id, {"event": "file-start"}, data=b"")
        # 3) Stream raw binary frames immediately
        async for chunk in websocket.iter_bytes():
            # chunk is bytes
            await broadcast(room_id, {"event": "file-chunk"}, data=chunk)
        # 4) When client cleanly closes → end‐of‐file
        await broadcast(room_id, {"event": "file-end"}, data=b"")
    except WebSocketDisconnect:
        room["clients"].remove(websocket)


async def broadcast(room_id: str, meta: dict, data: bytes):
    """
    Send a JSON envelope to all WebSocket clients in room_id.
    We transport `data` as Latin-1–encoded so it survives JSON.
    """
    text = data.decode("latin1") if data else ""
    payload = {"meta": meta, "data": text}
    for ws in list(ROOMS[room_id]["clients"]):
        try:
            await ws.send_json(payload)
        except:
            ROOMS[room_id]["clients"].remove(ws)
