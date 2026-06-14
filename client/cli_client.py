import socket
import threading
import sys
import json
import struct
import time

def recvall(sock, n):
    data = bytearray()
    while len(data) < n:
        packet = sock.recv(n - len(data))
        if not packet:
            return None
        data.extend(packet)
    return bytes(data)

def recv_msg(sock):
    raw_msglen = recvall(sock, 4)
    if not raw_msglen:
        return None
    msglen = struct.unpack('!I', raw_msglen)[0]
    data = recvall(sock, msglen)
    if data is None:
        return None
    return json.loads(data.decode('utf-8'))

def send_msg(sock, msg_dict):
    payload = json.dumps(msg_dict).encode('utf-8')
    header = struct.pack('!I', len(payload))
    sock.sendall(header + payload)

def receive_thread(sock):
    while True:
        try:
            msg = recv_msg(sock)
            if not msg:
                print("\n[!] Disconnected from server.")
                sys.exit(0)
            
            msg_type = msg.get("type")
            if msg_type == "CHAT":
                ttl = msg.get("ttl", 0)
                marker = f" [SELF-DESTRUCT IN {ttl}s]" if ttl > 0 else ""
                print(f"\n[{msg['room_name']}] {msg['timestamp']} | {msg['sender']}: {msg['message']}{marker}")
            elif msg_type == "PM":
                ttl = msg.get("ttl", 0)
                marker = f" [SELF-DESTRUCT IN {ttl}s]" if ttl > 0 else ""
                print(f"\n[PRIVATE] {msg['sender']}: {msg['message']}{marker}")
            elif msg_type == "ROOM_HISTORY":
                print(f"\n--- History for {msg['room_name']} ---")
                for h in msg.get("messages", []):
                    print(f"{h['timestamp']} | {h['sender']}: {h['message']}")
                print("-------------------------")
            elif msg_type == "INFO" or msg_type == "LOGIN_SUCCESS":
                print(f"\n[*] {msg.get('message')}")
            elif msg_type == "ERROR":
                print(f"\n[!] ERROR: {msg.get('message')}")
            elif msg_type == "USER_LIST":
                print(f"\n[Users Online] {', '.join(msg.get('users', []))}")
            elif msg_type == "ROOM_LIST":
                print(f"\n[Rooms Active] {', '.join(msg.get('rooms', []))}")
        except Exception as e:
            print("\n[!] Error receiving message:", e)
            break

def main():
    host = '127.0.0.1'
    port = 5000

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.connect((host, port))
    except Exception as e:
        print(f"Failed to connect: {e}")
        return

    print("Connected to StealthNet Server!")
    username = input("Enter Codename: ")
    send_msg(sock, {"type": "LOGIN", "username": username})

    threading.Thread(target=receive_thread, args=(sock,), daemon=True).start()

    time.sleep(0.5) # Wait for login response
    print("""
    Commands:
    /create <room>
    /join <room>
    /leave <room>
    /chat <room> <message>
    /stealth <room> <message>   (30s TTL)
    /pm <user> <message>
    /quit
    """)

    while True:
        try:
            cmd_input = input("> ").strip()
            if not cmd_input:
                continue
            
            parts = cmd_input.split(" ", 2)
            cmd = parts[0].lower()

            if cmd == "/quit":
                break
            elif cmd == "/create" and len(parts) >= 2:
                send_msg(sock, {"type": "CREATE_ROOM", "room_name": parts[1]})
            elif cmd == "/join" and len(parts) >= 2:
                send_msg(sock, {"type": "JOIN_ROOM", "room_name": parts[1]})
            elif cmd == "/leave" and len(parts) >= 2:
                send_msg(sock, {"type": "LEAVE_ROOM", "room_name": parts[1]})
            elif cmd == "/chat" and len(parts) >= 3:
                send_msg(sock, {"type": "CHAT", "target": "room", "target_name": parts[1], "message": parts[2], "ttl": 0})
            elif cmd == "/stealth" and len(parts) >= 3:
                send_msg(sock, {"type": "CHAT", "target": "room", "target_name": parts[1], "message": parts[2], "ttl": 30})
            elif cmd == "/pm" and len(parts) >= 3:
                send_msg(sock, {"type": "CHAT", "target": "user", "target_name": parts[1], "message": parts[2], "ttl": 0})
            else:
                print("Invalid command.")
        except KeyboardInterrupt:
            break

    sock.close()

if __name__ == "__main__":
    main()
