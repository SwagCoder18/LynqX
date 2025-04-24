# relay_server.py
#!/usr/bin/env python3
"""
WebSocket-based P2P Relay & Health Server

Usage:
  # Run on Render or any HTTP-capable host (uses $PORT or defaults to 12345):
  python3 relay_server.py

Clients connect via WebSocket to ws://<host>:<port>/ws
Health check on HTTP GET / or /health returns 200 OK.
"""
import asyncio
import json
import os
import random
from websockets import serve, WebSocketServerProtocol
import websockets

# room_id -> set of WebSocketServerProtocol
ROOMS = {}

async def handler(ws: WebSocketServerProtocol, path: str):
    # Initial JSON handshake
    try:
        init = await ws.recv()
        req = json.loads(init)
        action = req.get('action')
        room_id = req.get('room_id')
    except Exception:
        await ws.close()
        return

    if action == 'create':
        room_id = ''.join(random.choices('0123456789', k=6))
        ROOMS[room_id] = {ws}
        await ws.send(json.dumps({'status':'ok','room_id':room_id}))
        print(f"[+] Room {room_id} created")
    elif action == 'join':
        if room_id not in ROOMS:
            await ws.send(json.dumps({'status':'error','error':'Room not found'}))
            await ws.close()
            return
        ROOMS[room_id].add(ws)
        await ws.send(json.dumps({'status':'ok','room_id':room_id}))
        print(f"[+] Peer joined room {room_id}")
    else:
        await ws.close()
        return

    try:
        async for message in ws:
            # Broadcast JSON/text messages to other peers
            for peer in list(ROOMS.get(room_id, [])):
                if peer is not ws:
                    await peer.send(message)
    except websockets.ConnectionClosed:
        pass
    finally:
        participants = ROOMS.get(room_id, set())
        participants.discard(ws)
        if not participants:
            ROOMS.pop(room_id, None)
        print(f"[-] Peer left room {room_id}")

async def process_request(path, request_headers):
    # HTTP health check before WebSocket handshake
    if path in ('/', '/health'):
        return (200, [('Content-Type', 'text/plain; charset=utf-8')], b'OK')
    # None = continue with WebSocket handshake for /ws
    return None

async def main():
    port = int(os.getenv('PORT', '12345'))
    async with serve(handler, '0.0.0.0', port, process_request=process_request):
        print(f"[*] WebSocket Relay & Health on 0.0.0.0:{port}")
        await asyncio.Future()  # run forever

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[!] Server shutting down.")
