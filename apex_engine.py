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
import PyPDF2
import apex_database

try:
    from ddgs import DDGS
except ImportError:
    try:
        from duckduckgo_search import DDGS
    except ImportError:
        pass

import google.generativeai as genai

CONFIG_FILE = "apex_config.json"

class ApexEngine:
    def __init__(self):
        self.config = self.load_config()
        self.session_memory = apex_database.load_chat_history()
        self.api_key = os.environ.get("GEMINI_API_KEY", self.config.get("gemini_api_key", ""))
        genai.configure(api_key=self.api_key)
        
        self.current_model = "gemini-1.5-flash"
        try:
            for m in genai.list_models():
                if 'flash' in m.name.lower() and 'generateContent' in m.supported_generation_methods:
                    self.current_model = m.name
                    logging.info(f"Auto-selected brain: {self.current_model}")
                    break
        except Exception as e:
            logging.warning(f"Auto-detect failed, using fallback. {e}")

        # --- HARD-LOCKED COMPUTE QUOTA ---
self.max_session_calls = 1500
        self.current_session_calls = 0
        self.guardrail_active = False

        logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
        self.maintenance_interval = 3600
        self.start_autonomous_maintenance()

    def load_config(self):
        default_config = {"gemini_api_key": "Paste_Key_Here", "theme": "Dark", "auto_scout_interval": 12, "max_session_calls": 1500}
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r") as f:
                    user_config = json.load(f)
                    default_config.update(user_config)
            except Exception:
                pass
        return default_config

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
            if not os.path.exists(db_path): return
            if (os.path.getsize(db_path) / (1024 * 1024)) > 5.0:
                conn = sqlite3.connect(db_path)
                conn.execute('VACUUM;').execute('ANALYZE;')
                conn.commit()
                conn.close()
        except Exception as e:
            logging.error(f"Autonomous optimization failed: {e}")

    def check_guardrails(self):
        if self.guardrail_active:
            return False, "[SYS_LOCKDOWN] Maximum compute budget exceeded."
        if self.current_session_calls >= self.max_session_calls:
            self.guardrail_active = True
            return False, "[SYS_LOCKDOWN] API call limit reached."
        return True, "OK"

    def generate_response(self, prompt, file_b64=None, persona="Synthesizer"):
        safe_to_run, lockdown_msg = self.check_guardrails()
        if not safe_to_run: return lockdown_msg
        if not self.api_key or self.api_key == "Paste_Key_Here": return "[SYS_ERROR] Missing Gemini API Key."

        self.current_session_calls += 1

        try:
            recent_memory = self.session_memory[-20:] if len(self.session_memory) > 20 else self.session_memory
            gemini_history = [{"role": "user" if m['role'] == "user" else "model", "parts": [m['content']]} for m in recent_memory]
            
            # --- DYNAMIC PERSONA ROUTING ---
            current_time = datetime.now().strftime('%A, %B %d, %Y at %I:%M %p')
            if persona == "Engineer":
                sys_instruction = f"You are APEX, a Senior Software Engineer. You write clean, modular, and highly optimized code. You adhere strictly to architectural best practices. Current time: {current_time}."
            elif persona == "Academic":
                sys_instruction = f"You are APEX, an Academic Researcher. You provide formal, highly structured, and objective answers. Analyze concepts with logical rigor and cite structural theories where applicable. Current time: {current_time}."
            else:
                sys_instruction = f"You are APEX, an elite 'Interdisciplinary Synthesizer'. Your core directive is to help users identify hidden connections and build novel mental models. Current date and time is {current_time}."

            model = genai.GenerativeModel(self.current_model, system_instruction=sys_instruction)
            
            prompt_parts = [prompt]
            file_tag = ""
            
            if file_b64:
                header, encoded = file_b64.split(',', 1)
                file_data = base64.b64decode(encoded)
                
                if 'application/pdf' in header.lower():
                    pdf_reader = PyPDF2.PdfReader(io.BytesIO(file_data))
                    pdf_text = "".join([page.extract_text() + "\n" for page in pdf_reader.pages])
                    prompt_parts[0] = f"{prompt}\n\n[USER UPLOADED PDF CONTENT]:\n{pdf_text}"
                    file_tag = " [📄 PDF Attached]"
                elif 'image' in header.lower():
                    try:
                        img = Image.open(io.BytesIO(file_data))
                        prompt_parts.append(img)
                        file_tag = " [📎 Image Attached]"
                    except Exception:
                        return "[SYS_ERROR] The uploaded image file is corrupted or unsupported."
                else:
                    return "[SYS_ERROR] File type rejected. APEX currently only accepts Images and PDFs."
                
        except Exception as e:
            return f"[SYS_ERROR] Neural engine instantiation failed: {str(e)}"

        if prompt.lower().startswith("/search "):
            search_query = prompt[8:].strip()
            try:
                raw_results = DDGS().text(search_query, max_results=2, backend="lite")
                live_context = ""
                for r in (list(raw_results) if raw_results else []):
                    try:
                        soup = BeautifulSoup(requests.get(r.get('href', ''), timeout=4).content, 'html.parser')
                        live_context += f"\nDeep Read: {' '.join([p.get_text() for p in soup.find_all('p')[:4]])}\n"
                    except:
                        live_context += f"\nSnippet: {r.get('body', '')}\n"
                response = model.generate_content(f"Answer using live results:\n{live_context}\n\nQUERY: {search_query}")
                reply = response.text
                apex_database.save_chat('user', prompt); apex_database.save_chat('assistant', reply)
                self.session_memory.extend([{'role': 'user', 'content': prompt}, {'role': 'assistant', 'content': reply}])
                return f"[LIVE WEB DATABANK ACCESSED]\n{reply}"
            except Exception as e: return f"[SYS_ERROR] Web connection failed: {str(e)}"

        save_prompt = prompt + file_tag
        apex_database.save_chat('user', save_prompt)
        self.session_memory.append({'role': 'user', 'content': save_prompt})
        gemini_history.append({"role": "user", "parts": prompt_parts})
        
        try:
            response = model.generate_content(gemini_history)
            reply = response.text
            apex_database.save_chat('assistant', reply)
            self.session_memory.append({'role': 'assistant', 'content': reply})
            return reply
        except Exception as e:
            return f"[SYS_ERROR] Backend failure: {str(e)}"
