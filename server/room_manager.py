from datetime import datetime, timedelta
import sqlite3
import threading
import queue
import json
import logging
import os
import uuid
import secrets

class RoomManager:
    def __init__(self):
        self.active_sockets = {}
        self.db_path = os.environ.get('DB_PATH', 'stealthnet.db')
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.execute('PRAGMA journal_mode=WAL;')
        
        # Messages
        conn.execute('''CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT, room_name TEXT, sender TEXT, payload TEXT, timestamp TEXT, expires_at TIMESTAMP
        )''')
        try: conn.execute("ALTER TABLE messages ADD COLUMN payload TEXT")
        except: pass
        try: conn.execute("ALTER TABLE messages ADD COLUMN expires_at TIMESTAMP")
        except: pass
        try: conn.execute("ALTER TABLE messages ADD COLUMN message_id TEXT")
        except: pass
        try: conn.execute("ALTER TABLE messages ADD COLUMN reply_to TEXT")
        except: pass
        try: conn.execute("ALTER TABLE messages ADD COLUMN is_deleted INTEGER DEFAULT 0")
        except: pass
        try: conn.execute("ALTER TABLE messages ADD COLUMN is_edited INTEGER DEFAULT 0")
        except: pass
        try: conn.execute("ALTER TABLE messages ADD COLUMN ttl INTEGER DEFAULT 0")
        except: pass
            
        # Reactions
        conn.execute('''CREATE TABLE IF NOT EXISTS reactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT, message_id TEXT, emoji TEXT, user TEXT, UNIQUE(message_id, emoji, user)
        )''')
        
        # Read Receipts
        conn.execute('''CREATE TABLE IF NOT EXISTS read_receipts (
            message_id TEXT, user TEXT, timestamp TEXT, PRIMARY KEY (message_id, user)
        )''')
        
        # Users
        conn.execute('''CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY, password TEXT
        )''')
        try: conn.execute("ALTER TABLE users ADD COLUMN profile_picture TEXT")
        except: pass
        try: conn.execute("ALTER TABLE users ADD COLUMN email TEXT")
        except: pass
        try: conn.execute("ALTER TABLE users ADD COLUMN status TEXT DEFAULT 'offline'")
        except: pass
        try: conn.execute("ALTER TABLE users ADD COLUMN last_seen TEXT")
        except: pass
        
        # Friends
        conn.execute('''CREATE TABLE IF NOT EXISTS friends (
            user1 TEXT, user2 TEXT, PRIMARY KEY (user1, user2)
        )''')

        # Rooms
        conn.execute('''CREATE TABLE IF NOT EXISTS rooms (
            room_name TEXT PRIMARY KEY
        )''')
        try: conn.execute("ALTER TABLE rooms ADD COLUMN invite_code TEXT")
        except: pass
        try: conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_rooms_invite_code ON rooms(invite_code)")
        except: pass
        try: conn.execute("ALTER TABLE rooms ADD COLUMN profile_picture TEXT")
        except: pass

        # Room Members
        conn.execute('''CREATE TABLE IF NOT EXISTS room_members (
            room_name TEXT, username TEXT, PRIMARY KEY (room_name, username)
        )''')
        try: conn.execute("ALTER TABLE room_members ADD COLUMN role TEXT DEFAULT 'MEMBER'")
        except: pass

        # Friend Requests
        conn.execute('''CREATE TABLE IF NOT EXISTS friend_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender TEXT,
            receiver TEXT,
            status TEXT DEFAULT 'pending',
            timestamp TEXT,
            UNIQUE(sender, receiver)
        )''')

        conn.commit()
        conn.close()

    def _execute(self, query, args=(), fetchall=False, fetchone=False, commit=False):
        with sqlite3.connect(self.db_path, timeout=10) as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(query, args)
                if commit: conn.commit()
                if fetchall: return cursor.fetchall()
                if fetchone: return cursor.fetchone()
                return cursor.rowcount
            except sqlite3.Error as e:
                logging.error(f"DB Error: {e}")
                return None

    # ---- Users & Auth ----
    def register_user(self, username, password):
        if self._execute('SELECT username FROM users WHERE username = ?', (username,), fetchone=True):
            return False
        self._execute('INSERT INTO users (username, password) VALUES (?, ?)', (username, password), commit=True)
        # No auto-join rooms
        return True

    def login_user(self, username, password, sock):
        row = self._execute('SELECT password FROM users WHERE username = ?', (username,), fetchone=True)
        if not row or row[0] != password:
            return False
        # No auto-join rooms
        if username not in self.active_sockets:
            self.active_sockets[username] = []
        if sock not in self.active_sockets[username]:
            self.active_sockets[username].append(sock)
        return True

    def remove_user(self, username, sock):
        if username in self.active_sockets:
            if sock in self.active_sockets[username]:
                self.active_sockets[username].remove(sock)
            if not self.active_sockets[username]:
                del self.active_sockets[username]

    def _get_wib_now(self):
        from datetime import timezone, timedelta
        return datetime.now(timezone(timedelta(hours=7)))

    def update_user_status(self, username, status):
        timestamp = self._get_wib_now().strftime('%Y-%m-%d %H:%M:%S')
        self._execute('UPDATE users SET status = ?, last_seen = ? WHERE username = ?', (status, timestamp, username), commit=True)

    def get_user_info(self, username):
        row = self._execute('SELECT username, profile_picture, email, status, last_seen FROM users WHERE username = ?', (username,), fetchone=True)
        if not row: return None
        return {
            "username": row[0],
            "profile_picture": row[1],
            "email": row[2] or f"{row[0].lower()}@stealthnet.local",
            "status": row[3] or "offline",
            "last_seen": row[4] or "Never"
        }

    def get_room_members_info(self, room_name):
        rows = self._execute('SELECT username, role FROM room_members WHERE room_name = ?', (room_name,), fetchall=True)
        members = []
        for uname, role in rows:
            info = self.get_user_info(uname)
            if info: 
                info['role'] = role
                members.append(info)
        return members

    def get_user_profile(self, username):
        row = self._execute('SELECT profile_picture FROM users WHERE username = ?', (username,), fetchone=True)
        return row[0] if row else None

    def update_user_settings(self, username, new_password=None, new_pfp=None):
        if new_password:
            self._execute('UPDATE users SET password = ? WHERE username = ?', (new_password, username), commit=True)
        if new_pfp:
            self._execute('UPDATE users SET profile_picture = ? WHERE username = ?', (new_pfp, username), commit=True)

    # ---- Socials ----
    def get_friends(self, username):
        rows = self._execute('SELECT user2 FROM friends WHERE user1 = ?', (username,), fetchall=True)
        return [r[0] for r in (rows or [])]

    def add_friend(self, user1, user2):
        # Ensure user2 exists
        if not self._execute('SELECT username FROM users WHERE username = ?', (user2,), fetchone=True):
            return False # User doesn't exist
        
        self._execute('INSERT OR IGNORE INTO friends (user1, user2) VALUES (?, ?)', (user1, user2), commit=True)
        self._execute('INSERT OR IGNORE INTO friends (user1, user2) VALUES (?, ?)', (user2, user1), commit=True)
        return True

    # ---- Rooms & Roles ----
    def generate_invite_code(self):
        while True:
            code = secrets.token_hex(4).upper()
            if not self._execute('SELECT room_name FROM rooms WHERE invite_code = ?', (code,), fetchone=True):
                return code

    def create_room(self, room_name, creator):
        if self._execute('SELECT room_name FROM rooms WHERE room_name = ?', (room_name,), fetchone=True):
            return False
        invite_code = self.generate_invite_code()
        self._execute('INSERT INTO rooms (room_name, invite_code) VALUES (?, ?)', (room_name, invite_code), commit=True)
        # Creator is ADMIN
        self._execute('INSERT INTO room_members (room_name, username, role) VALUES (?, ?, ?)', (room_name, creator, 'ADMIN'), commit=True)
        return invite_code

    def join_room_by_code(self, username, invite_code):
        row = self._execute('SELECT room_name FROM rooms WHERE invite_code = ?', (invite_code,), fetchone=True)
        if not row: return None
        room_name = row[0]
        self._execute('INSERT OR IGNORE INTO room_members (room_name, username, role) VALUES (?, ?, ?)', (room_name, username, 'MEMBER'), commit=True)
        return room_name

    def join_room(self, username, room_name):
        self._execute('INSERT OR IGNORE INTO rooms (room_name) VALUES (?)', (room_name,), commit=True)
        self._execute('INSERT OR IGNORE INTO room_members (room_name, username, role) VALUES (?, ?, ?)', (room_name, username, 'MEMBER'), commit=True)
        return True

    def leave_room(self, username, room_name):
        self._execute('DELETE FROM room_members WHERE room_name = ? AND username = ?', (room_name, username), commit=True)

    def get_room_role(self, username, room_name):
        row = self._execute('SELECT role FROM room_members WHERE room_name = ? AND username = ?', (room_name, username), fetchone=True)
        return row[0] if row else None

    def get_room_members(self, room_name):
        rows = self._execute('SELECT username FROM room_members WHERE room_name = ?', (room_name,), fetchall=True)
        return [r[0] for r in (rows or [])]

    def get_user_rooms(self, username):
        rows = self._execute('SELECT room_name FROM room_members WHERE username = ?', (username,), fetchall=True)
        return [r[0] for r in (rows or [])]

    def update_room_role(self, room_name, admin_user, target_user, new_role):
        if self.get_room_role(admin_user, room_name) != 'ADMIN': return False
        self._execute('UPDATE room_members SET role = ? WHERE room_name = ? AND username = ?', (new_role, room_name, target_user), commit=True)
        return True

    def update_room_info(self, room_name, admin_user, new_pfp):
        if self.get_room_role(admin_user, room_name) != 'ADMIN': return False
        self._execute('UPDATE rooms SET profile_picture = ? WHERE room_name = ?', (new_pfp, room_name), commit=True)
        return True

    def get_room_invite_code(self, room_name):
        row = self._execute('SELECT invite_code FROM rooms WHERE room_name = ?', (room_name,), fetchone=True)
        return row[0] if row else None

    # ---- Messages ----
    def append_history(self, room_name, sender, data, ttl_seconds):
        now = self._get_wib_now()
        timestamp = now.strftime('%Y-%m-%d %H:%M:%S')
        message_id = str(uuid.uuid4())
        data["message_id"] = message_id
        data["timestamp"] = timestamp
        data["sender"] = sender
        
        reply_to = data.get("reply_to")
        payload = json.dumps(data)
        
        expires_at = None
        if ttl_seconds > 0:
            expires_at = (now + timedelta(seconds=ttl_seconds)).strftime('%Y-%m-%d %H:%M:%S')
            
        try:
            self._execute('''
                INSERT INTO messages (room_name, sender, payload, timestamp, expires_at, message_id, reply_to, ttl)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (room_name, sender, payload, timestamp, expires_at, message_id, reply_to, ttl_seconds), commit=True)
        except Exception as e:
            print(f"[ERROR] Failed to insert message into DB: {e}")
            raise
        
        return {"timestamp": timestamp, "message_id": message_id}
        
    def edit_message(self, message_id, sender, new_text):
        row = self._execute('SELECT payload, is_deleted FROM messages WHERE message_id = ? AND sender = ?', (message_id, sender), fetchone=True)
        if not row or row[1] == 1: return False
        try:
            data = json.loads(row[0])
            data["message"] = new_text
            self._execute('UPDATE messages SET payload = ?, is_edited = 1 WHERE message_id = ?', (json.dumps(data), message_id), commit=True)
            return True
        except:
            return False

    def delete_message(self, message_id, sender):
        # We don't drop the row, we mark it deleted to sync UI
        res = self._execute('UPDATE messages SET is_deleted = 1 WHERE message_id = ? AND sender = ?', (message_id, sender), commit=True)
        return res and res > 0

    def mark_read(self, message_id, username):
        timestamp = self._get_wib_now().strftime('%Y-%m-%d %H:%M:%S')
        self._execute('INSERT OR IGNORE INTO read_receipts (message_id, user, timestamp) VALUES (?, ?, ?)', (message_id, username, timestamp), commit=True)

    def get_history(self, room_name):
        now_str = self._get_wib_now().strftime('%Y-%m-%d %H:%M:%S')
        rows = self._execute('''
            SELECT payload, message_id, is_deleted, is_edited FROM messages 
            WHERE room_name = ? 
            AND (expires_at IS NULL OR expires_at > ?)
            ORDER BY timestamp ASC
        ''', (room_name, now_str), fetchall=True)
        
        history = []
        for row in (rows or []):
            if not row[0]: continue
            try: data = json.loads(row[0])
            except Exception: continue
            
            msg_id = row[1]
            is_deleted = row[2]
            is_edited = row[3]
            
            data["message_id"] = msg_id
            data["is_deleted"] = bool(is_deleted)
            data["is_edited"] = bool(is_edited)
            
            if is_deleted:
                data["message"] = "This message was deleted."
                data["file_data"] = None
                
            # Attach Reactions
            reactions = self._execute('SELECT emoji, COUNT(*) FROM reactions WHERE message_id = ? GROUP BY emoji', (msg_id,), fetchall=True)
            if reactions:
                data["reactions"] = {r[0]: r[1] for r in reactions}
                
            # Attach Read Receipts
            receipts = self._execute('SELECT user FROM read_receipts WHERE message_id = ?', (msg_id,), fetchall=True)
            if receipts:
                data["read_by"] = [r[0] for r in receipts]

            history.append(data)
        return history

    # ---- Friend Requests ----
    def send_friend_request(self, sender, receiver):
        if not self._execute('SELECT username FROM users WHERE username = ?', (receiver,), fetchone=True):
            return False  # receiver doesn't exist
        if self._execute('SELECT user2 FROM friends WHERE user1 = ? AND user2 = ?', (sender, receiver), fetchone=True):
            return False  # already friends
        timestamp = self._get_wib_now().strftime('%Y-%m-%d %H:%M:%S')
        try:
            self._execute('INSERT OR IGNORE INTO friend_requests (sender, receiver, status, timestamp) VALUES (?, ?, ?, ?)',
                          (sender, receiver, 'pending', timestamp), commit=True)
            return True
        except:
            return False

    def accept_friend_request(self, request_id, receiver):
        row = self._execute('SELECT sender, receiver FROM friend_requests WHERE id = ? AND receiver = ? AND status = ?',
                            (request_id, receiver, 'pending'), fetchone=True)
        if not row: return False
        sender, recv = row
        self._execute('UPDATE friend_requests SET status = ? WHERE id = ?', ('accepted', request_id), commit=True)
        self._execute('INSERT OR IGNORE INTO friends (user1, user2) VALUES (?, ?)', (sender, recv), commit=True)
        self._execute('INSERT OR IGNORE INTO friends (user1, user2) VALUES (?, ?)', (recv, sender), commit=True)
        return (sender, recv)

    def reject_friend_request(self, request_id, receiver):
        res = self._execute('UPDATE friend_requests SET status = ? WHERE id = ? AND receiver = ? AND status = ?',
                            ('rejected', request_id, receiver, 'pending'), commit=True)
        return res and res > 0

    def get_pending_requests(self, username):
        rows = self._execute(
            'SELECT id, sender, timestamp FROM friend_requests WHERE receiver = ? AND status = ?',
            (username, 'pending'), fetchall=True)
        return [{'id': r[0], 'sender': r[1], 'timestamp': r[2]} for r in (rows or [])]

    def get_sent_requests(self, username):
        rows = self._execute(
            'SELECT receiver, status FROM friend_requests WHERE sender = ? AND status = ?',
            (username, 'pending'), fetchall=True)
        return [r[0] for r in (rows or [])]

    # ---- Room Admin ----
    def delete_room(self, room_name, admin_user):
        if self.get_room_role(admin_user, room_name) != 'ADMIN': return False
        self._execute('DELETE FROM room_members WHERE room_name = ?', (room_name,), commit=True)
        self._execute('DELETE FROM messages WHERE room_name = ?', (room_name,), commit=True)
        self._execute('DELETE FROM rooms WHERE room_name = ?', (room_name,), commit=True)
        return True

    def add_user_to_room(self, room_name, admin_user, target_user):
        if self.get_room_role(admin_user, room_name) != 'ADMIN': return False
        if not self._execute('SELECT username FROM users WHERE username = ?', (target_user,), fetchone=True):
            return False
        self._execute('INSERT OR IGNORE INTO room_members (room_name, username, role) VALUES (?, ?, ?)',
                      (room_name, target_user, 'MEMBER'), commit=True)
        return True

    def add_reaction(self, message_id, emoji, user):
        try:
            self._execute('INSERT INTO reactions (message_id, emoji, user) VALUES (?, ?, ?)', (message_id, emoji, user), commit=True)
        except:
            self._execute('DELETE FROM reactions WHERE message_id = ? AND emoji = ? AND user = ?', (message_id, emoji, user), commit=True)
