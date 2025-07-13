#!/bin/bash

echo "🚀 Starting Cloudflare Tunnel Manager"
echo "======================================"

if [ ! -d "venv" ]; then
    echo "📦 Creating virtual environment..."
    python3 -m venv venv
fi

echo "🔧 Activating virtual environment..."
source venv/bin/activate

echo "📚 Installing dependencies..."
pip install -r requirements.txt

if [ -f ".env" ]; then
    echo "🔑 Loading environment variables from .env file..."
    export $(cat .env | xargs)
else
    echo "⚠️  No .env file found. You can:"
    echo "   1. Copy .env.example to .env and fill in your credentials"
    echo "   2. Or set environment variables manually"
    echo "   3. Or configure through the web interface"
    echo ""
fi

LOCAL_IP=$(python3 -c "
import socket
try:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect(('8.8.8.8', 80))
    print(s.getsockname()[0])
    s.close()
except:
    print('192.168.1.100')
")

echo "🌐 Local IP detected: $LOCAL_IP"
echo "🖥️  Web interface will be available at:"
echo "   - Local: http://localhost:5000"
echo "   - Network: http://$LOCAL_IP:5000"
echo ""

if ! command -v cloudflared &> /dev/null; then
    echo "⚠️  cloudflared is not installed. You'll need it to run tunnels."
    echo "   Install from: https://github.com/cloudflare/cloudflared/releases"
    echo ""
fi

echo "🚀 Starting Flask application..."
echo "   Press Ctrl+C to stop"
echo ""

python3 app.py
