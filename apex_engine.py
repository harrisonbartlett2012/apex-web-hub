import os
import json
import logging
import asyncio
import urllib.request
import sqlite3
import pandas as pd
from fpdf import FPDF
import subprocess
import sys
import ast
import re
import time
import threading
import apex_database
import finance_agent  
import predictor

# STAGE 3.1: Web Scraper Library (UPDATED TO ddgs)
try:
    from ddgs import DDGS
except ImportError:
    try:
        from duckduckgo_search import DDGS # Fallback
    except ImportError:
        pass

try:
    from ollama import AsyncClient, ResponseError
except ImportError:
    pass

CONFIG_FILE = "apex_config.json"

class ApexEngine:
    def __init__(self):
        self.config = self.load_config()
        self.session_memory = apex_database.load_chat_history()
        self.ollama_host = self.config.get("ollama_host", "http://localhost:11434")
        self.current_model = self.config.get("default_model", "qwen2:0.5b")

        # STAGE 6.2: Deterministic Guardrails
        self.max_session_calls = self.config.get("max_session_calls", 50)
        self.current_session_calls = 0
        self.guardrail_active = False

        logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
        
        # STAGE 6.3: Agentic Self-Tooling & Optimization
        self.maintenance_interval = 3600  # Checks its own health every 1 hour
        self.start_autonomous_maintenance()

    def load_config(self):
        default_config = {
            "gemini_api_key": "Paste_Key_Here",
            "theme": "Dark",
            "auto_scout_interval": 12,
            "ollama_host": "http://localhost:11434",
            "default_model": "qwen2:0.5b",
            "max_session_calls": 50
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

    # ==========================================
    # STAGE 6.3: AUTONOMOUS MAINTENANCE LOOP
    # ==========================================
    def start_autonomous_maintenance(self):
        def maintenance_worker():
            while True:
                time.sleep(self.maintenance_interval)
                self.optimize_internal_systems()
                
        t = threading.Thread(target=maintenance_worker, daemon=True)
        t.start()
        logging.info("Autonomous Self-Tooling loop initialized.")

    def optimize_internal_systems(self):
        try:
            db_path = 'apex_core.db'
            if not os.path.exists(db_path):
                return
                
            file_size_mb = os.path.getsize(db_path) / (1024 * 1024)
            
            if file_size_mb > 5.0:
                logging.info(f"Database size at {file_size_mb:.2f}MB. Initiating autonomous defragmentation (VACUUM)...")
                conn = sqlite3.connect(db_path)
                cursor = conn.cursor()
                cursor.execute('VACUUM;')
                cursor.execute('ANALYZE;')
                conn.commit()
                conn.close()
                logging.info("System optimization complete. Bottlenecks cleared.")
        except Exception as e:
            logging.error(f"Autonomous optimization failed: {e}")

    # ==========================================
    # STAGE 6.2: GUARDRAIL LOGIC
    # ==========================================
    def check_guardrails(self):
        if self.guardrail_active:
            return False, "[SYS_LOCKDOWN] Maximum compute budget exceeded. System locked to prevent token runoff. Restart APEX to clear."
        
        if self.current_session_calls >= self.max_session_calls:
            self.guardrail_active = True
            logging.warning("HARD KILL-SWITCH ACTIVATED: Compute budget exhausted.")
            return False, f"[SYS_LOCKDOWN] API call limit ({self.max_session_calls}) reached. Hard kill-switch activated."
        
        return True, "OK"

    def run_diagnostics(self):
        db_status = "ONLINE" if os.path.exists("apex_core.db") else "OFFLINE"
        
        try:
            urllib.request.urlopen(self.ollama_host, timeout=2.0)
            neural_status = "ONLINE"
        except Exception:
            neural_status = "OFFLINE"

        modules_to_test = {
            "finance_agent": "import finance_agent; print('OK')",
            "predictor": "import predictor; print('OK')"
        }
        
        module_status = {}
        for mod_name, command in modules_to_test.items():
            try:
                result = subprocess.run(
                    [sys.executable, "-c", command],
                    capture_output=True, text=True, timeout=5.0
                )
                if result.returncode == 0 and "OK" in result.stdout:
                    module_status[mod_name] = "ONLINE"
                else:
                    error_msg = result.stderr.strip().split('\n')[-1]
                    module_status[mod_name] = f"ERROR: {error_msg}"
            except subprocess.TimeoutExpired:
                module_status[mod_name] = "TIMEOUT"
            except Exception as e:
                module_status[mod_name] = f"FAILED: {str(e)}"

        all_online = (
            db_status == "ONLINE" and 
            neural_status == "ONLINE" and 
            module_status.get("finance_agent") == "ONLINE" and 
            module_status.get("predictor") == "ONLINE"
        )
        system_state = "ONLINE" if all_online else "DEGRADED // ISSUES DETECTED"

        return {
            "master_status": system_state,
            "database": db_status,
            "neural_link": neural_status,
            "finance_agent": module_status.get("finance_agent"),
            "predictor": module_status.get("predictor"),
            "current_model": self.current_model
        }

    def export_telemetry_report(self):
        try:
            conn = sqlite3.connect('apex_core.db')
            df_stocks = pd.read_sql_query("SELECT * FROM stock_predictions", conn)
            
            current_dir = os.path.dirname(os.path.abspath(__file__))
            csv_path = os.path.join(current_dir, "APEX_Stock_Data.csv")
            df_stocks.to_csv(csv_path, index=False)
            
            correct = len(df_stocks[df_stocks['status'] == 'Correct']) if 'status' in df_stocks.columns else 0
            wrong = len(df_stocks[df_stocks['status'] == 'Wrong']) if 'status' in df_stocks.columns else 0
            total = correct + wrong
            accuracy = round((correct / total) * 100, 1) if total > 0 else 0.0

            pdf = FPDF()
            pdf.add_page()
            pdf.set_font("Courier", size=16, style='B')
            pdf.cell(200, 10, txt="APEX // NEURAL TELEMETRY REPORT", ln=1, align='C')
            pdf.cell(200, 10, txt="---------------------------------", ln=1, align='C')
            
            pdf.set_font("Courier", size=12)
            pdf.ln(10)
            pdf.cell(200, 10, txt=f"Total Predictions Logged: {len(df_stocks)}", ln=1)
            pdf.cell(200, 10, txt=f"Successful Strikes: {correct}", ln=1)
            pdf.cell(200, 10, txt=f"Missed Strikes: {wrong}", ln=1)
            pdf.cell(200, 10, txt=f"Overall Engine Accuracy: {accuracy}%", ln=1)
            
            pdf_path = os.path.join(current_dir, "APEX_Telemetry_Report.pdf")
            pdf.output(pdf_path)
            conn.close()
            
            return {"success": True, "csv": csv_path, "pdf": pdf_path}
        except Exception as e:
            logging.error(f"Export Error: {e}")
            return {"success": False, "error": str(e)}

    async def generate_response(self, prompt):
        safe_to_run, lockdown_msg = self.check_guardrails()
        if not safe_to_run:
            return lockdown_msg

        self.current_session_calls += 1

        try:
            client = AsyncClient(host=self.ollama_host)
        except Exception:
            return "[SYS_ERROR] Neural engine disconnected."

        if prompt.lower().startswith("/search "):
            search_query = prompt[8:].strip()
            try:
                raw_results = DDGS().text(search_query, max_results=3, backend="lite")
                results = list(raw_results) if raw_results else []
                
                if not results:
                    return "[SYS_ERROR] Web search returned empty. DuckDuckGo blocked the request."
                
                live_context = "\n".join([f"Source: {r.get('title', 'Unknown')}\nData: {r.get('body', '')}" for r in results])
                system_prompt = f"Answer the user's query using ONLY the following live internet search results. Be concise.\n\nLIVE DATA:\n{live_context}"
                
                temp_memory = self.session_memory.copy()
                temp_memory.append({'role': 'system', 'content': system_prompt})
                temp_memory.append({'role': 'user', 'content': search_query})
                
                response = await asyncio.wait_for(client.chat(model=self.current_model, messages=temp_memory), timeout=45.0)
                reply = response['message']['content']
                
                apex_database.save_chat('user', prompt)
                apex_database.save_chat('assistant', reply)
                self.session_memory.append({'role': 'user', 'content': prompt})
                self.session_memory.append({'role': 'assistant', 'content': reply})
                
                return f"[LIVE WEB DATABANK ACCESSED]\n{reply}"
            
            except Exception as e:
                return f"[SYS_ERROR] Live connection failed: {str(e)}"

        apex_database.save_chat('user', prompt)
        self.session_memory.append({'role': 'user', 'content': prompt})
        
        try:
            max_retries = 2
            for attempt in range(max_retries):
                response = await asyncio.wait_for(client.chat(model=self.current_model, messages=self.session_memory), timeout=30.0)
                reply = response['message']['content']
                
                # FIXED LINE HERE:
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
                    self.session_memory.append({'role': 'assistant', 'content': reply})
                    self.session_memory.append({'role': 'user', 'content': correction_prompt})
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

        except asyncio.TimeoutError:
            return "[SYS_ERROR] Neural execution timed out."
        except Exception as e:
            return f"[SYS_ERROR] Backend failure: {str(e)}"

    def run_market_math(self, ticker, horizon=4):
        try:
            analysis = finance_agent.analyze_stock(ticker)
            forecast = predictor.forecast_price(ticker, analysis['history'], hours_ahead=horizon)
            return {"success": True, "analysis": analysis, "forecast": forecast}
        except Exception as e:
            return {"success": False, "error": f"Network/Data Error: {str(e)}"}