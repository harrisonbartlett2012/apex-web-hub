from flask import Flask, render_template, request, session, jsonify, redirect, url_for
from flask_socketio import SocketIO, emit, disconnect
import logging
import time
import datetime
from apex_engine import ApexEngine
import apex_database

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

# --- AUTH ROUTES ---
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        data = request.get_json()
        user_id = apex_database.verify_user(data['username'], data['password'])
        if user_id:
            session['user_id'] = user_id
            session['username'] = data['username']
            return jsonify({'success': True})
        return jsonify({'success': False, 'error': 'Invalid credentials'})
    return render_template('login.html')

@app.route('/register', methods=['POST'])
def register():
    data = request.get_json()
    if len(data['password']) < 6:
        return jsonify({'success': False, 'error': 'Password must be at least 6 characters'})
    if apex_database.create_user(data['username'], data['password']):
        return jsonify({'success': True})
    return jsonify({'success': False, 'error': 'Username already taken'})

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


# --- PUBLIC ROUTES ---
@app.route('/')
def index():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    history = apex_database.load_chat_history(session['user_id'])
    return render_template('index.html', username=session['username'], history=history)

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
    if 'user_id' not in session:
        disconnect()
        return
    active_connections.add(request.sid)
    logging.info(f"User {session['username']} connected via WebSockets.")

@socketio.on('disconnect')
def handle_disconnect():
    sid = request.sid
    if sid in user_requests:
        del user_requests[sid]
    if sid in active_connections:
        active_connections.remove(sid)

@socketio.on('clear_session')
def handle_clear_session():
    if 'user_id' in session:
        apex_database.clear_chat(session['user_id'])
        logging.info(f"Session memory wiped for {session['username']}")

@socketio.on('upload_library')
def handle_library_upload(data):
    if 'user_id' not in session: return
    success, msg = engine.save_to_library(session['user_id'], data['filename'], data['file_data'])
    socketio.emit('library_status', {'msg': msg}, to=request.sid)

@socketio.on('user_message')
def handle_user_message(data):
    if 'user_id' not in session: return
    
    prompt = data.get('command', '').strip()
    file_data = data.get('file_data', None)
    persona = data.get('persona', 'Synthesizer')
    sid = request.sid
    user_id = session['user_id']
    
    if not prompt and not file_data:
        return

    if not check_rate_limit(sid):
        socketio.emit('ai_response', {
            'sender': 'APEX', 
            'text': "[SYS_WARNING] Traffic threshold exceeded. Please wait 60 seconds before transmitting again."
        }, to=sid)
        return
    
    def background_ai_task():
        try:
            msg_id = str(time.time()).replace('.', '')
            sender_label = f'APEX [{persona}]'
            socketio.emit('ai_response_start', {'sender': sender_label, 'msg_id': msg_id}, to=sid)
            
            for chunk in engine.generate_response_stream(user_id, prompt, file_data, persona):
                socketio.emit('ai_response_chunk', {'msg_id': msg_id, 'chunk': chunk}, to=sid)
                
            socketio.emit('ai_response_done', {'msg_id': msg_id}, to=sid)
            
        except Exception as e:
            socketio.emit('ai_response', {'sender': 'APEX', 'text': f"[SYS_ERROR] Web Gateway Failure: {str(e)}"}, to=sid)

    socketio.start_background_task(background_ai_task)

if __name__ == '__main__':
    logging.info("Starting APEX Cloud Node...")
    socketio.run(app, host='0.0.0.0', port=5000)
