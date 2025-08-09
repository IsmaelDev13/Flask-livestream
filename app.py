
from flask import Flask, Response, render_template_string, request, jsonify
from flask_socketio import SocketIO, emit
import threading
import time
import os
import json
import base64
from flask_cors import CORS
import subprocess
from threading import Thread

app = Flask(__name__)
CORS(app)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'secret!')
# Enhanced SocketIO configuration for better compatibility
socketio = SocketIO(app, 
                   cors_allowed_origins="*",
                   logger=False,  # Disabled for Azure
                   engineio_logger=False,  # Disabled for Azure
                   async_mode='eventlet')  # Changed for Azure

# Track connected users and streaming state
connected_users = set()
current_stream = {
    'active': False,
    'streamer_id': None,
    'streamer_name': None,
    'stream_key': None
}

def start_rtmp_server():
    try:
        print("Attempting to start RTMP server...")
        process = subprocess.Popen(["node", "rtmp_server.js"], 
                                 stdout=subprocess.PIPE, 
                                 stderr=subprocess.PIPE)
        print(f"RTMP server started with PID: {process.pid}")
    except Exception as e:
        print(f"Failed to start RTMP server: {e}")

# Start the RTMP server in a separate thread when the Flask app starts
if os.environ.get('WERKZEUG_RUN_MAIN') == 'true' and os.environ.get('WEBSITE_SITE_NAME') is None:
    rtmp_thread = Thread(target=start_rtmp_server)
    rtmp_thread.daemon = True
    rtmp_thread.start()

