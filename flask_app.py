from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit
import asyncio
import logging
from apex_engine import ApexEngine

# Initialize Flask and WebSockets
app = Flask(__name__)
app.config['SECRET_KEY'] = 'apex_super_secret_key_2026'
socketio = SocketIO(app, async_mode='geventt', cors_allowed_origins="*")

# Boot the APEX Engine
logging.info("Booting APEX Core...")
engine = ApexEngine()

@app.route('/')
def index():
    """Serves the main APEX web interface."""
    return render_template('index.html')

@socketio.on('connect')
def handle_connect():
    logging.info(f"New web client connected: {request.sid}")
    emit('server_message', {'sender': 'APEX', 'text': '[SYSTEM ONLINE] Welcome to APEX Web Hub. Core Engine ready.'})

@socketio.on('user_message')
def handle_user_message(data):
    """Intercepts chat messages and processes them through the engine."""
    prompt = data.get('command', '').strip()
    session_id = request.sid
    
    if not prompt:
        return

    # Desktop-Exclusive Feature Check
    if prompt.lower().startswith("/search"):
        socketio.emit('ai_response', {
            'sender': 'APEX',
            'text': "[PREMIUM FEATURE] Live internet scraping is streamlined exclusively for the APEX Desktop Application. Please submit a standard query or upgrade for live data."
        }, to=session_id)
        return
    
    # We run the AI generation in a background task so it doesn't freeze the web server
    def background_ai_task(user_prompt, sid):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            # Process through the core engine
            reply = loop.run_until_complete(engine.generate_response(user_prompt))
            socketio.emit('ai_response', {'sender': 'APEX', 'text': reply}, to=sid)
        except Exception as e:
            socketio.emit('ai_response', {'sender': 'APEX', 'text': f"[SYS_ERROR] Web Gateway Failure: {str(e)}"}, to=sid)
        finally:
            loop.close()

    socketio.start_background_task(background_ai_task, prompt, session_id)

if __name__ == '__main__':
    logging.info("Starting APEX Cloud Node...")
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)
