# relay_server.py
#!/usr/bin/env python3
"""
P2P Relay & Health Server using aiohttp WebSockets

USAGE:
  # Run on Render or any HTTP-capable host (uses $PORT or defaults to 12345):
  python3 relay_server.py

Clients connect via WebSocket to ws://<host>:<port>/ws
Health check on HTTP GET or HEAD at / or /health returns 200 OK.
"""
import os
import json
import random
from aiohttp import web, WSMsgType

# room_id -> set of WebSocketResponse
ROOMS = {}

async def websocket_handler(request):
    ws = web.WebSocketResponse()
    await ws.prepare(request)

    # Initial handshake: receive JSON action
    msg = await ws.receive()
    if msg.type != WSMsgType.TEXT:
        await ws.close()
        return ws
    try:
        req = json.loads(msg.data)
        action = req.get('action')
        room_id = req.get('room_id')
    except Exception:
        await ws.close()
        return ws

    if action == 'create':
        room_id = ''.join(random.choices('0123456789', k=6))
        ROOMS[room_id] = {ws}
        await ws.send_json({'status':'ok','room_id':room_id})
        print(f"[+] Room {room_id} created")
    elif action == 'join':
        if room_id not in ROOMS:
            await ws.send_json({'status':'error','error':'Room not found'})
            await ws.close()
            return ws
        ROOMS[room_id].add(ws)
        await ws.send_json({'status':'ok','room_id':room_id})
        print(f"[+] Peer joined room {room_id}")
    else:
        await ws.close()
        return ws

    # Broadcast loop
    try:
        async for msg in ws:
            if msg.type == WSMsgType.TEXT:
                for peer in set(ROOMS.get(room_id, [])):
                    if peer is not ws:
                        await peer.send_str(msg.data)
            elif msg.type == WSMsgType.ERROR:
                break
    finally:
        peers = ROOMS.get(room_id, set())
        peers.discard(ws)
        if not peers:
            ROOMS.pop(room_id, None)
        print(f"[-] Peer left room {room_id}")

    return ws

async def health(request):
    return web.Response(text='OK')

if __name__ == '__main__':
    port = int(os.getenv('PORT', '12345'))
    app = web.Application()
    # Health endpoints
    app.router.add_get('/', health)
    app.router.add_head('/', health)
    app.router.add_get('/health', health)
    app.router.add_head('/health', health)
    # WebSocket endpoint
    app.router.add_get('/ws', websocket_handler)

    print(f"[*] Running server on 0.0.0.0:{port}")
    web.run_app(app, host='0.0.0.0', port=port)
