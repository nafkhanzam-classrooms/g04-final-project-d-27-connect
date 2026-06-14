import socket
import select
import logging
import ssl
import os
import subprocess
import json
import struct
from datetime import datetime
from protocol import send_msg
from room_manager import RoomManager

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def ensure_certs():
    if not os.path.exists("cert.pem") or not os.path.exists("key.pem"):
        logging.info("Generating self-signed certificate...")
        try:
            subprocess.run([
                "openssl", "req", "-x509", "-newkey", "rsa:2048",
                "-keyout", "key.pem", "-out", "cert.pem", "-days", "365",
                "-nodes", "-subj", "/CN=localhost"
            ], check=True)
            return True
        except Exception:
            logging.warning("openssl failed. Disabling TLS.")
            return False
    return True

class StealthNetServer:
    def __init__(self, host='0.0.0.0', port=5000):
        self.use_tls = ensure_certs()
        
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.bind((host, port))
        self.server_socket.listen(100)
        
        if self.use_tls:
            self.ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            self.ssl_context.load_cert_chain(certfile="cert.pem", keyfile="key.pem")
            self.server_socket = self.ssl_context.wrap_socket(self.server_socket, server_side=True)
        
        self.server_socket.setblocking(False)
        self.inputs = [self.server_socket]
        self.manager = RoomManager()
        self.socket_to_user = {}
        self.buffers = {}

        logging.info(f"StealthNet V2 TLS Server listening on {host}:{port}")

    def run(self):
        try:
            while self.inputs:
                readable, _, exceptional = select.select(self.inputs, [], self.inputs)

                for sock in readable:
                    if sock is self.server_socket:
                        try:
                            client_socket, client_address = sock.accept()
                            client_socket.setblocking(False)
                            self.inputs.append(client_socket)
                            self.buffers[client_socket] = bytearray()
                            logging.info(f"New connection from {client_address}")
                        except ssl.SSLWantReadError: continue
                        except BlockingIOError: continue
                        except Exception as e: logging.error(f"Accept error: {e}")
                    else:
                        try:
                            chunk = sock.recv(8192)
                            if chunk:
                                self.buffers[sock].extend(chunk)
                                self.process_buffer(sock)
                            else:
                                self.disconnect_client(sock)
                        except ssl.SSLWantReadError: continue
                        except BlockingIOError: continue
                        except Exception: self.disconnect_client(sock)

                for sock in exceptional:
                    self.disconnect_client(sock)

        except KeyboardInterrupt:
            logging.info("Server shutting down.")
        finally:
            self.server_socket.close()

    def process_buffer(self, sock):
        buffer = self.buffers[sock]
        while len(buffer) >= 4:
            msg_len = struct.unpack('!I', buffer[:4])[0]
            MAX_PAYLOAD_SIZE = 10 * 1024 * 1024
            if msg_len > MAX_PAYLOAD_SIZE:
                logging.warning(f"Payload size {msg_len} exceeds 10MB limit. Dropping.")
                self.disconnect_client(sock)
                return
            
            if len(buffer) >= 4 + msg_len:
                data = buffer[4:4+msg_len]
                del buffer[:4+msg_len]
                try:
                    msg_dict = json.loads(data.decode('utf-8'))
                    self.handle_message(sock, msg_dict)
                except Exception as e:
                    logging.error(f"JSON decode error: {e}")
            else:
                break

    def disconnect_client(self, sock):
        if sock in self.inputs: self.inputs.remove(sock)
        if sock in self.buffers: del self.buffers[sock]
        if sock in self.socket_to_user:
            usr = self.socket_to_user[sock]
            self.manager.remove_user(usr, sock)
            if usr not in self.manager.active_sockets:
                self.manager.update_user_status(usr, "offline")
                self.broadcast_online_status(usr, False)
            del self.socket_to_user[sock]
        sock.close()

    # --- Handlers ---
    def handle_message(self, sock, data):
        msg_type = data.get("type")
        username = self.socket_to_user.get(sock)
        
        if msg_type == "REGISTER":
            usr = data.get("username")
            pwd = data.get("password")
            if not usr or not pwd:
                return send_msg(sock, {"type": "ERROR", "message": "Missing credentials"})
            if self.manager.register_user(usr, pwd):
                if self.manager.login_user(usr, pwd, sock):
                    self.socket_to_user[sock] = usr
                    self.manager.update_user_status(usr, "online")
                    send_msg(sock, {"type": "LOGIN_SUCCESS", "message": f"Welcome {usr}"})
                    self.send_initial_data(sock, usr)
                    self.broadcast_online_status(usr, True)
            else:
                # Fallback to login if user exists
                if self.manager.login_user(usr, pwd, sock):
                    self.socket_to_user[sock] = usr
                    self.manager.update_user_status(usr, "online")
                    send_msg(sock, {"type": "LOGIN_SUCCESS", "message": f"Welcome back {usr}"})
                    self.send_initial_data(sock, usr)
                    self.broadcast_online_status(usr, True)
                else:
                    send_msg(sock, {"type": "ERROR", "message": "Username exists"})

        elif msg_type == "LOGIN":
            usr = data.get("username") or data.get("userid")
            pwd = data.get("password")
            if not usr:
                return send_msg(sock, {"type": "ERROR", "message": "Missing credentials"})
            if self.manager.login_user(usr, pwd, sock):
                self.socket_to_user[sock] = usr
                self.manager.update_user_status(usr, "online")
                send_msg(sock, {"type": "LOGIN_SUCCESS", "message": f"Welcome {usr}"})
                self.send_initial_data(sock, usr)
                self.broadcast_online_status(usr, True)
            else:
                send_msg(sock, {"type": "ERROR", "message": "Invalid credentials"})
                
        # The following commands require authentication
        if not username: return
        
        if msg_type == "UPDATE_SETTINGS":
            pwd = data.get("password")
            new_pfp = data.get("profile_picture")
            self.manager.update_user_settings(username, new_password=pwd, new_pfp=new_pfp)
            send_msg(sock, {"type": "INFO", "message": "Settings updated"})
            self.send_initial_data(sock, username)
            
        elif msg_type == "SEND_FRIEND_REQUEST":
            target = data.get("target_user")
            if self.manager.send_friend_request(username, target):
                send_msg(sock, {"type": "FRIEND_REQUEST_SENT", "message": f"Friend request sent to {target}", "target": target})
                # Notify target if online
                for ts in self.manager.active_sockets.get(target, []):
                    pending = self.manager.get_pending_requests(target)
                    send_msg(ts, {"type": "FRIEND_REQUEST_RECEIVED", "requests": pending})
            else:
                send_msg(sock, {"type": "ERROR", "message": "Cannot send friend request (user not found or already friends)"})

        elif msg_type == "ACCEPT_FRIEND_REQUEST":
            req_id = data.get("request_id")
            result = self.manager.accept_friend_request(req_id, username)
            if result:
                sender, recv = result
                self.send_initial_data(sock, username)
                send_msg(sock, {"type": "INFO", "message": f"You are now friends with {sender}"})
                for ts in self.manager.active_sockets.get(sender, []):
                    self.send_initial_data(ts, sender)
                    send_msg(ts, {"type": "INFO", "message": f"{recv} accepted your friend request!"})
            else:
                send_msg(sock, {"type": "ERROR", "message": "Request not found or already handled"})

        elif msg_type == "REJECT_FRIEND_REQUEST":
            req_id = data.get("request_id")
            if self.manager.reject_friend_request(req_id, username):
                pending = self.manager.get_pending_requests(username)
                send_msg(sock, {"type": "FRIEND_REQUESTS_UPDATE", "requests": pending})
            else:
                send_msg(sock, {"type": "ERROR", "message": "Request not found"})

        elif msg_type == "GET_FRIEND_REQUESTS":
            pending = self.manager.get_pending_requests(username)
            sent = self.manager.get_sent_requests(username)
            send_msg(sock, {"type": "FRIEND_REQUESTS_UPDATE", "requests": pending, "sent_requests": sent})

        elif msg_type == "DELETE_ROOM":
            room_name = data.get("room_name")
            if self.manager.delete_room(room_name, username):
                sys_msg = {"type": "ROOM_DELETED", "room_name": room_name}
                self._route_message(username, "room", room_name, sys_msg)
                send_msg(sock, {"type": "INFO", "message": f"Room '{room_name}' deleted"})
                self.send_initial_data(sock, username)
            else:
                send_msg(sock, {"type": "ERROR", "message": "Permission denied or room not found"})

        elif msg_type == "ADD_TO_ROOM":
            room_name = data.get("room_name")
            target = data.get("target_user")
            friends = self.manager.get_friends(username)
            if target not in friends:
                send_msg(sock, {"type": "ERROR", "message": "You can only add friends to a room"})
            elif self.manager.add_user_to_room(room_name, username, target):
                send_msg(sock, {"type": "INFO", "message": f"{target} was added to {room_name}"})
                self.send_initial_data(sock, username)
                for ts in self.manager.active_sockets.get(target, []):
                    self.send_initial_data(ts, target)
                    send_msg(ts, {"type": "INFO", "message": f"You were added to {room_name} by {username}"})
            else:
                send_msg(sock, {"type": "ERROR", "message": "Could not add user to room"})

        elif msg_type == "CREATE_ROOM":
            room_name = data.get("room_name")
            code = self.manager.create_room(room_name, username)
            if code:
                send_msg(sock, {"type": "INFO", "message": f"Room '{room_name}' created. Invite Code: {code}"})
                self.send_initial_data(sock, username)
            else:
                if room_name in self.manager.get_user_rooms(username):
                    code = self.manager.get_room_invite_code(room_name)
                    send_msg(sock, {"type": "INFO", "message": f"Room '{room_name}' already exists. Invite Code: {code}"})
                    self.send_initial_data(sock, username)
                else:
                    send_msg(sock, {"type": "ERROR", "message": "Room exists"})

        elif msg_type == "JOIN_ROOM_BY_CODE":
            code = data.get("invite_code")
            room_name = self.manager.join_room_by_code(username, code)
            if room_name:
                send_msg(sock, {"type": "INFO", "message": f"Joined room {room_name}"})
                self.send_initial_data(sock, username)
            else:
                send_msg(sock, {"type": "ERROR", "message": "Invalid code"})
                
        elif msg_type == "LEAVE_ROOM":
            room_name = data.get("room_name")
            if room_name in self.manager.get_user_rooms(username):
                self.manager.leave_room(username, room_name)
                send_msg(sock, {"type": "INFO", "message": f"Left room {room_name}"})
                self.send_initial_data(sock, username)
            else:
                send_msg(sock, {"type": "ERROR", "message": "You are not in this room"})
                
        elif msg_type == "GET_PM_HISTORY":
            target = data.get("target_user")
            pm_room = self._get_pm_room(username, target)
            history = self.manager.get_history(pm_room)
            target_info = self.manager.get_user_info(target)
            send_msg(sock, {"type": "ROOM_HISTORY", "room_name": pm_room, "is_pm": True, "target_user": target, "target_info": target_info, "messages": history})

        elif msg_type == "GET_ROOM_HISTORY":
            room_name = data.get("room_name")
            # Verify membership
            if room_name in self.manager.get_user_rooms(username):
                history = self.manager.get_history(room_name)
                members_info = self.manager.get_room_members_info(room_name)
                role = self.manager.get_room_role(username, room_name)
                code = self.manager.get_room_invite_code(room_name)
                send_msg(sock, {
                    "type": "ROOM_HISTORY", 
                    "room_name": room_name, 
                    "messages": history, 
                    "members_info": members_info,
                    "my_role": role,
                    "invite_code": code if role == 'ADMIN' else None
                })
                
        elif msg_type == "TYPING":
            target = data.get("target")
            target_name = data.get("target_name")
            is_typing = data.get("is_typing", True)
            
            pkt = {"type": "TYPING", "sender": username, "target": target, "target_name": target_name, "is_typing": is_typing}
            self._route_message(username, target, target_name, pkt, exclude_sock=sock)
            
        elif msg_type == "MARK_READ":
            message_id = data.get("message_id")
            target = data.get("target")
            target_name = data.get("target_name")
            self.manager.mark_read(message_id, username)
            
            pkt = {"type": "READ_RECEIPT", "message_id": message_id, "user": username, "target": target, "target_name": target_name}
            self._route_message(username, target, target_name, pkt)

        elif msg_type == "CHAT":
            target = data.get("target")
            target_name = data.get("target_name")
            message = data.get("message", "")
            if not message and data.get("msg"): message = data.get("msg")
            try:
                ttl = int(data.get("ttl", 0))
            except (TypeError, ValueError):
                ttl = 0
            
            if not message and not data.get("file_data"): return
            
            # Check Role
            if target == "room":
                role = self.manager.get_room_role(username, target_name)
                if role is None:
                    return send_msg(sock, {"type": "ERROR", "message": "You are not a member of this room"})
                if role == 'READ_ONLY':
                    return send_msg(sock, {"type": "ERROR", "message": "You are muted in this room"})

            room_name = target_name if target == "room" else self._get_pm_room(username, target_name)
            msg_entry = self.manager.append_history(room_name, username, data, ttl)
            
            data.update({"timestamp": msg_entry["timestamp"], "message_id": msg_entry["message_id"], "sender": username})
            if target == "room": data["room_name"] = target_name
            else: data["type"] = "PM"
            
            self._route_message(username, target, target_name, data)

        elif msg_type == "EDIT_MSG":
            msg_id = data.get("message_id")
            new_text = data.get("new_message")
            target = data.get("target")
            target_name = data.get("target_name")
            if self.manager.edit_message(msg_id, username, new_text):
                pkt = {"type": "MSG_EDITED", "message_id": msg_id, "new_message": new_text, "target": target, "target_name": target_name}
                self._route_message(username, target, target_name, pkt)

        elif msg_type == "DELETE_MSG":
            msg_id = data.get("message_id")
            target = data.get("target")
            target_name = data.get("target_name")
            if self.manager.delete_message(msg_id, username):
                pkt = {"type": "MSG_DELETED", "message_id": msg_id, "target": target, "target_name": target_name}
                self._route_message(username, target, target_name, pkt)

        elif msg_type == "REACTION":
            msg_id = data.get("message_id")
            emoji = data.get("emoji")
            target = data.get("target")
            target_name = data.get("target_name")
            self.manager.add_reaction(msg_id, emoji, username)
            data["sender"] = username
            self._route_message(username, target, target_name, data)
            
        elif msg_type == "ADMIN_ACTION":
            action = data.get("action")
            room_name = data.get("room_name")
            target_user = data.get("target_user")
            
            if action == "MUTE":
                if self.manager.update_room_role(room_name, username, target_user, "READ_ONLY"):
                    sys_msg = {"type": "SYSTEM", "message": f"{target_user} was muted.", "room_name": room_name}
                    self._route_message(username, "room", room_name, sys_msg)
            elif action == "UNMUTE":
                if self.manager.update_room_role(room_name, username, target_user, "MEMBER"):
                    sys_msg = {"type": "SYSTEM", "message": f"{target_user} was unmuted.", "room_name": room_name}
                    self._route_message(username, "room", room_name, sys_msg)
            elif action == "KICK":
                if self.manager.get_room_role(username, room_name) == 'ADMIN':
                    self.manager.leave_room(target_user, room_name)
                    sys_msg = {"type": "SYSTEM", "message": f"{target_user} was kicked.", "room_name": room_name}
                    self._route_message(username, "room", room_name, sys_msg)
            elif action == "PROMOTE":
                if self.manager.update_room_role(room_name, username, target_user, "ADMIN"):
                    sys_msg = {"type": "SYSTEM", "message": f"{target_user} is now an admin.", "room_name": room_name}
                    self._route_message(username, "room", room_name, sys_msg)
                    # Force update on target if online
                    for ts in self.manager.active_sockets.get(target_user, []):
                        self.send_initial_data(ts, target_user)

    # --- Utils ---
    def _get_pm_room(self, u1, u2):
        s = sorted([u1, u2])
        return f"@PM:{s[0]}:{s[1]}"

    def _route_message(self, sender, target_type, target_name, pkt, exclude_sock=None):
        if target_type == "room":
            for member in self.manager.get_room_members(target_name):
                for s in self.manager.active_sockets.get(member, []):
                    if s != exclude_sock: send_msg(s, pkt)
        else: # PM
            for s in self.manager.active_sockets.get(target_name, []):
                if s != exclude_sock: send_msg(s, pkt)
            for s in self.manager.active_sockets.get(sender, []):
                if s != exclude_sock: send_msg(s, pkt)

    def broadcast_online_status(self, target_user, is_online):
        friends = self.manager.get_friends(target_user)
        user_info = self.manager.get_user_info(target_user)
        last_seen = user_info['last_seen'] if user_info else "Never"
        for friend in friends:
            for s in self.manager.active_sockets.get(friend, []):
                send_msg(s, {"type": "ONLINE_STATUS", "username": target_user, "is_online": is_online, "last_seen": last_seen})

    def send_initial_data(self, sock, username):
        friends = self.manager.get_friends(username)
        # determine online status of friends
        friend_status = {}
        for f in friends:
            user_info = self.manager.get_user_info(f)
            is_on = (f in self.manager.active_sockets)
            friend_status[f] = {
                "is_online": is_on,
                "last_seen": user_info['last_seen'] if user_info else "Never"
            }
            
        rooms = self.manager.get_user_rooms(username)
        pfp = self.manager.get_user_profile(username)
        pending_requests = self.manager.get_pending_requests(username)
        sent_requests = self.manager.get_sent_requests(username)
        
        send_msg(sock, {
            "type": "INITIAL_DATA", 
            "username": username,
            "profile_picture": pfp,
            "friends": friend_status,
            "rooms": rooms,
            "pending_requests": pending_requests,
            "sent_requests": sent_requests
        })

if __name__ == "__main__":
    host = os.environ.get('TCP_HOST', '0.0.0.0')
    port = int(os.environ.get('TCP_PORT', 5000))
    server = StealthNetServer(host=host, port=port)
    server.run()
