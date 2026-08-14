from flask import Flask, render_template, request, session, jsonify
from flask_socketio import SocketIO, emit, disconnect
import logging
import time
import datetime
from apex_engine import ApexEngine

app = Flask(__name__)
app.config['SECRET_KEY'] = 'apex_super_secret_key_2026'
app.config['MAX_CONTENT_LENGTH'] = 15 * 1024 * 1024 

socketio = SocketIO(app, async_mode='threading', cors_allowed_origins="*", max_http_buffer_size=15 * 1024 * 1024)

logging.info("Booting APEX Core...")
engine = ApexEngine()

user_requests = {}
active_connections = set()
MAX_MESSAGES_PER_MINUTE = 10
BOOT_TIME = datetime.datetime.now()

ADMIN_ACCESS_CODE = "APEXADMIN"

def check_rate_limit(sid):
    current_time = time.time()
    if sid not in user_requests:
        user_requests[sid] = []
    user_requests[sid] = [t for t in user_requests[sid] if current_time - t < 60]
    if len(user_requests[sid]) >= MAX_MESSAGES_PER_MINUTE:
        return False
    user_requests[sid].append(current_time)
    return True

# --- PUBLIC ROUTES ---
@app.route('/')
def index():
    return render_template('index.html')

# --- ADMIN COMMAND CENTER ROUTES ---
@app.route('/admin')
def admin_dashboard():
    return render_template('admin.html', admin_logged_in=session.get('admin_authenticated', False))

@app.route('/admin/authenticate', methods=['POST'])
def admin_authenticate():
    data = request.get_json()
    if data and data.get('passcode') == ADMIN_ACCESS_CODE:
        session['admin_authenticated'] = True
        return jsonify({'success': True})
    return jsonify({'success': False}), 401

@app.route('/admin/stats')
def admin_stats():
    if not session.get('admin_authenticated'):
        return jsonify({'error': 'Unauthorized'}), 401
    
    uptime = str(datetime.datetime.now() - BOOT_TIME).split('.')[0]
    
    return jsonify({
        'api_calls': engine.current_session_calls,
        'api_limit': engine.max_session_calls,
        'active_users': len(active_connections),
        'uptime': uptime
    })

# --- WEBSOCKET LOGIC ---
@socketio.on('connect')
def handle_connect():
    active_connections.add(request.sid)
    logging.info(f"New public client connected: {request.sid}")

@socketio.on('disconnect')
def handle_disconnect():
    sid = request.sid
    if sid in user_requests:
        del user_requests[sid]
    if sid in active_connections:
        active_connections.remove(sid)

@socketio.on('clear_session')
def handle_clear_session():
    # Instantly wipes the sliding memory window for a fresh start
    engine.session_memory = []
    logging.info(f"Session memory wiped by {request.sid}")

@socketio.on('user_message')
def handle_user_message(data):
    prompt = data.get('command', '').strip()
    file_data = data.get('file_data', None)
    persona = data.get('persona', 'Synthesizer')
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
            # Create a unique ID for this specific message stream
            msg_id = str(time.time()).replace('.', '')
            sender_label = f'APEX [{user_persona}]'
            
            # Tell the front-end to create an empty chat bubble
            socketio.emit('ai_response_start', {'sender': sender_label, 'msg_id': msg_id}, to=sid)
            
            # Stream the text chunks as Gemini generates them
            for chunk in engine.generate_response_stream(user_prompt, incoming_file, user_persona):
                socketio.emit('ai_response_chunk', {'msg_id': msg_id, 'chunk': chunk}, to=sid)
                
            # Tell the front-end the stream is done so it can render the math formulas
            socketio.emit('ai_response_done', {'msg_id': msg_id}, to=sid)
            
        except Exception as e:
            socketio.emit('ai_response', {'sender': 'APEX', 'text': f"[SYS_ERROR] Web Gateway Failure: {str(e)}"}, to=sid)

    socketio.start_background_task(background_ai_task, prompt, file_data, persona, session_id)

if __name__ == '__main__':
    logging.info("Starting APEX Cloud Node...")
    socketio.run(app, host='0.0.0.0', port=5000)
