import cv2
from flask import Flask, Response, render_template_string
from flask_socketio import SocketIO, emit
import threading
import time

app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret!'
socketio = SocketIO(app)

# Camera setup
EXTERNAL_CAM_INDEX = 1  # Change this to your camera index
# camera = cv2.VideoCapture(EXTERNAL_CAM_INDEX)
camera = cv2.VideoCapture(EXTERNAL_CAM_INDEX, cv2.CAP_DSHOW)

if not camera.isOpened():
    print(f"Error: Could not open camera at index {EXTERNAL_CAM_INDEX}")
    # Try different indices
    for i in range(3):
        camera = cv2.VideoCapture(i)
        if camera.isOpened():
            EXTERNAL_CAM_INDEX = i
            print(f"Found camera at index {i}")
            break
    else:
        print("No camera found. Exiting.")
        exit()

# Traditional MJPEG stream endpoint
@app.route('/video_feed')
def video_feed():
    def generate():
        while True:
            success, frame = camera.read()
            if not success:
                break
            frame = cv2.resize(frame, (640, 480))
            ret, buffer = cv2.imencode('.jpg', frame)
            frame = buffer.tobytes()
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')
    return Response(generate(),
                  mimetype='multipart/x-mixed-replace; boundary=frame')

# WebSocket chat handlers
@socketio.on('connect')
def handle_connect():
    print('Client connected')

@socketio.on('disconnect')
def handle_disconnect():
    print('Client disconnected')

@socketio.on('chat_message')
def handle_message(data):
    print(f"Message from {data['user']}: {data['msg']}")
    emit('chat_message', data, broadcast=True)

@app.route('/')
def index():
    return render_template_string('''
    <!DOCTYPE html>
    <html>
    <head>
        <title>Camera + Chat</title>
        <style>
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
            }
            #video-feed {
                width: 100%;
                background: #000;
            }
            #chat-box {
                height: 400px;
                overflow-y: auto;
                border: 1px solid #ddd;
                padding: 10px;
                margin-bottom: 10px;
            }
            #chat-form {
                display: flex;
                gap: 10px;
            }
            #user {
                width: 100px;
            }
        </style>
    </head>
    <body>
        <h1>Live Camera with Chat</h1>
        <div id="container">
            <div id="video-container">
                <!-- Using traditional MJPEG stream -->
                <img id="video-feed" src="/video_feed">
            </div>
            <div id="chat-container">
                <div id="chat-box"></div>
                <form id="chat-form" onsubmit="sendMessage(); return false;">
                    <input id="user" type="text" placeholder="Your name" required>
                    <input id="message" type="text" placeholder="Type message" required>
                    <button type="submit">Send</button>
                </form>
            </div>
        </div>

        <script src="https://cdn.socket.io/4.5.4/socket.io.min.js"></script>
        <script>
            const socket = io();
            const chatBox = document.getElementById('chat-box');
            
            // Handle chat messages
            socket.on('chat_message', (data) => {
                const msgElement = document.createElement('div');
                msgElement.innerHTML = `<strong>${data.user}:</strong> ${data.msg}`;
                chatBox.appendChild(msgElement);
                chatBox.scrollTop = chatBox.scrollHeight;
            });
            
            function sendMessage() {
                const user = document.getElementById('user').value;
                const msg = document.getElementById('message').value;
                if (user && msg) {
                    socket.emit('chat_message', {user, msg});
                    document.getElementById('message').value = '';
                }
            }
        </script>
    </body>
    </html>
    ''')

if __name__ == '__main__':
    # Start the application
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)