@app.route('/video_feed')
def video_feed():
    def generate():
        # Simple placeholder without OpenCV
        placeholder_response = b'''--frame\r
Content-Type: text/plain\r

Server camera not available in cloud deployment. Use browser camera below.\r
'''
        while True:
            yield placeholder_response
            time.sleep(1)
    
    return Response(generate(),
                  mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/stream/info')
def stream_info():
    """Get current streaming information"""
    return jsonify(current_stream)

@app.route('/stream/rtmp-key')
def get_rtmp_key():
    """Generate RTMP streaming key"""
    app_url = request.host_url.rstrip('/')
    # Extract host without port for RTMP URL
    host = request.host.split(':')[0]
    rtmp_url = f"rtmp://{host}/live"
    stream_key = f"stream-{len(connected_users)}-{int(time.time())}"
    
    # Fix the HLS URL by using the correct port (8000)
    hls_url = f"http://{host}:8000/live/{stream_key}/index.m3u8"
    print(hls_url)

    return jsonify({
        'rtmp_url': rtmp_url,
        'stream_key': stream_key,
        'hls_playback': hls_url,
        'instructions': {
            'obs': 'In OBS: Settings → Stream → Service: Custom → Server: ' + rtmp_url + ' → Stream Key: ' + stream_key,
            'software': 'Any RTMP-compatible software can use these settings'
        }
    })
@socketio.on('chat_message')
def handle_message(data):
    print(f'Received message from {data.get("user", "anonymous")}: {data.get("msg", "")}')
    # Broadcast message to all connected clients
    emit('chat_message', data, broadcast=True)

@socketio.on('connect')
def handle_connect():
    connected_users.add(request.sid)
    viewer_count = len(connected_users)
    print(f'Client connected: {request.sid} (Total viewers: {viewer_count})')
    
    # Notify all clients of the updated viewer count
    emit('viewer_count', {'count': viewer_count}, broadcast=True)
    emit('status', {'msg': f'Client {request.sid[:8]} has connected'})
    
    # Send current stream info to new user
    emit('stream_info', current_stream)

@socketio.on('disconnect')
def handle_disconnect():
    global current_stream
    connected_users.discard(request.sid)
    viewer_count = len(connected_users)
    print(f'Client disconnected: {request.sid} (Total viewers: {viewer_count})')
    
    # If the disconnected user was streaming, stop the stream
    if current_stream['active'] and current_stream['streamer_id'] == request.sid:
        streamer_name = current_stream['streamer_name']
        current_stream = {
            'active': False,
            'streamer_id': None,
            'streamer_name': None,
            'stream_key': None
        }
        emit('stream_stopped', {
            'message': f'{streamer_name} disconnected (stream ended)'
        }, broadcast=True)
    
    # Notify remaining clients of the updated viewer count
    emit('viewer_count', {'count': viewer_count}, broadcast=True)

@socketio.on('start_broadcast')
def handle_start_broadcast(data):
    """Handle when someone starts broadcasting"""
    global current_stream
    
    user_name = data.get('user_name', 'Anonymous')
    stream_key = data.get('stream_key', None)
    
    if not current_stream['active']:
        current_stream = {
            'active': True,
            'streamer_id': request.sid,
            'streamer_name': user_name,
            'stream_key': stream_key
        }
        
        # Notify all users that streaming started
        emit('stream_started', {
            'streamer_name': user_name,
            'stream_key': stream_key,
            'message': f'{user_name} started broadcasting!'
        }, broadcast=True)
        
        print(f"{user_name} started broadcasting")
        return {'success': True, 'message': 'Broadcasting started'}
    else:
        return {'success': False, 'message': 'Someone else is already broadcasting'}

@socketio.on('stop_broadcast')
def handle_stop_broadcast():
    """Handle when someone stops broadcasting"""
    global current_stream
    
    if current_stream['active'] and current_stream['streamer_id'] == request.sid:
        streamer_name = current_stream['streamer_name']
        current_stream = {
            'active': False,
            'streamer_id': None,
            'streamer_name': None,
            'stream_key': None
        }
        
        # Notify all users that streaming stopped
        emit('stream_stopped', {
            'message': f'{streamer_name} stopped broadcasting'
        }, broadcast=True)
        
        print(f"{streamer_name} stopped broadcasting")
        return {'success': True, 'message': 'Broadcasting stopped'}
    else:
        return {'success': False, 'message': 'You are not currently broadcasting'}

@socketio.on('webrtc_offer')
def handle_webrtc_offer(data):
    """Handle WebRTC offer for peer-to-peer streaming"""
    # Broadcast the offer to all other users except sender
    emit('webrtc_offer', {
        'offer': data['offer'],
        'streamer_id': request.sid,
        'streamer_name': data.get('streamer_name', 'Anonymous')
    }, broadcast=True, include_self=False)

@socketio.on('webrtc_answer')
def handle_webrtc_answer(data):
    """Handle WebRTC answer"""
    # Send answer back to the streamer
    emit('webrtc_answer', {
        'answer': data['answer'],
        'viewer_id': request.sid
    }, room=data['streamer_id'])

@socketio.on('webrtc_ice_candidate')
def handle_ice_candidate(data):
    """Handle ICE candidate exchange"""
    # Forward ICE candidate to the target peer
    target_id = data.get('target_id')
    if target_id:
        emit('webrtc_ice_candidate', {
            'candidate': data['candidate'],
            'from_id': request.sid
        }, room=target_id)

@app.route('/')
def index():
    return render_template_string('''
    <!DOCTYPE html>
    <html>
    <head>
        <script src="https://cdn.jsdelivr.net/npm/hls.js@latest"></script>
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
            .broadcast-controls {
                margin: 10px 0;
            }
            .broadcast-controls button {
                margin-right: 10px;
                margin-bottom: 5px;
            }
            .stream-status {
                padding: 10px;
                margin: 10px 0;
                border-radius: 4px;
                font-weight: bold;
                text-align: center;
            }
            .stream-active {
                background: #d4edda;
                color: #155724;
            }
            .stream-inactive {
                background: #f8d7da;
                color: #721c24;
            }
            .modal {
                position: fixed;
                z-index: 1000;
                left: 0;
                top: 0;
                width: 100%;
                height: 100%;
                background-color: rgba(0,0,0,0.5);
            }
            .modal-content {
                background-color: #fefefe;
                margin: 15% auto;
                padding: 20px;
                border-radius: 8px;
                width: 80%;
                max-width: 600px;
            }
            .close {
                color: #aaa;
                float: right;
                font-size: 28px;
                font-weight: bold;
                cursor: pointer;
            }
            .close:hover {
                color: black;
            }
            .rtmp-info {
                background: #f8f9fa;
                padding: 15px;
                border-radius: 4px;
                margin: 10px 0;
                font-family: monospace;
            }
            .broadcasting {
                background: #dc3545 !important;
                animation: pulse 2s infinite;
            }
            @keyframes pulse {
                0% { opacity: 1; }
                50% { opacity: 0.7; }
                100% { opacity: 1; }
            }
        </style>
    </head>
    <body>
        <h1>Live Camera with Chat</h1>
        <div id="container">
            <div id="video-container">
                <div class="video-section">
                    <h3>🔴 Live Stream</h3>
                    <div id="stream-status" class="stream-status">
                        No one is streaming
                    </div>
                    
                    <!-- Broadcast Controls -->
                    <div id="broadcast-controls" class="broadcast-controls">
                        <button id="start-broadcast" onclick="startBroadcast()">📹 Start Broadcasting</button>
                        <button id="stop-broadcast" onclick="stopBroadcast()" disabled>⏹️ Stop Broadcasting</button>
                        <button id="get-rtmp-info" onclick="getRTMPInfo()">📡 Get RTMP Info</button>
                    </div>
                    
                    <!-- Stream Display -->
                    <video id="stream-video" autoplay playsinline controls style="display: none; width: 100%; max-height: 400px; background: #000; border-radius: 8px;">
                        Your browser doesn't support video playback.
                    </video>
                    
                    <!-- RTMP Info Modal -->
                    <div id="rtmp-modal" class="modal" style="display: none;">
                        <div class="modal-content">
                            <span class="close" onclick="closeRTMPModal()">&times;</span>
                            <h3>📡 RTMP Streaming Setup</h3>
                            <div id="rtmp-info"></div>
                        </div>
                    </div>
                </div>
                
                <div class="video-section">
                    <h3>Your Camera (Preview)</h3>
                    <div id="camera-controls">
                        <button id="start-camera" onclick="startCamera()">Start Camera</button>
                        <button id="stop-camera" onclick="stopCamera()" class="stop-btn" disabled>Stop Camera</button>
                    </div>
                    <video id="user-video" autoplay playsinline muted style="max-height: 250px;"></video>
                    <div id="camera-error" class="camera-error" style="display: none;">
                        Camera access denied or not available. Please allow camera access and try again.
                    </div>
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
            const streamVideo = document.getElementById('stream-video');
            const streamStatus = document.getElementById('stream-status');
            const startBroadcastBtn = document.getElementById('start-broadcast');
            const stopBroadcastBtn = document.getElementById('stop-broadcast');
            const startBtn = document.getElementById('start-camera');
            const stopBtn = document.getElementById('stop-camera');
            const cameraError = document.getElementById('camera-error');
            
            let mediaStream = null;
            let peerConnection = null;
            let isBroadcasting = false;
            let currentStreamInfo = { active: false };
            let hlsPlayer = null;
            
            // WebRTC configuration
            const rtcConfig = {
                iceServers: [
                    { urls: 'stun:stun.l.google.com:19302' },
                    { urls: 'stun:stun1.l.google.com:19302' }
                ]
            };
            
            // Broadcasting functions
            async function startBroadcast() {
                const userName = document.getElementById('user').value.trim() || 'Anonymous';
                
                try {
                    if (!mediaStream) {
                        await startCamera();
                    }
                    
                    // Get RTMP key first
                    const rtmpResponse = await fetch('/stream/rtmp-key');
                    const rtmpData = await rtmpResponse.json();
                    
                    const response = await new Promise((resolve) => {
                        socket.emit('start_broadcast', { 
                            user_name: userName,
                            stream_key: rtmpData.stream_key 
                        }, resolve);
                    });
                    
                    if (response.success) {
                        isBroadcasting = true;
                        startBroadcastBtn.disabled = true;
                        stopBroadcastBtn.disabled = false;
                        startBroadcastBtn.classList.add('broadcasting');
                        
                        // Start WebRTC broadcasting
                        await setupWebRTCBroadcast(userName);
                        
                        addMessage('System', 'You are now broadcasting!', 'status');
                    } else {
                        alert(response.message);
                    }
                } catch (error) {
                    console.error('Error starting broadcast:', error);
                    alert('Failed to start broadcasting');
                }
            }
            
            async function stopBroadcast() {
                const response = await new Promise((resolve) => {
                    socket.emit('stop_broadcast', {}, resolve);
                });
                
                if (response.success) {
                    isBroadcasting = false;
                    startBroadcastBtn.disabled = false;
                    stopBroadcastBtn.disabled = true;
                    startBroadcastBtn.classList.remove('broadcasting');
                    
                    // Stop WebRTC
                    if (peerConnection) {
                        peerConnection.close();
                        peerConnection = null;
                    }
                    
                    addMessage('System', 'Broadcasting stopped', 'status');
                }
            }
            
            async function setupWebRTCBroadcast(userName) {
                try {
                    peerConnection = new RTCPeerConnection(rtcConfig);
                    
                    // Add local stream to peer connection
                    mediaStream.getTracks().forEach(track => {
                        peerConnection.addTrack(track, mediaStream);
                    });
                    
                    // Create and send offer
                    const offer = await peerConnection.createOffer();
                    await peerConnection.setLocalDescription(offer);
                    
                    socket.emit('webrtc_offer', {
                        offer: offer,
                        streamer_name: userName
                    });
                    
                } catch (error) {
                    console.error('Error setting up WebRTC:', error);
                }
            }
            
            async function getRTMPInfo() {
                try {
                    const response = await fetch('/stream/rtmp-key');
                    const data = await response.json();
                    
                    const modal = document.getElementById('rtmp-modal');
                    const infoDiv = document.getElementById('rtmp-info');
                    
                    infoDiv.innerHTML = `
                        <div class="rtmp-info">
                            <h4>📺 For OBS Studio:</h4>
                            <p><strong>Server:</strong> ${data.rtmp_url}</p>
                            <p><strong>Stream Key:</strong> ${data.stream_key}</p>
                        </div>
                        
                        <div class="rtmp-info">
                            <h4>📱 Setup Instructions:</h4>
                            <ol>
                                <li>Open OBS Studio</li>
                                <li>Go to Settings → Stream</li>
                                <li>Service: Custom</li>
                                <li>Server: <code>${data.rtmp_url}</code></li>
                                <li>Stream Key: <code>${data.stream_key}</code></li>
                                <li>Click OK and Start Streaming!</li>
                            </ol>
                        </div>
                        
                        <div class="rtmp-info">
                            <h4>🎬 Alternative Software:</h4>
                            <p>You can use any RTMP-compatible software like Streamlabs, XSplit, or mobile apps with these same settings.</p>
                        </div>
                        
                        <div class="rtmp-info">
                            <p><strong>Note:</strong> Currently using WebRTC for browser-to-browser streaming. RTMP server integration coming soon!</p>
                        </div>
                    `;
                    
                    modal.style.display = 'block';
                } catch (error) {
                    console.error('Error getting RTMP info:', error);
                    alert('Failed to get RTMP information');
                }
            }
            
            function closeRTMPModal() {
                document.getElementById('rtmp-modal').style.display = 'none';
            }
            
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
            
            // Handle stream events
            socket.on('stream_started', (data) => {
                console.log('Stream started:', data);
                streamStatus.textContent = `🔴 LIVE: ${data.streamer_name}`;
                streamStatus.className = 'stream-status stream-active';
                addMessage('System', data.message, 'status');
                
                if (!isBroadcasting && data.stream_key) {
                    setupHLSPlayback(data.stream_key);
                }
            });
            
            socket.on('stream_stopped', (data) => {
                console.log('Stream stopped:', data);
                streamStatus.textContent = 'No one is streaming';
                streamStatus.className = 'stream-status stream-inactive';
                streamVideo.style.display = 'none';
                
                // Clean up HLS player if it exists
                if (hlsPlayer) {
                    hlsPlayer.destroy();
                    hlsPlayer = null;
                }
                
                addMessage('System', data.message, 'status');
            });
            
            socket.on('stream_info', (data) => {
                currentStreamInfo = data;
                if (data.active) {
                    streamStatus.textContent = `🔴 LIVE: ${data.streamer_name}`;
                    streamStatus.className = 'stream-status stream-active';
                    
                    if (!isBroadcasting && data.stream_key) {
                        setupHLSPlayback(data.stream_key);
                    }
                } else {
                    streamStatus.textContent = 'No one is streaming';
                    streamStatus.className = 'stream-status stream-inactive';
                    streamVideo.style.display = 'none';
                }
            });
            
            function setupHLSPlayback(streamKey) {
                                    const host = window.location.hostname;
    const hlsUrl = `http://${host}:8000/live/${streamKey}/index.m3u8`;
    
    console.log('Setting up HLS playback from:', hlsUrl);
                const appUrl = window.location.href.split('/').slice(0, 3).join('/');
                
                console.log('Setting up HLS playback from:', hlsUrl);
                
                if (Hls.isSupported()) {
                    if (hlsPlayer) {
                        hlsPlayer.destroy();
                    }
                    
                    hlsPlayer = new Hls();
                    hlsPlayer.loadSource(hlsUrl);
                    hlsPlayer.attachMedia(streamVideo);
                    hlsPlayer.on(Hls.Events.MANIFEST_PARSED, function() {
                        streamVideo.play().catch(e => console.error('Error playing video:', e));
                        streamVideo.style.display = 'block';
                    });
                    
                    hlsPlayer.on(Hls.Events.ERROR, function(event, data) {
                        console.error('HLS Error:', data);
                        if (data.fatal) {
                            switch(data.type) {
                                case Hls.ErrorTypes.NETWORK_ERROR:
                                    console.error('Fatal network error encountered, trying to recover');
                                    hlsPlayer.startLoad();
                                    break;
                                case Hls.ErrorTypes.MEDIA_ERROR:
                                    console.error('Fatal media error encountered, trying to recover');
                                    hlsPlayer.recoverMediaError();
                                    break;
                                default:
                                    console.error('Unrecoverable error encountered');
                                    setupHLSPlayback(streamKey);
                                    break;
                            }
                        }
                    });
                } else if (streamVideo.canPlayType('application/vnd.apple.mpegurl')) {
                    // For Safari
                    streamVideo.src = hlsUrl;
                    streamVideo.addEventListener('loadedmetadata', function() {
                        streamVideo.play().catch(e => console.error('Error playing video:', e));
                        streamVideo.style.display = 'block';
                    });
                } else {
                    console.error('HLS is not supported in this browser');
                }
            }
            
            // WebRTC handling for viewers
            socket.on('webrtc_offer', async (data) => {
                if (data.streamer_id !== socket.id) {
                    console.log('Received WebRTC offer from:', data.streamer_name);
                    
                    try {
                        const viewerPeerConnection = new RTCPeerConnection(rtcConfig);
                        
                        // Handle incoming stream
                        viewerPeerConnection.ontrack = (event) => {
                            console.log('Received remote stream');
                            streamVideo.srcObject = event.streams[0];
                            streamVideo.style.display = 'block';
                        };
                        
                        await viewerPeerConnection.setRemoteDescription(new RTCSessionDescription(data.offer));
                        const answer = await viewerPeerConnection.createAnswer();
                        await viewerPeerConnection.setLocalDescription(answer);
                        
                        socket.emit('webrtc_answer', {
                            answer: answer,
                            streamer_id: data.streamer_id
                        });
                        
                    } catch (error) {
                        console.error('Error handling WebRTC offer:', error);
                    }
                }
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
                if (hlsPlayer) {
                    hlsPlayer.destroy();
                }
            });
        </script>
    </body>
    </html>
    ''')

if __name__ == '__main__':
    print('Starting server...')
    
    # Get port from environment variable (for Azure deployment) or default to 5000
    port = int(os.environ.get('PORT', 5000))
    
    # For local development
    if os.environ.get('WEBSITE_SITE_NAME') is None:
        print('Running locally')
        socketio.run(app, host='0.0.0.0', port=port, debug=False)
    else:
        print('Running on Azure')
        # Azure handles the server startup with gunicorn