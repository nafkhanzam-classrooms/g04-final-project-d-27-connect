import json
import struct

def send_msg(sock, msg_dict):
    """Serializes a dictionary to JSON and sends it with a 4-byte length prefix."""
    payload = json.dumps(msg_dict).encode('utf-8')
    header = struct.pack('!I', len(payload))
    data_to_send = header + payload
    
    # Save the old timeout and set to blocking for sending large payloads
    import socket
    old_timeout = sock.gettimeout()
    sock.setblocking(True)
    try:
        sock.sendall(data_to_send)
        return True
    except Exception as e:
        return False
    finally:
        # Restore the previous non-blocking state
        if old_timeout == 0.0:
            sock.setblocking(False)
        else:
            sock.settimeout(old_timeout)
