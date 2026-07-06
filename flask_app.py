from flask import Flask, render_template, request, session, jsonify, redirect
from flask_socketio import SocketIO, emit, disconnect
import logging
import time
from apex_engine import ApexEngine

app = Flask(__name__)
app.config['SECRET_KEY'] = 'apex_super_secret_key_2026'
app.config['MAX_CONTENT_LENGTH'] = 15 * 1024 * 1024 

socketio = SocketIO(app, async_mode='threading', cors_allowed_origins="*", max_http_buffer_size=15 * 1024 * 1024)

logging.info("Booting APEX Core...")
engine = ApexEngine()

user_requests = {}
MAX_MESSAGES_PER_MINUTE = 10

MASTER_ACCESS_CODE = "APEXWEB"

def check_rate_limit(sid):
    current_time = time.time()
    if sid not in user_requests:
        user_requests[sid] = []
    user_requests[sid] = [t for t in user_requests[sid] if current_time - t < 60]
    if len(user_requests[sid]) >= MAX_MESSAGES_PER_MINUTE:
        return False
    user_requests[sid].append(current_time)
    return True

@app.route('/')
def index():
    return render_template('index.html', logged_in=session.get('authenticated', False))

@app.route('/authenticate', methods=['POST'])
def authenticate():
    data = request.get_json()
    if data and data.get('passcode') == MASTER_ACCESS_CODE:
        session['authenticated'] = True
        return jsonify({'success': True})
    return jsonify({'success': False}), 401

@app.route('/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({'success': True})

@socketio.on('connect')
def handle_connect():
    if not session.get('authenticated'):
        disconnect()
        return
    logging.info(f"New authenticated client connected: {request.sid}")

@socketio.on('disconnect')
def handle_disconnect():
    sid = request.sid
    if sid in user_requests:
        del user_requests[sid]

@socketio.on('user_message')
def handle_user_message(data):
    if not session.get('authenticated'):
        disconnect()
        return

    prompt = data.get('command', '').strip()
    file_data = data.get('file_data', None)
    persona = data.get('persona', 'Synthesizer') # Captures the selected persona
    session_id = request.sid
    
    if not prompt and not file_data:
        return

    if not check_rate_limit(session_id):
        socketio.emit('ai_response', {
            'sender': 'APEX', 
            'text': "[SYS_WARNING] Traffic threshold exceeded. Please wait 60 seconds before transmitting again."
        }, to=session_id)
        return
    
    def background_ai_task(user_prompt, incoming_file, user_persona, sid):
        try:
            reply = engine.generate_response(user_prompt, incoming_file, user_persona)
            socketio.emit('ai_response', {'sender': f'APEX [{user_persona}]', 'text': reply}, to=sid)
        except Exception as e:
            socketio.emit('ai_response', {'sender': 'APEX', 'text': f"[SYS_ERROR] Web Gateway Failure: {str(e)}"}, to=sid)

    socketio.start_background_task(background_ai_task, prompt, file_data, persona, session_id)

if __name__ == '__main__':
    logging.info("Starting APEX Cloud Node...")
    socketio.run(app, host='0.0.0.0', port=5000)
