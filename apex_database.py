import os
import logging
from datetime import datetime
import json
from werkzeug.security import generate_password_hash, check_password_hash
import psycopg2

def get_connection():
    # Your Neon connection string is hardcoded here for manual testing/deployment
    db_url = os.environ.get('DATABASE_URL', 'postgresql://neondb_owner:npg_cQ9Hox8TgGeb@ep-damp-shape-ax6tshqj-pooler.c-4.us-east-2.aws.neon.tech/neondb?sslmode=require&channel_binding=require')
    return psycopg2.connect(db_url)

def initialize_db():
    conn = get_connection()
    cursor = conn.cursor()
    
    # --- NEW V2 TABLES (PostgreSQL uses SERIAL instead of AUTOINCREMENT) ---
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY, 
            username TEXT UNIQUE, 
            password TEXT
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS library (
            id SERIAL PRIMARY KEY, 
            user_id INTEGER, 
            filename TEXT, 
            chunk_text TEXT, 
            embedding TEXT
        )
    ''')
    
    # --- UPDATED CHAT TABLE ---
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS chat_history (
            id SERIAL PRIMARY KEY,
            user_id INTEGER,
            role TEXT,
            content TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # --- YOUR CUSTOM STOCK TABLE ---
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS stock_predictions (
            id SERIAL PRIMARY KEY,
            ticker TEXT,
            date TEXT,
            price REAL,
            prediction TEXT,
            status TEXT
        )
    ''')
    
    conn.commit()
    cursor.close()
    conn.close()
    logging.info("Cloud PostgreSQL Database Initialized! (V2 + Stocks)")

# --- USER AUTHENTICATION ---
def create_user(username, password):
    conn = get_connection()
    cursor = conn.cursor()
    try:
        # PostgreSQL uses %s for placeholders instead of ?
        cursor.execute('INSERT INTO users (username, password) VALUES (%s, %s)', (username, generate_password_hash(password)))
        conn.commit()
        return True
    except psycopg2.IntegrityError:
        conn.rollback()
        return False
    finally:
        cursor.close()
        conn.close()

def verify_user(username, password):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT id, password FROM users WHERE username = %s', (username,))
    user = cursor.fetchone()
    cursor.close()
    conn.close()
    if user and check_password_hash(user[1], password):
        return user[0]
    return None

# --- UPDATED CHAT FUNCTIONS ---
def save_chat(user_id, role, content):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('INSERT INTO chat_history (user_id, role, content) VALUES (%s, %s, %s)', (user_id, role, content))
    conn.commit()
    cursor.close()
    conn.close()

def load_chat_history(user_id, limit=50):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT role, content FROM chat_history WHERE user_id = %s ORDER BY id ASC LIMIT %s', (user_id, limit))
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return [{"role": row[0], "content": row[1]} for row in rows]

def clear_chat(user_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM chat_history WHERE user_id = %s', (user_id,))
    conn.commit()
    cursor.close()
    conn.close()

# --- PERMANENT LIBRARY FUNCTIONS ---
def save_library_chunk(user_id, filename, chunk_text, embedding):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('INSERT INTO library (user_id, filename, chunk_text, embedding) VALUES (%s, %s, %s, %s)', (user_id, filename, chunk_text, json.dumps(embedding)))
    conn.commit()
    cursor.close()
    conn.close()

def get_library_embeddings(user_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT chunk_text, embedding FROM library WHERE user_id = %s', (user_id,))
    rows = [(row[0], json.loads(row[1])) for row in cursor.fetchall()]
    cursor.close()
    conn.close()
    return rows

# --- YOUR CUSTOM STOCK FUNCTIONS ---
def get_stock_stats(ticker):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT count(*) FROM stock_predictions WHERE ticker = %s AND status = 'Correct'", (ticker,))
    correct = cursor.fetchone()[0]
    cursor.execute("SELECT count(*) FROM stock_predictions WHERE ticker = %s AND status = 'Wrong'", (ticker,))
    wrong = cursor.fetchone()[0]
    cursor.close()
    conn.close()
    return correct, wrong

def update_pending_predictions(ticker, current_price, current_time_slot):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT id, price, prediction FROM stock_predictions 
        WHERE ticker = %s AND status = 'Pending' AND date != %s
    ''', (ticker, current_time_slot))
    
    pending_records = cursor.fetchall()
    for record in pending_records:
        rec_id, price_then, pred_dir = record
        actual_went_up = current_price >= price_then
        pred_went_up = "Up" in pred_dir
        new_status = "Correct" if actual_went_up == pred_went_up else "Wrong"
        cursor.execute('UPDATE stock_predictions SET status = %s WHERE id = %s', (new_status, rec_id))
        
    conn.commit()
    cursor.close()
    conn.close()

def log_prediction(ticker, current_time_slot, current_price, simple_pred):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT count(*) FROM stock_predictions WHERE ticker = %s AND date = %s', (ticker, current_time_slot))
    if cursor.fetchone()[0] == 0:
        cursor.execute('''
            INSERT INTO stock_predictions (ticker, date, price, prediction, status) 
            VALUES (%s, %s, %s, %s, 'Pending')
        ''', (ticker, current_time_slot, current_price, simple_pred))
        conn.commit()
    cursor.close()
    conn.close()

# Auto-initialize on import
initialize_db()
