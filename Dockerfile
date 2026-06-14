FROM python:3.10-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y openssl && rm -rf /var/lib/apt/lists/*

# Install python dependencies
RUN pip install --no-cache-dir websockets

# Copy server code
COPY server/ /app/
# Copy client code so ws-proxy can serve index.html
COPY client/ /app/client/

# Expose ports (5000 for tcp, 8080 for ws proxy)
EXPOSE 5000 8080

# The command will be overridden by docker-compose for each service
CMD ["python", "server.py"]
