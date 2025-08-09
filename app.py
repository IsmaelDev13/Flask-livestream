import cv2
from flask import Flask, Response, render_template_string, request
from flask_socketio import SocketIO, emit
import threading
import time
import os
import numpy as np
from flask_cors import CORS

app = Flask(__name__)
CORS(app)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'secret!')
# Enhanced SocketIO configuration for better compatibility
socketio = SocketIO(app, 
                   cors_allowed_origins="*",
                   logger=False,  # Disabled for Azure
                   engineio_logger=False,  # Disabled for Azure
                   async_mode='eventlet')  # Changed for Azure

# Track connected users
connected_users = set()

# Camera setup with cloud deployment fallback
EXTERNAL_CAM_INDEX = 1  # Change this to your camera index
camera = None

# Try to initialize camera (will fail on cloud platforms)
try:
    camera = cv2.VideoCapture(EXTERNAL_CAM_INDEX, cv2.CAP_DSHOW)
    if not camera.isOpened():
        print(f"Error: Could not open camera at index {EXTERNAL_CAM_INDEX}")
        for i in range(3):
            camera = cv2.VideoCapture(i)
            if camera.isOpened():
                EXTERNAL_CAM_INDEX = i
                print(f"Found camera at index {i}")
                break
        else:
            print("No local camera found.")
            camera = None
except Exception as e:
    # print(f"Camera initialization failed: {e}")
    camera = None

