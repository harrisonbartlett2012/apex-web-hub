from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit
import logging
from apex_engine import ApexEngine

# Initialize Flask and WebSockets
app = Flask(__name__)
app.config['SECRET_KEY'] = 'apex_super_secret_key_2026'
socketio = SocketIO(app, async_mode='threading', cors_allowed_origins="*")

# Boot the APEX Engine
logging.info("Booting APEX Core...")
engine = ApexEngine()

@app.route('/')
def index():
    """Serves the main APEX web interface."""
    return render_template('index.html')

@socketio.on('connect')
def handle_connect():
    # Removed the server_message emit to prevent mobile reconnection spam
    logging.info(f"New web client connected: {request.sid}")

@socketio.on('user_message')
def handle_user_message(data):
    """Intercepts chat messages and processes them through the engine."""
    prompt = data.get('command', '').strip()
    session_id = request.sid
    
    if not prompt:
        return
    # Pure threaded background task, no complex event loops needed
    def background_ai_task(user_prompt, sid):
        try:
            # Process through the core engine synchronously
            reply = engine.generate_response(user_prompt)
            socketio.emit('ai_response', {'sender': 'APEX', 'text': reply}, to=sid)
        except Exception as e:
            socketio.emit('ai_response', {'sender': 'APEX', 'text': f"[SYS_ERROR] Web Gateway Failure: {str(e)}"}, to=sid)

    socketio.start_background_task(background_ai_task, prompt, session_id)

if __name__ == '__main__':
    logging.info("Starting APEX Cloud Node...")
    socketio.run(app, host='0.0.0.0', port=5000)
