import os
import json
import logging
import sqlite3
import pandas as pd
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
from urllib.parse import urlparse, parse_qs
import apex_database

try:
    from youtube_transcript_api import YouTubeTranscriptApi
except ImportError:
    pass

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

    def load_config(self):
        default_config = {"gemini_api_key": "Paste_Key_Here", "max_session_calls": 1500}
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r") as f:
                    default_config.update(json.load(f))
            except Exception:
                pass
        return default_config

    def check_guardrails(self):
        if self.guardrail_active:
            return False, "[SYS_LOCKDOWN] Maximum compute budget exceeded."
        if self.current_session_calls >= self.max_session_calls:
            self.guardrail_active = True
            return False, "[SYS_LOCKDOWN] API call limit reached."
        return True, "OK"

    # --- VECTOR LIBRARY LOGIC ---
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
            chunks = [text[i:i+1000] for i in range(0, len(text), 1000)]
            for chunk in chunks:
                if len(chunk.strip()) > 50:
                    embedding = self.get_embedding(chunk)
                    apex_database.save_library_chunk(user_id, filename, chunk, embedding)
            return True, f"Successfully embedded {len(chunks)} chunks into your Library."
        return False, "Only PDFs are supported for the permanent Library."

    # --- YOUTUBE LOGIC ---
    def extract_youtube_transcript(self, url):
        try:
            if "youtu.be" in url:
                video_id = url.split("/")[-1].split("?")[0]
            else:
                video_id = parse_qs(urlparse(url).query).get('v', [None])[0]
            
            if not video_id: return None
            
            transcript_list = YouTubeTranscriptApi.get_transcript(video_id)
            full_text = " ".join([t['text'] for t in transcript_list])
            return full_text
        except Exception as e:
            logging.error(f"YouTube Extract Failed: {e}")
            return None

    # --- CORE STREAMING LOGIC ---
    def generate_response_stream(self, user_id, prompt, file_b64=None, persona="Synthesizer"):
        safe_to_run, lockdown_msg = self.check_guardrails()
        if not safe_to_run: 
            yield lockdown_msg
            return
        if not self.api_key or self.api_key == "Paste_Key_Here": 
            yield "[SYS_ERROR] Missing Gemini API Key."
            return

        self.current_session_calls += 1
        session_memory = apex_database.load_chat_history(user_id)
        recent_memory = session_memory[-20:] if len(session_memory) > 20 else session_memory
        gemini_history = [{"role": "user" if m['role'] == "user" else "model", "parts": [m['content']]} for m in recent_memory]
        
        current_time = datetime.now().strftime('%A, %B %d, %Y at %I:%M %p')
        personas = {
            "Synthesizer": f"You are APEX, an elite Interdisciplinary Synthesizer. Current time: {current_time}.",
            "Engineer": f"You are APEX, a Senior Software Engineer. Current time: {current_time}.",
            "Academic": f"You are APEX, an Academic Researcher. Current time: {current_time}.",
            "Tutor": f"You are APEX, a Socratic Tutor. Never give final answers directly. Teach step by step. Current time: {current_time}."
        }
        model = genai.GenerativeModel(self.current_model, system_instruction=personas.get(persona, personas["Synthesizer"]))
        
        internal_prompt = prompt
        file_tag = ""
        
        # 1. YOUTUBE INTERCEPTOR
        yt_match = re.search(r'(https?://)?(www\.)?(youtube\.com/watch\?v=|youtu\.be/)[^\s]+', prompt)
        if yt_match:
            yt_url = yt_match.group(0)
            yield f"[📡 YouTube Video Detected. Ripping Transcript... ]\n\n"
            transcript = self.extract_youtube_transcript(yt_url)
            if transcript:
                internal_prompt += f"\n\n[YOUTUBE TRANSCRIPT]:\n{transcript[:100000]}" # Limit to 100k chars for safety
                yield f"[✅ Transcript Extracted Successfully.]\n\n"
            else:
                yield f"[❌ Failed to extract transcript. Video may be private or lack captions.]\n\n"

        # 2. SLASH COMMAND INTERCEPTORS
        if prompt.lower().startswith("/quiz"):
            topic = prompt[5:].strip()
            internal_prompt = f"Generate a challenging 3-question quiz about {topic if topic else 'the current topic'}. DO NOT provide the answers yet. Use numbered lists."
        
        elif prompt.lower().startswith("/flashcards"):
            topic = prompt[12:].strip()
            internal_prompt = f"Generate exactly 15 high-quality flashcards about {topic if topic else 'the current topic'}. Format them STRICTLY as 'Term | Definition' separated by line breaks. Put the entire list inside ONE Markdown code block so I can copy and paste it directly into Quizlet/Anki."
        
        elif prompt.lower().startswith("/studyguide"):
            topic = prompt[12:].strip()
            internal_prompt = f"Create a highly structured, comprehensive Study Guide about {topic if topic else 'the current topic'}. Use clear Markdown headings (##), bullet points, bold key terms, and summary sections. This will be exported as a PDF."

        # 3. VECTOR SEARCH
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
                        internal_prompt = f"Use the following excerpts from my permanent Library to help formulate your response:\n{context}\n\n[PROMPT]: {internal_prompt}"
            except Exception as e:
                pass

        prompt_parts = [internal_prompt]
        
        # FILE HANDLING
        if file_b64:
            header, encoded = file_b64.split(',', 1)
            file_data = base64.b64decode(encoded)
            if 'application/pdf' in header.lower():
                pdf_reader = PyPDF2.PdfReader(io.BytesIO(file_data))
                pdf_text = "".join([page.extract_text() + "\n" for page in pdf_reader.pages])
                prompt_parts[0] = f"{internal_prompt}\n\n[UPLOADED PDF]:\n{pdf_text}"
                file_tag = " [📄 Session PDF Attached]"
            elif 'image' in header.lower():
                img = Image.open(io.BytesIO(file_data)).convert('RGB')
                img.thumbnail((2000, 2000))
                prompt_parts.append(img)
                file_tag = " [📎 Image Attached]"

        save_prompt = prompt + file_tag

        # 4. WEB SEARCH INTERCEPTOR
        if prompt.lower().startswith("/search "):
            search_query = prompt[8:].strip()
            try:
                raw_results = DDGS().text(search_query, max_results=2, backend="lite")
                live_context = "\n".join([r.get('body', '') for r in (list(raw_results) if raw_results else [])])
                yield "[LIVE WEB DATABANK ACCESSED]\n\n"
                search_res = model.generate_content(f"Answer using live results:\n{live_context}\n\nQUERY: {search_query}", stream=True)
                full_reply = "[LIVE WEB DATABANK ACCESSED]\n\n"
                for chunk in search_res:
                    if chunk.text:
                        full_reply += chunk.text
                        yield chunk.text
                apex_database.save_chat(user_id, 'user', save_prompt)
                apex_database.save_chat(user_id, 'assistant', full_reply)
                return
            except Exception as e: 
                yield f"[SYS_ERROR] Web search failed: {str(e)}"
                return

        apex_database.save_chat(user_id, 'user', save_prompt)
        gemini_history.append({"role": "user", "parts": prompt_parts})
        
        try:
            response = model.generate_content(gemini_history, stream=True)
            full_reply = ""
            for chunk in response:
                if chunk.text:
                    full_reply += chunk.text
                    yield chunk.text
            apex_database.save_chat(user_id, 'assistant', full_reply)
        except Exception as e:
            yield f"[SYS_ERROR] Backend failure: {str(e)}"
