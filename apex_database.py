import sqlite3
import os
import logging
from datetime import datetime
import json
from werkzeug.security import generate_password_hash, check_password_hash

DB_FILE = "apex_core.db"

def get_connection():
    return sqlite3.connect(DB_FILE)

def initialize_db():
    conn = get_connection()
    cursor = conn.cursor()
    
    # --- NEW V2 TABLES ---
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT, 
            username TEXT UNIQUE, 
            password TEXT
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS library (
            id INTEGER PRIMARY KEY AUTOINCREMENT, 
            user_id INTEGER, 
            filename TEXT, 
            chunk_text TEXT, 
            embedding TEXT
        )
    ''')
    
    # --- UPDATED CHAT TABLE (Added user_id) ---
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS chat_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            role TEXT,
            content TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # --- YOUR CUSTOM STOCK TABLE ---
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS stock_predictions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT,
            date TEXT,
            price REAL,
            prediction TEXT,
            status TEXT
        )
    ''')
    
    conn.commit()
    conn.close()
    logging.info("SQLite Database Initialized: apex_core.db (V2 + Stocks)")

# --- USER AUTHENTICATION ---
def create_user(username, password):
    conn = get_connection()
    try:
        conn.execute('INSERT INTO users (username, password) VALUES (?, ?)', (username, generate_password_hash(password)))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()

def verify_user(username, password):
    conn = get_connection()
    cursor = conn.execute('SELECT id, password FROM users WHERE username = ?', (username,))
    user = cursor.fetchone()
    conn.close()
    if user and check_password_hash(user[1], password):
        return user[0]
    return None

# --- UPDATED CHAT FUNCTIONS ---
def save_chat(user_id, role, content):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('INSERT INTO chat_history (user_id, role, content) VALUES (?, ?, ?)', (user_id, role, content))
    conn.commit()
    conn.close()

def load_chat_history(user_id, limit=50):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT role, content FROM chat_history WHERE user_id = ? ORDER BY id ASC LIMIT ?', (user_id, limit))
    rows = cursor.fetchall()
    conn.close()
    return [{"role": row[0], "content": row[1]} for row in rows]

def clear_chat(user_id):
    conn = get_connection()
    conn.execute('DELETE FROM chat_history WHERE user_id = ?', (user_id,))
    conn.commit()
    conn.close()

# --- PERMANENT LIBRARY FUNCTIONS ---
def save_library_chunk(user_id, filename, chunk_text, embedding):
    conn = get_connection()
    conn.execute('INSERT INTO library (user_id, filename, chunk_text, embedding) VALUES (?, ?, ?, ?)', (user_id, filename, chunk_text, json.dumps(embedding)))
    conn.commit()
    conn.close()

def get_library_embeddings(user_id):
    conn = get_connection()
    cursor = conn.execute('SELECT chunk_text, embedding FROM library WHERE user_id = ?', (user_id,))
    rows = [(row[0], json.loads(row[1])) for row in cursor.fetchall()]
    conn.close()
    return rows

# --- YOUR CUSTOM STOCK FUNCTIONS ---
def get_stock_stats(ticker):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT count(*) FROM stock_predictions WHERE ticker = ? AND status = "Correct"', (ticker,))
    correct = cursor.fetchone()[0]
    cursor.execute('SELECT count(*) FROM stock_predictions WHERE ticker = ? AND status = "Wrong"', (ticker,))
    wrong = cursor.fetchone()[0]
    conn.close()
    return correct, wrong

def update_pending_predictions(ticker, current_price, current_time_slot):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT id, price, prediction FROM stock_predictions 
        WHERE ticker = ? AND status = "Pending" AND date != ?
    ''', (ticker, current_time_slot))
    
    pending_records = cursor.fetchall()
    for record in pending_records:
        rec_id, price_then, pred_dir = record
        actual_went_up = current_price >= price_then
        pred_went_up = "Up" in pred_dir
        new_status = "Correct" if actual_went_up == pred_went_up else "Wrong"
        cursor.execute('UPDATE stock_predictions SET status = ? WHERE id = ?', (new_status, rec_id))
        
    conn.commit()
    conn.close()

def log_prediction(ticker, current_time_slot, current_price, simple_pred):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT count(*) FROM stock_predictions WHERE ticker = ? AND date = ?', (ticker, current_time_slot))
    if cursor.fetchone()[0] == 0:
        cursor.execute('''
            INSERT INTO stock_predictions (ticker, date, price, prediction, status) 
            VALUES (?, ?, ?, ?, "Pending")
        ''', (ticker, current_time_slot, current_price, simple_pred))
        conn.commit()
    conn.close()

# Auto-initialize on import
initialize_db()