@app.route('/video_feed')
def video_feed():
    def generate():
        # For cloud deployment - return placeholder
        placeholder = np.zeros((480, 640, 3), dtype=np.uint8)
        cv2.putText(placeholder, 'Use browser camera below', (120, 240), 
                   cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
        ret, buffer = cv2.imencode('.jpg', placeholder)
        frame_bytes = buffer.tobytes()
        
        while True:
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
            time.sleep(1)  # Slower refresh for placeholder
    
    return Response(generate(),
                  mimetype='multipart/x-mixed-replace; boundary=frame')

# Fixed: Removed namespace mismatch - all handlers use default namespace
@socketio.on('connect')
def handle_connect():
    connected_users.add(request.sid)
    viewer_count = len(connected_users)
    print(f'Client connected: {request.sid} (Total viewers: {viewer_count})')
    
    # Notify all clients of the updated viewer count
    emit('viewer_count', {'count': viewer_count}, broadcast=True)
    emit('status', {'msg': f'Client {request.sid[:8]} has connected'})

@socketio.on('disconnect')
def handle_disconnect():
    connected_users.discard(request.sid)
    viewer_count = len(connected_users)
    print(f'Client disconnected: {request.sid} (Total viewers: {viewer_count})')
    
    # Notify remaining clients of the updated viewer count
    emit('viewer_count', {'count': viewer_count}, broadcast=True)

@socketio.on('chat_message')
def handle_message(data):
    print(f'Received message from {data.get("user", "anonymous")}: {data.get("msg", "")}')
    # Broadcast message to all connected clients
    emit('chat_message', data, broadcast=True)

@app.route('/')
def index():
    return render_template_string('''
    <!DOCTYPE html>
    <html>
    <head>
        <title>Camera + Chat</title>
        <style>
            body {
                font-family: Arial, sans-serif;
                margin: 20px;
            }
            #container {
                display: flex;
                gap: 20px;
                max-width: 1200px;
                margin: 0 auto;
            }
            #video-container {
                flex: 2;
            }
            #chat-container {
                flex: 1;
                min-width: 300px;
            }
            #video-feed, #user-video {
                width: 100%;
                background: #000;
                border-radius: 8px;
                margin-bottom: 10px;
            }
            #user-video {
                max-height: 300px;
                object-fit: cover;
            }
            .video-section {
                margin-bottom: 20px;
            }
            .video-section h3 {
                margin-bottom: 10px;
                color: #333;
            }
            #camera-controls {
                margin-bottom: 10px;
            }
            #camera-controls button {
                margin-right: 10px;
                padding: 8px 16px;
                background: #28a745;
                color: white;
                border: none;
                border-radius: 4px;
                cursor: pointer;
            }
            #camera-controls button:hover {
                background: #218838;
            }
            #camera-controls button:disabled {
                background: #6c757d;
                cursor: not-allowed;
            }
            .stop-btn {
                background: #dc3545 !important;
            }
            .stop-btn:hover {
                background: #c82333 !important;
            }
            #chat-box {
                height: 400px;
                overflow-y: auto;
                border: 1px solid #ddd;
                padding: 10px;
                margin-bottom: 10px;
                background: #f9f9f9;
                border-radius: 8px;
                font-size: 14px;
            }
            #chat-form {
                display: flex;
                gap: 10px;
                flex-wrap: wrap;
            }
            #user {
                width: 100px;
                padding: 8px;
                border: 1px solid #ddd;
                border-radius: 4px;
            }
            #message {
                flex: 1;
                min-width: 150px;
                padding: 8px;
                border: 1px solid #ddd;
                border-radius: 4px;
            }
            button {
                padding: 8px 16px;
                background: #007bff;
                color: white;
                border: none;
                border-radius: 4px;
                cursor: pointer;
            }
            button:hover {
                background: #0056b3;
            }
            .message {
                margin-bottom: 5px;
                padding: 5px;
                border-radius: 4px;
            }
            .status {
                color: #666;
                font-style: italic;
            }
            .connection-status {
                padding: 5px 10px;
                margin-bottom: 10px;
                border-radius: 4px;
                font-size: 12px;
            }
            .connected {
                background: #d4edda;
                color: #155724;
            }
            .disconnected {
                background: #f8d7da;
                color: #721c24;
            }
            .viewer-count {
                padding: 5px 10px;
                margin-bottom: 10px;
                background: #e7f3ff;
                color: #0c5460;
                border-radius: 4px;
                font-size: 12px;
                text-align: center;
                font-weight: bold;
            }
            .camera-error {
                color: #721c24;
                background: #f8d7da;
                padding: 10px;
                border-radius: 4px;
                margin-bottom: 10px;
            }
        </style>
    </head>
    <body>
        <h1>Live Camera with Chat</h1>
        <div id="container">
            <div id="video-container">
                <div class="video-section">
                    <h3>Your Camera</h3>
                    <div id="camera-controls">
                        <button id="start-camera" onclick="startCamera()">Start Camera</button>
                        <button id="stop-camera" onclick="stopCamera()" class="stop-btn" disabled>Stop Camera</button>
                    </div>
                    <video id="user-video" autoplay playsinline muted></video>
                    <div id="camera-error" class="camera-error" style="display: none;">
                        Camera access denied or not available. Please allow camera access and try again.
                    </div>
                </div>
                <div class="video-section">
                    <h3>Server Feed</h3>
                    <img id="video-feed" src="/video_feed" alt="Server camera feed">
                </div>
            </div>
            <div id="chat-container">
                <div id="connection-status" class="connection-status disconnected">
                    Disconnected
                </div>
                <div id="viewer-count" class="viewer-count">
                    👥 0 viewers online
                </div>
                <div id="chat-box"></div>
                <form id="chat-form" onsubmit="sendMessage(event)">
                    <input id="user" type="text" placeholder="Your name" required>
                    <input id="message" type="text" placeholder="Type message" required>
                    <button type="submit">Send</button>
                </form>
            </div>
        </div>

        <script src="https://cdn.socket.io/4.5.4/socket.io.min.js"></script>
        <script>
            // Enhanced connection with fallback options
            const socket = io({
                transports: ['websocket', 'polling'],
                upgrade: true,
                rememberUpgrade: true,
                timeout: 5000,
                forceNew: true
            });
            
            const chatBox = document.getElementById('chat-box');
            const statusDiv = document.getElementById('connection-status');
            const viewerCountDiv = document.getElementById('viewer-count');
            const userVideo = document.getElementById('user-video');
            const startBtn = document.getElementById('start-camera');
            const stopBtn = document.getElementById('stop-camera');
            const cameraError = document.getElementById('camera-error');
            
            let mediaStream = null;
            
            // Camera functions
            async function startCamera() {
                try {
                    cameraError.style.display = 'none';
                    
                    mediaStream = await navigator.mediaDevices.getUserMedia({
                        video: {
                            width: { ideal: 640 },
                            height: { ideal: 480 },
                            facingMode: 'user'
                        },
                        audio: false
                    });
                    
                    userVideo.srcObject = mediaStream;
                    startBtn.disabled = true;
                    stopBtn.disabled = false;
                    
                    addMessage('System', 'Camera started successfully', 'status');
                    
                } catch (error) {
                    console.error('Error accessing camera:', error);
                    cameraError.style.display = 'block';
                    cameraError.textContent = `Camera error: ${error.message}`;
                    addMessage('System', 'Failed to access camera', 'status');
                }
            }
            
            function stopCamera() {
                if (mediaStream) {
                    mediaStream.getTracks().forEach(track => track.stop());
                    mediaStream = null;
                }
                userVideo.srcObject = null;
                startBtn.disabled = false;
                stopBtn.disabled = true;
                cameraError.style.display = 'none';
                
                addMessage('System', 'Camera stopped', 'status');
            }
            
            // Auto-start camera on page load
            window.addEventListener('load', () => {
                startCamera();
            });
            
            // More detailed connection logging
            socket.on('connect', () => {
                console.log('Connected to WebSocket server with transport:', socket.io.engine.transport.name);
                statusDiv.textContent = `Connected (${socket.io.engine.transport.name})`;
                statusDiv.className = 'connection-status connected';
                
                // Add a system message
                addMessage('System', 'Connected to chat', 'status');
            });
            
            socket.on('disconnect', (reason) => {
                console.log('Disconnected from WebSocket server. Reason:', reason);
                statusDiv.textContent = `Disconnected (${reason})`;
                statusDiv.className = 'connection-status disconnected';
                
                // Add a system message
                addMessage('System', `Disconnected: ${reason}`, 'status');
            });
            
            // Transport upgrade logging
            socket.io.on('upgrade', () => {
                console.log('Upgraded to transport:', socket.io.engine.transport.name);
            });
            
            // Handle viewer count updates
            socket.on('viewer_count', (data) => {
                console.log('Viewer count update:', data.count);
                const plural = data.count === 1 ? 'viewer' : 'viewers';
                viewerCountDiv.textContent = `👥 ${data.count} ${plural} online`;
            });
            
            // Handle status messages
            socket.on('status', (data) => {
                console.log('Status:', data);
                addMessage('System', data.msg, 'status');
            });
            
            // Handle chat messages
            socket.on('chat_message', (data) => {
                console.log('Received message:', data);
                addMessage(data.user, data.msg);
            });
            
            function addMessage(user, msg, type = 'message') {
                const msgElement = document.createElement('div');
                msgElement.className = `message ${type}`;
                msgElement.innerHTML = `<strong>${user}:</strong> ${msg}`;
                chatBox.appendChild(msgElement);
                chatBox.scrollTop = chatBox.scrollHeight;
            }
            
            function sendMessage(event) {
                event.preventDefault(); // Prevent form submission
                
                const user = document.getElementById('user').value.trim();
                const msg = document.getElementById('message').value.trim();
                
                if (user && msg) {
                    if (socket.connected) {
                        console.log('Sending message:', {user, msg});
                        socket.emit('chat_message', {user, msg});
                        document.getElementById('message').value = '';
                    } else {
                        alert('Not connected to server. Please wait for reconnection.');
                    }
                } else {
                    alert('Please enter both name and message');
                }
            }
            
            // Allow Enter key to send message
            document.getElementById('message').addEventListener('keypress', (e) => {
                if (e.key === 'Enter') {
                    sendMessage(e);
                }
            });
            
            // Handle connection errors with more detail
            socket.on('connect_error', (error) => {
                console.error('Connection error:', error);
                statusDiv.textContent = `Connection Error: ${error.message}`;
                statusDiv.className = 'connection-status disconnected';
                addMessage('System', `Connection error: ${error.message}`, 'status');
            });
            
            // Handle reconnection attempts
            socket.on('reconnect_attempt', (attemptNumber) => {
                console.log('Reconnection attempt:', attemptNumber);
                statusDiv.textContent = `Reconnecting... (attempt ${attemptNumber})`;
                addMessage('System', `Reconnecting... (attempt ${attemptNumber})`, 'status');
            });
            
            socket.on('reconnect', (attemptNumber) => {
                console.log('Reconnected after', attemptNumber, 'attempts');
                addMessage('System', `Reconnected after ${attemptNumber} attempts`, 'status');
            });
            
            // Clean up camera on page unload
            window.addEventListener('beforeunload', () => {
                stopCamera();
            });
        </script>
    </body>
    </html>
    ''')

if __name__ == '__main__':
    print('Starting server...')
    
    # Get port from environment variable (for Azure deployment) or default to 5000
    port = int(os.environ.get('PORT', 5000))
    debug_mode = os.environ.get('FLASK_ENV') != 'production'
    
    if debug_mode:
        print('Open http://localhost:5000 in your browser')
        socketio.run(app, host='0.0.0.0', port=port, debug=False)
    else:
        print('Running in production mode')
        # For Azure, gunicorn will handle the server startup
        app.run(host='0.0.0.0', port=port)