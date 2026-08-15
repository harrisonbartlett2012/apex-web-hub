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

    # --- VECTOR LIBRARY METHODS ---
    def get_embedding(self, text):
        result = genai.embed_content(model="models/embedding-001", content=text)
        return result['embedding']

    def cosine_similarity(self, v1, v2):
        dot = sum(a*b for a, b in zip(v1, v2))
        norm1 = sum(a*a for a in v1) ** 0.5
        norm2 = sum(b*b for b in v2) ** 0.5
        return dot / (norm1 * norm2) if norm1 and norm2 else 0

    def save_to_library(self, user_id, filename, file_b64):
        header, encoded = file_b64.split(',', 1)
        file_data = base64.b64decode(encoded)
        
        if 'application/pdf' in header.lower():
            pdf_reader = PyPDF2.PdfReader(io.BytesIO(file_data))
            text = "".join([page.extract_text() + "\n" for page in pdf_reader.pages])
            
            # Chunk the text
            chunks = [text[i:i+1000] for i in range(0, len(text), 1000)]
            for chunk in chunks:
                if len(chunk.strip()) > 50:
                    embedding = self.get_embedding(chunk)
                    apex_database.save_library_chunk(user_id, filename, chunk, embedding)
            return True, f"Successfully processed and embedded {len(chunks)} chunks into your Library."
        return False, "Only PDFs are supported for the permanent Library."

    # --- UPDATED GENERATOR (Requires user_id) ---
    def generate_response_stream(self, user_id, prompt, file_b64=None, persona="Synthesizer"):
        safe_to_run, lockdown_msg = self.check_guardrails()
        if not safe_to_run: 
            yield lockdown_msg
            return
        if not self.api_key or self.api_key == "Paste_Key_Here": 
            yield "[SYS_ERROR] Missing Gemini API Key."
            return

        self.current_session_calls += 1

        try:
            session_memory = apex_database.load_chat_history(user_id)
            recent_memory = session_memory[-20:] if len(session_memory) > 20 else session_memory
            gemini_history = [{"role": "user" if m['role'] == "user" else "model", "parts": [m['content']]} for m in recent_memory]
            
            current_time = datetime.now().strftime('%A, %B %d, %Y at %I:%M %p')
            if persona == "Engineer":
                sys_instruction = f"You are APEX, a Senior Software Engineer. You write clean, modular, and highly optimized code. You adhere strictly to architectural best practices. Current time: {current_time}."
            elif persona == "Academic":
                sys_instruction = f"You are APEX, an Academic Researcher. You provide formal, highly structured, and objective answers. Analyze concepts with logical rigor and cite structural theories where applicable. Current time: {current_time}."
            elif persona == "Tutor":
                sys_instruction = f"You are APEX, a Socratic Tutor. Your core directive is to teach, not just tell. NEVER give the final answer to a problem directly. Instead, break the problem down into manageable steps. Ask the user to solve the first step and wait for their response. If they are wrong, gently point out their mistake and let them try again. Praise them when they get it right before moving to the next step. Current time: {current_time}."
            else:
                sys_instruction = f"You are APEX, an elite 'Interdisciplinary Synthesizer'. Your core directive is to help users identify hidden connections and build novel mental models. Current date and time is {current_time}."

            model = genai.GenerativeModel(self.current_model, system_instruction=sys_instruction)
            
            internal_prompt = prompt
            
            if prompt.lower().startswith("/quiz"):
                quiz_topic = prompt[5:].strip()
                if quiz_topic:
                    internal_prompt = f"Generate a challenging 3-question quiz about {quiz_topic}. DO NOT provide the answers yet. Ask the questions clearly using numbered lists."
                else:
                    internal_prompt = "Generate a challenging 3-question quiz based on the document I just uploaded or our current topic. DO NOT provide the answers yet. Ask the questions clearly using numbered lists."

            # RAG VECTOR SEARCH
            if not file_b64 and not prompt.lower().startswith("/search"):
                try:
                    query_emb = self.get_embedding(internal_prompt)
                    docs = apex_database.get_library_embeddings(user_id)
                    if docs:
                        scored = [(doc[0], self.cosine_similarity(query_emb, doc[1])) for doc in docs]
                        scored.sort(key=lambda x: x[1], reverse=True)
                        best_chunks = [s[0] for s in scored[:2] if s[1] > 0.5]
                        
                        if best_chunks:
                            context = "\n\n---\n\n".join(best_chunks)
                            internal_prompt = f"Use the following excerpts from my permanent Library to help formulate your response. If it's not relevant, ignore it.\n\n[LIBRARY EXCERPTS]:\n{context}\n\n[MY PROMPT]: {internal_prompt}"
                except Exception as e:
                    logging.warning(f"Vector search failed: {e}")

            prompt_parts = [internal_prompt]
            file_tag = ""
            
            if file_b64:
                header, encoded = file_b64.split(',', 1)
                file_data = base64.b64decode(encoded)
                
                if 'application/pdf' in header.lower():
                    pdf_reader = PyPDF2.PdfReader(io.BytesIO(file_data))
                    if len(pdf_reader.pages) > 10:
                        yield "[SYS_ERROR] Document rejected. Limit is 10 pages."
                        return
                    pdf_text = "".join([page.extract_text() + "\n" for page in pdf_reader.pages])
                    prompt_parts[0] = f"{internal_prompt}\n\n[USER UPLOADED PDF CONTENT]:\n{pdf_text}"
                    file_tag = " [📄 PDF Attached]"
                    
                elif 'image' in header.lower():
                    try:
                        img = Image.open(io.BytesIO(file_data))
                        if img.mode in ('RGBA', 'P'):
                            img = img.convert('RGB')
                        img.thumbnail((2000, 2000))
                        prompt_parts.append(img)
                        file_tag = " [📎 Image Attached]"
                    except Exception:
                        yield "[SYS_ERROR] The uploaded image file is corrupted or unsupported."
                        return
                else:
                    yield "[SYS_ERROR] File type rejected."
                    return
                
        except Exception as e:
            yield f"[SYS_ERROR] Neural engine instantiation failed: {str(e)}"
            return

        save_prompt = prompt + file_tag

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
                
                yield "[LIVE WEB DATABANK ACCESSED]\n\n"
                
                search_response = model.generate_content(f"Answer using live results:\n{live_context}\n\nQUERY: {search_query}", stream=True)
                
                full_reply = "[LIVE WEB DATABANK ACCESSED]\n\n"
                for chunk in search_response:
                    try:
                        text_chunk = chunk.text
                        if text_chunk:
                            full_reply += text_chunk
                            yield text_chunk
                    except Exception:
                        pass
                        
                apex_database.save_chat(user_id, 'user', save_prompt)
                apex_database.save_chat(user_id, 'assistant', full_reply)
                return
            except Exception as e: 
                yield f"[SYS_ERROR] Web connection failed: {str(e)}"
                return

        apex_database.save_chat(user_id, 'user', save_prompt)
        gemini_history.append({"role": "user", "parts": prompt_parts})
        
        try:
            response = model.generate_content(gemini_history, stream=True)
            full_reply = ""
            for chunk in response:
                try:
                    text_chunk = chunk.text
                    if text_chunk:
                        full_reply += text_chunk
                        yield text_chunk
                except Exception:
                    pass
            
            apex_database.save_chat(user_id, 'assistant', full_reply)
        except Exception as e:
            yield f"[SYS_ERROR] Backend failure: {str(e)}"
