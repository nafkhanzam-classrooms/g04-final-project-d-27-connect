import asyncio
import websockets
import struct
import json
import logging
import ssl

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ws_proxy")

import os
TCP_SERVER_HOST = os.environ.get('TCP_HOST', '127.0.0.1')
TCP_SERVER_PORT = int(os.environ.get('TCP_PORT', 5000))
WS_HOST = os.environ.get('WS_HOST', '0.0.0.0')
WS_PORT = int(os.environ.get('WS_PORT', 8080))

async def handle_client(websocket):
    # Connect to the TCP server
    ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE
    
    try:
        reader, writer = await asyncio.open_connection(
            TCP_SERVER_HOST, 
            TCP_SERVER_PORT,
            ssl=ssl_context,
            limit=1024 * 1024 * 100
        )
        logger.info(f"Connected to TLS TCP server for WS client {websocket.remote_address}")
    except Exception as e:
        logger.warning(f"TLS connection failed ({e}), falling back to non-TLS...")
        try:
            reader, writer = await asyncio.open_connection(
                TCP_SERVER_HOST, 
                TCP_SERVER_PORT,
                limit=1024 * 1024 * 100
            )
            logger.info(f"Connected to TCP server for WS client {websocket.remote_address}")
        except Exception as e2:
            logger.error(f"Failed to connect to TCP server: {e2}")
            return

    # Task to forward messages from TCP to WebSocket
    async def tcp_to_ws():
        try:
            while True:
                # Read 4-byte header
                header = await reader.readexactly(4)
                length = struct.unpack('>I', header)[0]
                
                # Read payload
                payload = await reader.readexactly(length)
                message = payload.decode('utf-8')
                
                # Send to WebSocket
                await websocket.send(message)
        except asyncio.IncompleteReadError:
            logger.info("TCP connection closed (IncompleteReadError).")
        except websockets.exceptions.ConnectionClosed:
             logger.info("WebSocket connection closed during tcp_to_ws.")
        except Exception as e:
            logger.error(f"Error in tcp_to_ws: {e}")
        finally:
            await websocket.close()
            writer.close()

    # Task to forward messages from WebSocket to TCP
    async def ws_to_tcp():
        try:
            async for message in websocket:
                if isinstance(message, str):
                    payload = message.encode('utf-8')
                else:
                    payload = message
                header = struct.pack('>I', len(payload))
                writer.write(header + payload)
                await writer.drain()
        except websockets.exceptions.ConnectionClosed:
            logger.info(f"WebSocket client disconnected: {websocket.remote_address}")
        except Exception as e:
            logger.error(f"Error in ws_to_tcp: {e}")
        finally:
            writer.close()

    # Run both tasks concurrently
    task1 = asyncio.create_task(tcp_to_ws())
    task2 = asyncio.create_task(ws_to_tcp())
    
    try:
        done, pending = await asyncio.wait(
            [task1, task2],
            return_when=asyncio.FIRST_COMPLETED
        )
        # Cancel pending tasks
        for task in pending:
            task.cancel()
    finally:
        writer.close()
        await writer.wait_closed()
        logger.info(f"Disconnected WS client {websocket.remote_address}")

async def main():
    logger.info(f"Starting WS proxy on {WS_HOST}:{WS_PORT}")
    logger.info(f"Connecting to TCP server at {TCP_SERVER_HOST}:{TCP_SERVER_PORT}")
    
    async with websockets.serve(handle_client, WS_HOST, WS_PORT, max_size=None, ping_interval=None, ping_timeout=None):
        await asyncio.Future()  # run forever

if __name__ == "__main__":
    asyncio.run(main())
