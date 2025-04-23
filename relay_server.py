import asyncio
import json

ROOMS = {}  # room_id -> list of StreamWriter

async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    data = await reader.readline()
    if not data:
        writer.close()
        return
    req = json.loads(data.decode())
    action = req.get('action')
    room_id = req.get('room_id')

    if action == 'create':
        # generate a new room
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
            # broadcast to others
            for w in list(ROOMS[room_id]):
                if w is not writer:
                    w.write(line)
                    await w.drain()
    finally:
        # cleanup
        participants = ROOMS.get(room_id, [])
        if writer in participants:
            participants.remove(writer)
        writer.close()
        await writer.wait_closed()
        if not participants:
            ROOMS.pop(room_id, None)
        print(f"[-] Peer left room {room_id}")

async def main():
    import argparse
    parser = argparse.ArgumentParser(description='P2P Relay Server')
    parser.add_argument('-p','--port', type=int, default=12345, help='Port to listen on')
    args = parser.parse_args()

    server = await asyncio.start_server(handle_client, host='0.0.0.0', port=args.port)
    print(f"[*] Relay server listening on 0.0.0.0:{args.port}")
    async with server:
        await server.serve_forever()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[!] Server shutting down.")

from flask import Flask
app = Flask(__name__)

@app.route('/health', methods=['GET'])
def health():
    return 'OK', 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000)
