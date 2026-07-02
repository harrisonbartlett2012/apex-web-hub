import sqlite3
import os
import logging
from datetime import datetime

DB_FILE = "apex_core.db"

def get_connection():
    return sqlite3.connect(DB_FILE)

def initialize_db():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS chat_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            role TEXT,
            content TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
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
    logging.info("SQLite Database Initialized: apex_core.db")

def save_chat(role, content):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('INSERT INTO chat_history (role, content) VALUES (?, ?)', (role, content))
    conn.commit()
    conn.close()

def load_chat_history(limit=50):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT role, content FROM chat_history ORDER BY id ASC LIMIT ?', (limit,))
    rows = cursor.fetchall()
    conn.close()
    return [{"role": row[0], "content": row[1]} for row in rows]

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

initialize_db()