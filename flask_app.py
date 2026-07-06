from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit
import logging
import time
from apex_engine import ApexEngine

app = Flask(__name__)
app.config['SECRET_KEY'] = 'apex_super_secret_key_2026'

# --- THE IRON DOME: PAYLOAD DEFENSE ---
# Instantly drops any incoming file or message larger than 15MB
app.config['MAX_CONTENT_LENGTH'] = 15 * 1024 * 1024 
socketio = SocketIO(app, async_mode='threading', cors_allowed_origins="*", max_http_buffer_size=15 * 1024 * 1024)

logging.info("Booting APEX Core...")
engine = ApexEngine()

# --- THE IRON DOME: RATE LIMITER MEMORY ---
user_requests = {}
MAX_MESSAGES_PER_MINUTE = 10

def check_rate_limit(sid):
    """Tracks timestamps of messages. If > 10 in the last 60 seconds, blocks the user."""
    current_time = time.time()
    
    # Initialize user if they are new
    if sid not in user_requests:
        user_requests[sid] = []

    # Clear out timestamps that are older than 60 seconds
    user_requests[sid] = [t for t in user_requests[sid] if current_time - t < 60]

    # Check if they hit the cap
    if len(user_requests[sid]) >= MAX_MESSAGES_PER_MINUTE:
        return False

    # Log this new message's timestamp and approve
    user_requests[sid].append(current_time)
    return True

@app.route('/')
def index():
    return render_template('index.html')

@socketio.on('connect')
def handle_connect():
    logging.info(f"New web client connected: {request.sid}")

@socketio.on('disconnect')
def handle_disconnect():
    # Clean up the rate limiter memory when they leave to save RAM
    sid = request.sid
    if sid in user_requests:
        del user_requests[sid]
    logging.info(f"Client disconnected: {sid}")

@socketio.on('user_message')
def handle_user_message(data):
    prompt = data.get('command', '').strip()
    file_data = data.get('file_data', None)
    session_id = request.sid
    
    if not prompt and not file_data:
        return

    # --- ACTIVATE RATE LIMITER ---
    if not check_rate_limit(session_id):
        socketio.emit('ai_response', {
            'sender': 'APEX', 
            'text': "[SYS_WARNING] Traffic threshold exceeded. Please wait 60 seconds before transmitting again. (Limit: 10 queries/min)"
        }, to=session_id)
        return
    
    def background_ai_task(user_prompt, incoming_file, sid):
        try:
            reply = engine.generate_response(user_prompt, incoming_file)
            socketio.emit('ai_response', {'sender': 'APEX', 'text': reply}, to=sid)
        except Exception as e:
            socketio.emit('ai_response', {'sender': 'APEX', 'text': f"[SYS_ERROR] Web Gateway Failure: {str(e)}"}, to=sid)

    socketio.start_background_task(background_ai_task, prompt, file_data, session_id)

if __name__ == '__main__':
    logging.info("Starting APEX Cloud Node...")
    socketio.run(app, host='0.0.0.0', port=5000)
