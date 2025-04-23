import asyncio
import json

# In-memory rooms registry
ROOMS = {}

async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    # Read first line: determine if HTTP or chat protocol
    data = await reader.readline()
    if not data:
        writer.close()
        return
    text = data.decode(errors='ignore')
    # HTTP health check handling
    if text.startswith('GET '):
        parts = text.split(' ')
        path = parts[1] if len(parts) > 1 else ''
        if path == '/health':
            response = (
                'HTTP/1.1 200 OK\r\n'
                'Content-Type: text/plain\r\n'
                'Content-Length: 2\r\n'
                'Connection: close\r\n'
                '\r\n'
                'OK'
            )
            writer.write(response.encode())
            await writer.drain()
        writer.close()
        return

    # Chat JSON protocol
    try:
        req = json.loads(text)
        action = req.get('action')
        room_id = req.get('room_id')
    except Exception:
        writer.close()
        return

    # Handle create/join
    if action == 'create':
        room_id = ''.join(__import__('random').choices('0123456789', k=6))
        ROOMS[room_id] = [writer]
        writer.write(json.dumps({'status':'ok','room_id':room_id}).encode() + b"\n")
        await writer.drain()
        print(f"[+] Room {room_id} created")
    elif action == 'join':
        if room_id not in ROOMS:
            writer.write(json.dumps({'status':'error','error':'Room not found'}).encode() + b"\n")
            await writer.drain()
            writer.close()
            return
        ROOMS[room_id].append(writer)
        writer.write(json.dumps({'status':'ok','room_id':room_id}).encode() + b"\n")
        await writer.drain()
        print(f"[+] Peer joined room {room_id}")
    else:
        writer.close()
        return

    # Relay messages/files between peers
    try:
        while True:
            line = await reader.readline()
            if not line:
                break
            for w in list(ROOMS.get(room_id, [])):
                if w is not writer:
                    w.write(line)
                    await w.drain()
    finally:
        # Cleanup on disconnect
        participants = ROOMS.get(room_id, [])
        if writer in participants:
            participants.remove(writer)
        writer.close()
        await writer.wait_closed()
        if not participants:
            ROOMS.pop(room_id, None)
        print(f"[-] Peer left room {room_id}")

async def start_server(port: int):
    server = await asyncio.start_server(handle_client, host='0.0.0.0', port=port)
    print(f"[*] Relay & health server listening on 0.0.0.0:{port}")
    async with server:
        await server.serve_forever()

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='P2P Relay Server with Health on same port')
    parser.add_argument('-p', '--port', type=int, default=12345, help='Port for both relay and health')
    args = parser.parse_args()

    try:
        asyncio.run(start_server(args.port))
    except KeyboardInterrupt:
        print("\n[!] Server shutting down.")
