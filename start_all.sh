#!/bin/bash
echo "Starting StealthNet..."
echo "Removing old containers (if any)..."
docker-compose down

echo "Building and starting Docker containers..."
docker-compose up -d --build

echo ""
echo "StealthNet is running!"
echo "HTTP UI (Browser): http://localhost:80"
echo "WebSocket Proxy: ws://localhost:8080"
echo "TCP Backend: localhost:5000"
echo ""
echo "To view live logs, run: docker-compose logs -f"
echo "To stop StealthNet, run: docker-compose down"
