"""
StealthNet Server Load Tester & Maintenance Tool
Master Testing Script
"""

import socket, ssl, threading, json, struct, time, statistics, argparse, sqlite3, os

# ─── Utilitas soket dengan framing prefix-length 4-byte ───

def send_msg(s, d):
    data = json.dumps(d).encode('utf-8')
    s.sendall(struct.pack('!I', len(data)) + data)

def recv_msg(s, timeout=4.0):
    try:
        s.settimeout(timeout)
        hdr = b''
        while len(hdr) < 4:
            c = s.recv(4 - len(hdr))
            if not c: return None
            hdr += c
        length = struct.unpack('!I', hdr)[0]
        body = b''
        while len(body) < length:
            c = s.recv(length - len(body))
            if not c: return None
            body += c
        return json.loads(body.decode('utf-8'))
    except Exception:
        return None

def recv_n(s, n, timeout=5.0):
    msgs = []
    for _ in range(n):
        m = recv_msg(s, timeout)
        if m:
            msgs.append(m)
    return msgs

def drain_until_type(s, target_type, max_msgs=10, timeout=5.0):
    for _ in range(max_msgs):
        m = recv_msg(s, timeout)
        if not m:
            return None
        if m.get('type') == target_type:
            return m
    return None


# ─── Simulasi satu klien ───

def run_client(cid, host, port, num_messages, latencies, success_counts):
    try:
        raw = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        raw.connect((host, port))
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        s = ctx.wrap_socket(raw)
    except Exception:
        return

    username = f"su_{cid}"

    send_msg(s, {"type": "REGISTER", "username": username, "password": "Str3ss!"})
    recv_n(s, 2, timeout=5)

    send_msg(s, {"type": "LOGIN", "username": username, "password": "Str3ss!"})
    msgs = recv_n(s, 2, timeout=5)
    types = [m.get('type') for m in msgs]
    if 'LOGIN_SUCCESS' not in types:
        s.close()
        return

    room_name = f"stress_{cid}"
    send_msg(s, {"type": "CREATE_ROOM", "room_name": room_name})
    recv_n(s, 2, timeout=5)

    local_lat = []
    sent_ok = 0

    for i in range(num_messages):
        payload = {
            "type": "CHAT",
            "target": "room",
            "target_name": room_name,
            "message": f"s{i}",
            "ttl": 0
        }
        t0 = time.perf_counter()
        send_msg(s, payload)

        resp = drain_until_type(s, "CHAT", max_msgs=5, timeout=3.0)
        t1 = time.perf_counter()

        if resp:
            local_lat.append((t1 - t0) * 1000)
            sent_ok += 1

    s.close()
    latencies.extend(local_lat)
    success_counts.append(sent_ok)


# ─── Runner skenario ───

def run_scenario(host, port, num_clients, msg_per_client, label):
    print(f"\n{'─'*55}")
    print(f"  Skenario: {label}")
    print(f"{'─'*55}")

    latencies      = []
    success_counts = []
    threads        = []

    t_start = time.perf_counter()

    for i in range(num_clients):
        t = threading.Thread(
            target=run_client,
            args=(i, host, port, msg_per_client, latencies, success_counts)
        )
        threads.append(t)
        t.start()

    for t in threads:
        t.join()

    elapsed    = time.perf_counter() - t_start
    total_sent = sum(success_counts)
    conn_ok    = len([x for x in success_counts if x > 0])
    throughput = total_sent / elapsed if elapsed > 0 else 0

    print(f"  Koneksi Berhasil    : {conn_ok} / {num_clients}")
    print(f"  Total Pesan Dikirim : {total_sent}")
    print(f"  Waktu Total         : {elapsed:.2f} detik")
    print(f"  Throughput          : {throughput:.2f} pesan/detik")

    if latencies:
        print(f"  Latensi Rata-rata   : {statistics.mean(latencies):.2f} ms")
        print(f"  Latensi Median      : {statistics.median(latencies):.2f} ms")
        print(f"  Latensi Min         : {min(latencies):.2f} ms")
        print(f"  Latensi Maks        : {max(latencies):.2f} ms")
    else:
        print("  [!] Tidak ada data latensi")

# ─── DB Maintenance ───

def clear_db():
    paths = ['../stealthnet.db', 'stealthnet.db', '../server/stealthnet.db']
    db_path = next((p for p in paths if os.path.exists(p)), None)
    
    if not db_path:
        print("Database stealthnet.db not found!")
        return
        
    print(f"Connecting to database: {db_path}")
    conn = sqlite3.connect(db_path)
    try:
        conn.execute('PRAGMA journal_mode=WAL;')
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = [r[0] for r in cursor.fetchall()]
        
        for table in ['users', 'rooms', 'room_members', 'messages', 'reactions', 'read_receipts', 'friends', 'friend_requests']:
            if table in tables:
                print(f"Clearing table: {table}")
                conn.execute(f"DELETE FROM {table};")
        conn.commit()
        conn.execute('VACUUM;')
        print("Database successfully cleared and vacuumed!")
    except Exception as e:
        print(f"Error during database clearing: {e}")
    finally:
        conn.close()

def verify_db():
    paths = ['../stealthnet.db', 'stealthnet.db', '../server/stealthnet.db']
    db_path = next((p for p in paths if os.path.exists(p)), None)
    
    if not db_path:
        print("Database stealthnet.db not found!")
        return
        
    print(f"Verifying database: {db_path}")
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = [r[0] for r in cursor.fetchall()]
        
        print("\n--- Database Statistics ---")
        for table in tables:
            count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            print(f"Table '{table}': {count} rows")
        print("---------------------------")
    except Exception as e:
        print(f"Error verifying database: {e}")
    finally:
        conn.close()

# ─── Main CLI ───

def main():
    parser = argparse.ArgumentParser(description="StealthNet Master Testing & Maintenance Tool")
    subparsers = parser.add_subparsers(dest="mode", help="Available commands", required=True)
    
    # Stress test mode
    parser_stress = subparsers.add_parser("stress", help="Run the server load and latency stress test")
    parser_stress.add_argument("--host", default="127.0.0.1", help="Target TCP Server host")
    parser_stress.add_argument("--port", type=int, default=5000, help="Target TCP Server port")
    parser_stress.add_argument("--clients", type=int, default=None, help="Number of concurrent clients")
    parser_stress.add_argument("--messages", type=int, default=20, help="Number of messages per client")
    
    # Clear DB mode
    parser_clear = subparsers.add_parser("clear_db", help="Clear all records from the SQLite database")
    
    # Verify DB mode
    parser_verify = subparsers.add_parser("verify_db", help="Show database tables and row counts")
    
    args = parser.parse_args()
    
    if args.mode == "stress":
        print("=" * 55)
        print("  STEALTHNET SERVER STRESS TEST (Protokol Aktual)")
        print(f"  Target: {args.host}:{args.port}")
        print("=" * 55)
        
        if args.clients:
            run_scenario(args.host, args.port, args.clients, args.messages, f"{args.clients} klien × {args.messages} pesan")
        else:
            for nc, nm in [(10, 20), (50, 20), (100, 10)]:
                run_scenario(args.host, args.port, nc, nm, f"{nc} klien × {nm} pesan")
        print(f"\n{'='*55}\n  Pengujian selesai.\n{'='*55}")
        
    elif args.mode == "clear_db":
        clear_db()
        
    elif args.mode == "verify_db":
        verify_db()

if __name__ == "__main__":
    main()
