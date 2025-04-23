import asyncio
import json
import threading
from flask import Flask

# In-memory rooms registry
ROOMS = {}

# Flask app for health checks
app = Flask(__name__)
@app.route('/', methods=['GET'])
def health():
    return 'OK', 200

def run_health():
    # Run Flask in a separate thread
    app.run(host='0.0.0.0', port=8000, threaded=True)

async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    data = await reader.readline()
    if not data:
        writer.close()
        return
    req = json.loads(data.decode())
    action = req.get('action')
    room_id = req.get('room_id')

    if action == 'create':
        # generate a new room ID
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

    try:
        while True:
            line = await reader.readline()
            if not line:
                break
            # Broadcast to all other peers
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
    print(f"[*] Relay server listening on 0.0.0.0:{port}")
    async with server:
        await server.serve_forever()

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='P2P Relay Server with Health Check')
    parser.add_argument('-p', '--port', type=int, default=12345, help='Port for relay service')
    args = parser.parse_args()

    # Start health-check endpoint
    threading.Thread(target=run_health, daemon=True).start()
    print('[*] Health check available at http://0.0.0.0:8000/health')

    # Start the relay server (asyncio)
    try:
        asyncio.run(start_server(args.port))
    except KeyboardInterrupt:
        print("\n[!] Server shutting down.")
