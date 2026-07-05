import os
import json
import logging
import sqlite3
import pandas as pd
from fpdf import FPDF
import subprocess
import sys
import ast
import re
import time
import threading
from datetime import datetime
import requests
from bs4 import BeautifulSoup
import base64
import io
from PIL import Image
import apex_database

# Web Scraper Library
try:
    from ddgs import DDGS
except ImportError:
    try:
        from duckduckgo_search import DDGS # Fallback
    except ImportError:
        pass

# The Cloud Brain Connection
import google.generativeai as genai

CONFIG_FILE = "apex_config.json"

class ApexEngine:
    def __init__(self):
        self.config = self.load_config()
        self.session_memory = apex_database.load_chat_history()
        
        # Pulls the API key securely from Render Environment Variables
        self.api_key = os.environ.get("GEMINI_API_KEY", self.config.get("gemini_api_key", ""))
        genai.configure(api_key=self.api_key)
        self.current_model = "gemini-1.5-flash"

        self.max_session_calls = self.config.get("max_session_calls", 1500)
        self.current_session_calls = 0
        self.guardrail_active = False

        logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
        
        self.maintenance_interval = 3600
        self.start_autonomous_maintenance()

    def load_config(self):
        default_config = {
            "gemini_api_key": "Paste_Key_Here",
            "theme": "Dark",
            "auto_scout_interval": 12,
            "max_session_calls": 1500
        }
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r") as f:
                    user_config = json.load(f)
                    default_config.update(user_config)
            except Exception:
                pass
        return default_config

    def save_config(self, new_settings):
        self.config.update(new_settings)
        try:
            with open(CONFIG_FILE, "w") as f:
                json.dump(self.config, f, indent=4)
            return True
        except Exception:
            return False

    def start_autonomous_maintenance(self):
        def maintenance_worker():
            while True:
                time.sleep(self.maintenance_interval)
                self.optimize_internal_systems()
                
        t = threading.Thread(target=maintenance_worker, daemon=True)
        t.start()

    def optimize_internal_systems(self):
        try:
            db_path = 'apex_core.db'
            if not os.path.exists(db_path):
                return
            file_size_mb = os.path.getsize(db_path) / (1024 * 1024)
            if file_size_mb > 5.0:
                conn = sqlite3.connect(db_path)
                cursor = conn.cursor()
                cursor.execute('VACUUM;')
                cursor.execute('ANALYZE;')
                conn.commit()
                conn.close()
        except Exception as e:
            logging.error(f"Autonomous optimization failed: {e}")

    def check_guardrails(self):
        if self.guardrail_active:
            return False, "[SYS_LOCKDOWN] Maximum compute budget exceeded. System locked to prevent token runoff. Restart APEX to clear."
        if self.current_session_calls >= self.max_session_calls:
            self.guardrail_active = True
            return False, f"[SYS_LOCKDOWN] API call limit ({self.max_session_calls}) reached. Hard kill-switch activated."
        return True, "OK"

    def run_diagnostics(self):
        db_status = "ONLINE" if os.path.exists("apex_core.db") else "OFFLINE"
        neural_status = "ONLINE" if self.api_key else "OFFLINE // MISSING API KEY"
        
        return {
            "master_status": "ONLINE" if neural_status == "ONLINE" else "DEGRADED",
            "database": db_status,
            "neural_link": neural_status,
            "current_model": self.current_model
        }

    def generate_response(self, prompt, image_b64=None):
        safe_to_run, lockdown_msg = self.check_guardrails()
        if not safe_to_run:
            return lockdown_msg

        if not self.api_key or self.api_key == "Paste_Key_Here":
            return "[SYS_ERROR] Missing Gemini API Key. Please add it to the Render Environment Variables."

        self.current_session_calls += 1

        try:
            gemini_history = []
            for msg in self.session_memory:
                role = "user" if msg['role'] == "user" else "model"
                gemini_history.append({"role": role, "parts": [msg['content']]})
            
            current_time = datetime.now().strftime("%A, %B %d, %Y at %I:%M %p")
            sys_instruction = f"You are APEX, an elite 'Interdisciplinary Synthesizer' and Mental Model Architect. Your core directive is to help users identify hidden connections, build novel mental models, and synthesize insights across multiple disparate domains (like biology, economics, philosophy, and engineering). Do not just provide generic facts; actively act as a Synthesizer Coach to challenge assumptions, generate powerful cross-domain analogies, and build complex frameworks. The current date and time is {current_time}."
            
            model = genai.GenerativeModel(self.current_model, system_instruction=sys_instruction)
            
            # --- VISION PROCESSING MODULE ---
            prompt_parts = [prompt]
            if image_b64:
                if ',' in image_b64:
                    image_b64 = image_b64.split(',')[1]
                img_data = base64.b64decode(image_b64)
                img = Image.open(io.BytesIO(img_data))
                prompt_parts.append(img)
                
        except Exception as e:
            return f"[SYS_ERROR] Neural engine instantiation failed: {str(e)}"

        # Web Search Module with Deep BeautifulSoup4 Web-Scraping
        if prompt.lower().startswith("/search "):
            search_query = prompt[8:].strip()
            try:
                raw_results = DDGS().text(search_query, max_results=2, backend="lite")
                results = list(raw_results) if raw_results else []
                
                if not results:
                    return "[SYS_ERROR] Web search returned empty. Request blocked."
                
                live_context = ""
                for r in results:
                    url = r.get('href', '')
                    live_context += f"\nSource: {r.get('title', 'Unknown')}\n"
                    try:
                        page = requests.get(url, timeout=4)
                        soup = BeautifulSoup(page.content, 'html.parser')
                        paragraphs = soup.find_all('p')
                        full_text = " ".join([p.get_text() for p in paragraphs[:4]])
                        live_context += f"Deep Read Data: {full_text}\n"
                    except Exception:
                        live_context += f"Snippet Data: {r.get('body', '')}\n"

                system_prompt = f"Answer the user's query using ONLY the following live internet search results. Synthesize the findings.\n\nLIVE DATA:\n{live_context}\n\nUSER QUERY: {search_query}"
                
                response = model.generate_content(system_prompt)
                reply = response.text
                
                apex_database.save_chat('user', prompt)
                apex_database.save_chat('assistant', reply)
                self.session_memory.append({'role': 'user', 'content': prompt})
                self.session_memory.append({'role': 'assistant', 'content': reply})
                
                return f"[LIVE WEB DATABANK ACCESSED]\n{reply}"
            except Exception as e:
                return f"[SYS_ERROR] Live connection failed: {str(e)}"

        # Standard Conversation Module
        save_prompt = prompt + " [Image Attached]" if image_b64 else prompt
        apex_database.save_chat('user', save_prompt)
        self.session_memory.append({'role': 'user', 'content': save_prompt})
        
        gemini_history.append({"role": "user", "parts": prompt_parts})
        
        try:
            max_retries = 2
            for attempt in range(max_retries):
                response = model.generate_content(gemini_history)
                reply = response.text
                
                code_blocks = re.findall(r'```python\n(.*?)\n```', reply, re.DOTALL)
                syntax_error = None
                
                for code in code_blocks:
                    try:
                        ast.parse(code)
                    except SyntaxError as e:
                        syntax_error = f"SyntaxError on line {e.lineno}: {e.msg}"
                        break
                
                if syntax_error and attempt < max_retries - 1:
                    correction_prompt = f"[SYS_INTERNAL] Your previous code failed the AST syntax check with: {syntax_error}. Rewrite the code to fix this error."
                    gemini_history.append({"role": "model", "parts": [reply]})
                    gemini_history.append({"role": "user", "parts": [correction_prompt]})
                    continue 
                elif syntax_error:
                    reply += f"\n\n[SYS_WARNING] Internal Linter failed to resolve syntax error: {syntax_error}"
                    break
                else:
                    if code_blocks:
                        reply += "\n\n[SYS_LINTER] Code passed internal AST syntax verification."
                    break

            apex_database.save_chat('assistant', reply)
            self.session_memory.append({'role': 'assistant', 'content': reply})
            return reply

        except Exception as e:
            return f"[SYS_ERROR] Backend failure: {str(e)}"
