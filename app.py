import os
import re
import io
import json
import hmac
import time
import random
import zipfile
import tempfile
import threading
import streamlit as st
import streamlit.components.v1 as components
from google import genai
from google.genai import errors, types

APP_VERSION = "v16"
COOLDOWN_SECONDS = 60
SKIP_WORDS = ("image", "tts", "embed", "live", "audio", "veo",
              "imagen", "robotics", "computer", "aqa")

SAVE_PATH = os.path.join(tempfile.gettempdir(), "nexus_last_project.json")
SPEC_PATH = os.path.join(tempfile.gettempdir(), "nexus_last_spec.txt")
STATE_PATH = os.path.join(tempfile.gettempdir(), "nexus_worker_state.json")

SPEC_CHAIN = ["gemini-3.5-flash-lite", "gemini-3.5-flash", "gemini-3.6-flash"]

FACTORY_SYSTEM = """You are a senior software architect who writes build specifications for an AI coding agent. Turn the user's short idea into ONE complete, copy-paste-ready prompt. Output ONLY the prompt text, with no preamble and no commentary.

The prompt you write must contain:
1. GOAL: the core experience in 2-3 sentences.
2. TECH CONSTRAINTS: Vanilla JavaScript or Three.js from cdnjs.cloudflare.com (pinned version). Modular architecture with clean file separation (index.html, style.css, game.js). No external images, fonts or audio files: draw textures on canvas and synthesize audio with Web Audio API. Touch controls for iPad Safari.
3. MULTI-FILE ARCHITECTURE: Name each file and its exact responsibility.
4. MUST-HAVE vs STRETCH: Core gameplay loops first; stretch features only if safe.
5. PERFORMANCE: Cap pixel ratio at 2, avoid per-frame allocations.
6. ZERO-PLACEHOLDER RULE: No TODOs, no stubs, every file and function fully written.
Be specific and concise."""

BUILDER_SYSTEM = """You are an expert full-stack WebGL and front-end engineer inspired by Bolt.diy.
Build exactly what the specification asks for using clean modular file architecture.

CRITICAL OUTPUT FORMAT RULES:
Wrap your entire project inside a <boltArtifact> tag with individual <boltAction> tags for each file:

<boltArtifact id="project-id" title="Project Name">
<boltAction type="file" filePath="index.html">
<!DOCTYPE html>
<html>
...
<link rel="stylesheet" href="style.css">
<script src="game.js"></script>
...
</html>
</boltAction>
<boltAction type="file" filePath="style.css">
/* Clean modern styles, touch-friendly min 44px tap targets */
</boltAction>
<boltAction type="file" filePath="game.js">
// Complete implementation with zero placeholders
</boltAction>
</boltArtifact>

Rules:
- Output ONLY the <boltArtifact> block. No explanation before or after.
- Zero placeholders: NO `// TODO`, NO `// Implement later`, NO omitted code. Every function must be fully written.
- External libraries: ONLY from cdnjs.cloudflare.com at pinned versions.
- Mobile first: Responsive canvas, touch controls, pixel ratio capped at 2."""

REFINE_SYSTEM = """You are an expert full-stack and WebGL engineer modifying an existing multi-file project.
Apply the requested changes to the CURRENT project files. Keep everything that already works unchanged.

CRITICAL OUTPUT FORMAT RULES:
Output the complete updated project using the <boltArtifact> format, including all project files:

<boltArtifact id="project-id" title="Project Name">
<boltAction type="file" filePath="index.html">...</boltAction>
<boltAction type="file" filePath="style.css">...</boltAction>
<boltAction type="file" filePath="game.js">...</boltAction>
</boltArtifact>

Rules:
- Output the COMPLETE updated files. Never omit sections or use placeholders.
- Trace the data flow carefully to fix root causes rather than stacking temporary patches."""

ERROR_SNIPPET = r"""<script>
(function(){
  var errs=[];
  function show(m){
    errs.push(m);
    var b=document.getElementById('__nexus_err');
    if(!b){
      b=document.createElement('pre');
      b.id='__nexus_err';
      b.style.cssText='position:fixed;left:10px;right:10px;bottom:10px;max-height:35%;overflow:auto;margin:0;padding:12px;background:rgba(20,5,5,0.95);border:1px solid #ff4444;border-radius:8px;color:#ff8888;font:11px monospace;z-index:2147483647;white-space:pre-wrap;-webkit-user-select:text;user-select:text;';
      (document.body||document.documentElement).appendChild(b);
    }
    b.textContent='[NEXUS CONSOLE ERRORS ('+errs.length+')]\n'+errs.join('\n');
  }
  window.addEventListener('error',function(e){
    if(e.target && e.target!==window && (e.target.src||e.target.href)){
      show('FAILED LOAD: '+(e.target.src||e.target.href));
    } else {
      show('EXCEPTION: '+e.message+' @ L'+e.lineno);
    }
  },true);
  window.addEventListener('unhandledrejection',function(e){
    show('PROMISE: '+((e.reason&&e.reason.message)||e.reason));
  });
  var ce=console.error;
  console.error=function(){
    show('console.error: '+Array.prototype.slice.call(arguments).join(' '));
    ce.apply(console,arguments);
  };
})();
</script>"""

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Google+Sans:wght@400;500;700&family=Plus+Jakarta+Sans:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');

html, body, [class*="css"] {
    font-family: 'Google Sans', 'Plus Jakarta Sans', -apple-system, sans-serif !important;
}

.stApp {
    background-color: #0b0c10 !important;
    background-image: 
        radial-gradient(circle at 50% 15%, rgba(45, 55, 110, 0.15) 0%, transparent 60%),
        radial-gradient(circle at 85% 85%, rgba(60, 30, 95, 0.12) 0%, transparent 50%),
        radial-gradient(1px 1px at 20% 30%, rgba(255, 255, 255, 0.3) 1px, transparent 1px),
        radial-gradient(1px 1px at 75% 15%, rgba(255, 255, 255, 0.25) 1px, transparent 1px) !important;
    color: #e3e3e8 !important;
}

[data-testid="stHeader"] {
    background: transparent !important;
    height: 3rem !important;
}

[data-testid="stSidebarCollapseButton"] {
    background: #161720 !important;
    border: 1px solid #282a3d !important;
    border-radius: 8px !important;
    color: #a5b4fc !important;
    box-shadow: 0 0 10px rgba(99, 102, 241, 0.2) !important;
}

footer {visibility: hidden !important;}

.block-container {
    padding-top: 1.5rem !important;
    padding-bottom: 5rem !important;
    max-width: 96% !important;
}

[data-testid="stSidebar"] {
    background-color: #0f1016 !important;
    border-right: 1px solid #1c1d28 !important;
}

.gem-hero {
    text-align: center;
    padding: 2.2rem 1rem 1.6rem 1rem;
}

.gem-greeting {
    font-size: 2.1rem;
    font-weight: 500;
    color: #f1f2f6;
    letter-spacing: -0.02em;
    margin-bottom: 0.8rem;
}

.gem-greeting span {
    background: linear-gradient(135deg, #a5b4fc, #c084fc);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
}

.gem-tag {
    font-size: 0.76rem;
    color: #8b8f9f;
    background: #171822;
    border: 1px solid #232534;
    border-radius: 999px;
    padding: 4px 14px;
    display: inline-flex;
    align-items: center;
    gap: 6px;
}

.ag-bar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 6px 4px 12px 4px;
    margin-bottom: 14px;
    border-bottom: 1px solid #161720;
}

.ag-title {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 0.95rem;
    font-weight: 600;
    letter-spacing: 0.04em;
    color: #f1f2f6;
}

.ag-title b { color: #818cf8; }

.ag-sparkle {
    width: 14px;
    height: 14px;
    background: linear-gradient(135deg, #6366f1, #c084fc);
    border-radius: 3px;
    box-shadow: 0 0 10px #6366f1;
}

.ag-badges {
    display: flex;
    align-items: center;
    gap: 6px;
    flex-wrap: wrap;
}

.ag-badge {
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.72rem;
    color: #94a3b8;
    background: #14151e;
    border: 1px solid #232534;
    border-radius: 6px;
    padding: 3px 9px;
}

.ag-badge-active {
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.72rem;
    color: #a5b4fc;
    background: #161829;
    border: 1px solid #3730a3;
    border-radius: 6px;
    padding: 3px 9px;
}

.ag-badge-fallback {
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.72rem;
    color: #fbbf24;
    background: #1c1810;
    border: 1px solid #5a4214;
    border-radius: 6px;
    padding: 3px 9px;
}

.ag-worker-banner {
    display: flex;
    align-items: center;
    justify-content: space-between;
    background: #12131c;
    border: 1px solid #26283b;
    border-left: 3px solid #818cf8;
    border-radius: 8px;
    padding: 12px 16px;
    margin-bottom: 14px;
    box-shadow: 0 4px 16px rgba(0, 0, 0, 0.5);
}

.ag-pulse-dot {
    width: 9px;
    height: 9px;
    border-radius: 50%;
    background: #818cf8;
    box-shadow: 0 0 10px #818cf8;
    animation: ag-pulse 1.4s infinite ease-in-out;
    display: inline-block;
    margin-right: 10px;
}

@keyframes ag-pulse {
    0%, 100% { transform: scale(0.9); opacity: 0.5; }
    50% { transform: scale(1.3); opacity: 1; }
}

.ag-recovery-card {
    background: #1a1114;
    border: 1px solid #4a1d24;
    border-radius: 12px;
    padding: 24px;
    text-align: center;
    margin: 20px 0;
}

.ag-chassis {
    background: #0f1016;
    border: 1px solid #1a1b24;
    border-bottom: none;
    border-radius: 8px 8px 0 0;
    padding: 8px 12px;
    display: flex;
    align-items: center;
    justify-content: space-between;
}

.ag-controls {
    display: flex;
    align-items: center;
    gap: 6px;
}

.ag-controls span {
    width: 9px;
    height: 9px;
    border-radius: 50%;
    display: inline-block;
}

.ag-c-red { background: #ef4444; }
.ag-c-yellow { background: #f59e0b; }
.ag-c-green { background: #10b981; }

.ag-chassis-title {
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.72rem;
    color: #64748b;
}

iframe {
    border: 1px solid #1a1b24 !important;
    border-radius: 0 0 8px 8px !important;
    background: #000000 !important;
}

[data-testid="stChatMessage"] {
    background: #11121a !important;
    border: 1px solid #1c1e2b !important;
    border-radius: 12px !important;
}

[data-testid="stChatInput"] {
    background-color: #14151e !important;
    border: 1px solid #26283b !important;
    border-radius: 20px !important;
}

.stButton > button, .stDownloadButton > button {
    background: #14151e !important;
    border: 1px solid #232536 !important;
    color: #cbd5e1 !important;
    border-radius: 8px !important;
    font-weight: 500 !important;
}

.stButton > button:hover, .stDownloadButton > button:hover {
    border-color: #6366f1 !important;
    color: #ffffff !important;
}

.stButton > button[kind="primary"] {
    background: linear-gradient(135deg, #4f46e5, #9333ea) !important;
    border: none !important;
    color: #ffffff !important;
    font-weight: 600 !important;
    box-shadow: 0 0 14px rgba(99, 102, 241, 0.35) !important;
}

div[role="radiogroup"] label {
    background: #12131b !important;
    border: 1px solid #1f212f !important;
    border-radius: 8px !important;
    padding: 4px 14px !important;
    font-size: 0.8rem !important;
}

div[role="radiogroup"] label:has(input:checked) {
    background: #1e1b4b !important;
    border-color: #6366f1 !important;
    color: #c7d2fe !important;
}

.stTabs [data-baseweb="tab-list"] {
    gap: 4px !important;
    border-bottom: 1px solid #1a1b26 !important;
}

.stTabs [data-baseweb="tab"] {
    border-radius: 6px 6px 0 0 !important;
    padding: 6px 14px !important;
    color: #64748b !important;
    font-size: 0.8rem !important;
}

.stTabs [aria-selected="true"] {
    color: #f1f5f9 !important;
    border-bottom: 2px solid #818cf8 !important;
    background: #12131c !important;
}

[data-testid="stCode"] pre, code {
    font-family: 'JetBrains Mono', monospace !important;
    background-color: #0d0e14 !important;
    border: 1px solid #1a1b26 !important;
    border-radius: 8px !important;
    font-size: 0.78rem !important;
}
</style>
"""


def extract_project_files(text):
    files = {}
    pattern = r'<boltAction\s+type="file"\s+filePath="([^"]+)">\n?(.*?)</boltAction>'
    matches = re.findall(pattern, text, re.DOTALL)
    
    if matches:
        for path, content in matches:
            clean_path = path.strip().lstrip("/")
            files[clean_path] = content.strip()
    else:
        m = re.search(r"```(?:html)?\s*\n(.*?)```", text, re.S)
        code = m.group(1) if m else text
        start = re.search(r"<!doctype html|<html", code, re.I)
        if start:
            code = code[start.start():]
        files["index.html"] = code.strip()

    return files


def bundle_for_preview(files):
    main_html = files.get("index.html")
    if not main_html:
        for k, v in files.items():
            if k.endswith(".html"):
                main_html = v
                break
    if not main_html:
        return "<h3>Error: No HTML file found in project</h3>"

    assembled = main_html
    for name, content in files.items():
        base = os.path.basename(name)
        if name.endswith(".css"):
            assembled = re.sub(rf'<link[^>]*href=["\'](\./)?{re.escape(base)}["\'][^>]*>', f'<style>\n{content}\n</style>', assembled)
        elif name.endswith(".js") and not name.endswith(".html"):
            assembled = re.sub(rf'<script[^>]*src=["\'](\./)?{re.escape(base)}["\'][^>]*>\s*</script>', f'<script>\n{content}\n</script>', assembled)

    return inject_errors(assembled)


def create_zip_bundle(files):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    buf.seek(0)
    return buf.getvalue()


def inject_errors(html):
    m = re.search(r"<head[^>]*>", html, re.I)
    if m:
        return html[:m.end()] + ERROR_SNIPPET + html[m.end():]
    return ERROR_SNIPPET + html


class KeyPool:
    def __init__(self, keys):
        self.keys = list(keys)
        self.next_index = 0
        self.cool = {}
        self.model_down = {}
        self.lock = threading.Lock()
        self.no_thinking = set()

    def _pick(self, model):
        with self.lock:
            now = time.time()
            n = len(self.keys)
            for offset in range(n):
                i = (self.next_index + offset) % n
                if self.cool.get((i, model), 0) <= now:
                    self.next_index = (i + 1) % n
                    return i, 0.0
            soonest = min(self.cool.get((i, model), 0) for i in range(n))
            return None, max(0.0, soonest - now)

    def _config(self, model, system, thinking, max_tokens):
        kwargs = {}
        if system:
            kwargs["system_instruction"] = system
        if max_tokens:
            kwargs["max_output_tokens"] = max_tokens
        
        # Explicit thinking levels
        if thinking and thinking.lower() != "off" and model not in self.no_thinking:
            kwargs["thinking_config"] = types.ThinkingConfig(
                thinking_level=thinking.lower()
            )
        return types.GenerateContentConfig(**kwargs) if kwargs else None

    def list_models(self):
        try:
            client = genai.Client(api_key=self.keys[0])
            names = []
            for m in client.models.list():
                name = m.name.replace("models/", "")
                actions = m.supported_actions or []
                if (
                    "gemini" in name
                    and "generateContent" in actions
                    and not any(w in name for w in SKIP_WORDS)
                ):
                    names.append(name)
            return sorted(set(names))
        except Exception:
            return []

    def generate(self, prompt, models, system=None, thinking="low",
                 max_tokens=None, notify=None, patience=2, no_fallback=False,
                 stop_check=None):
        if isinstance(models, str):
            models = [models]
        if no_fallback:
            models = [models[0]]

        tell = notify or (lambda m: None)
        log = []
        last = len(models) - 1

        for idx, model in enumerate(models):
            if stop_check and stop_check():
                raise RuntimeError("Build aborted by user.")

            if idx != last and self.model_down.get(model, 0) > time.time():
                log.append(f"{model}: skipped (cooling)")
                continue
            overloaded = limited = other = 0
            deadline = time.time() + (240 if patience > 2 else 120)

            while time.time() < deadline:
                if stop_check and stop_check():
                    raise RuntimeError("Build aborted by user.")

                i, wait = self._pick(model)
                if i is None:
                    if idx != last:
                        break
                    tell(f"{model}: waiting {int(wait)}s for quota refresh...")
                    time.sleep(min(wait, 5) + 0.1)
                    continue

                config = self._config(model, system, thinking, max_tokens)
                t0 = time.time()
                try:
                    client = genai.Client(
                        api_key=self.keys[i],
                        http_options=types.HttpOptions(timeout=300_000),
                    )
                    response = client.models.generate_content(
                        model=model, contents=prompt, config=config
                    )
                    
                    thoughts = ""
                    code_text = ""
                    try:
                        if response.candidates:
                            for cand in response.candidates:
                                if cand.content and cand.content.parts:
                                    for part in cand.content.parts:
                                        if getattr(part, "thought", False):
                                            thoughts += (part.text or "") + "\n"
                                        else:
                                            code_text += (part.text or "")
                    except Exception:
                        pass

                    if not code_text.strip():
                        try:
                            code_text = response.text or ""
                        except Exception:
                            pass

                    if not code_text.strip():
                        raise RuntimeError(f"{model} returned empty code text.")

                    log.append(f"{model} key {i+1}: OK in {time.time()-t0:.1f}s")
                    return code_text, model, i + 1, log, thoughts

                except errors.APIError as e:
                    code = e.code
                    log.append(f"{model} key {i+1}: error {code}")
                    if (code == 400 and thinking.lower() != "off" and model not in self.no_thinking):
                        self.no_thinking.add(model)
                        continue
                    if code in (500, 502, 503, 504):
                        overloaded += 1
                        if overloaded >= patience:
                            self.model_down[model] = time.time() + 120
                            if no_fallback:
                                raise RuntimeError(f"{model} is busy (HTTP 503). Never-fallback is on.")
                            tell(f"{model} queue congested (503). Shifting to fallback model...")
                            break
                        delay = min(3 * (overloaded), 15)
                        tell(f"{model} busy ({code}). Attempt {overloaded}/{patience}. Retry in {delay:.0f}s...")
                        time.sleep(delay)
                    elif code == 429:
                        limited += 1
                        self.cool[(i, model)] = time.time() + COOLDOWN_SECONDS
                        if limited >= len(self.keys):
                            self.model_down[model] = time.time() + 300
                            if no_fallback:
                                raise RuntimeError(f"{model} rate limits exhausted on all keys.")
                            tell(f"{model} rate limited across pool. Fallback triggered...")
                            break
                    elif code in (401, 403):
                        self.cool[(i, model)] = time.time() + 3600
                    elif code == 404:
                        log.append(f"{model}: unavailable")
                        break
                    else:
                        raise RuntimeError(f"{model}: error {code}: {e}")
                except Exception as e:
                    other += 1
                    log.append(f"{model} key {i+1}: {type(e).__name__}")
                    if other >= 3:
                        break
                    time.sleep(2)

        tail = "; ".join(log[-4:])
        raise RuntimeError(f"All model endpoints saturated. (Status: {tail})")

    def reset(self):
        self.cool.clear()
        self.model_down.clear()

    def status(self):
        now = time.time()
        out = []
        for (i, m), t in self.cool.items():
            if t > now:
                out.append(f"{m} / key {i+1}: cooldown {int(t-now)}s")
        for m, t in self.model_down.items():
            if t > now:
                out.append(f"{m}: paused {int(t-now)}s")
        return out or ["All keys nominal"]


class BackgroundWorker:
    def __init__(self):
        self.thread = None
        self.lock = threading.Lock()
        self.stop_flag = False
        self.state = {
            "running": False,
            "status_msg": "Idle",
            "task_type": None,
            "target_model": None,
            "used_model": None,
            "start_time": 0,
            "elapsed_seconds": 0,
            "result_raw": None,
            "thoughts": None,
            "error": None,
            "logs": [],
        }
        self._load_from_disk()

    def is_running(self):
        with self.lock:
            return self.state["running"]

    def get_snapshot(self):
        with self.lock:
            if self.state["running"]:
                self.state["elapsed_seconds"] = time.time() - self.state["start_time"]
            return dict(self.state)

    def log(self, msg):
        with self.lock:
            self.state["status_msg"] = msg
            ts = time.strftime("%H:%M:%S")
            self.state["logs"].append(f"[{ts}] {msg}")
            if len(self.state["logs"]) > 25:
                self.state["logs"].pop(0)
            self._save_to_disk()

    def start(self, task_type, task_fn, args):
        with self.lock:
            if self.state["running"]:
                return False
            self.stop_flag = False
            self.state["running"] = True
            self.state["status_msg"] = f"Synthesizing {task_type}..."
            self.state["task_type"] = task_type
            self.state["target_model"] = args[1][0] if len(args) > 1 and args[1] else "AI"
            self.state["used_model"] = None
            self.state["start_time"] = time.time()
            self.state["elapsed_seconds"] = 0
            self.state["result_raw"] = None
            self.state["thoughts"] = None
            self.state["error"] = None
            self.state["logs"] = [f"[{time.strftime('%H:%M:%S')}] Agent dispatched."]
            self._save_to_disk()

            self.thread = threading.Thread(
                target=self._run_wrapper, args=(task_fn, args), daemon=True
            )
            self.thread.start()
            return True

    def stop(self):
        with self.lock:
            self.stop_flag = True
            self.state["status_msg"] = "Aborting..."
            self.state["logs"].append(f"[{time.strftime('%H:%M:%S')}] User requested stop.")
            self._save_to_disk()

    def check_stop(self):
        with self.lock:
            return self.stop_flag

    def _run_wrapper(self, task_fn, args):
        try:
            res_raw, used_model, note, thoughts = task_fn(self, *args)
            with self.lock:
                self.state["result_raw"] = res_raw
                self.state["used_model"] = used_model
                self.state["thoughts"] = thoughts
                self.state["status_msg"] = f"Completed with {used_model}{note}"
                self.state["logs"].append(f"[{time.strftime('%H:%M:%S')}] Completed via {used_model}.")
        except Exception as e:
            with self.lock:
                self.state["error"] = str(e)
                self.state["status_msg"] = f"Failed: {e}"
                self.state["logs"].append(f"[{time.strftime('%H:%M:%S')}] Error: {e}")
        finally:
            with self.lock:
                self.state["running"] = False
                self.state["elapsed_seconds"] = time.time() - self.state["start_time"]
                self._save_to_disk()

    def clear_finished(self):
        with self.lock:
            res = self.state.get("result_raw")
            thoughts = self.state.get("thoughts")
            err = self.state.get("error")
            used = self.state.get("used_model")
            task = self.state.get("task_type")
            secs = self.state.get("elapsed_seconds", 0)
            self.state["result_raw"] = None
            self.state["thoughts"] = None
            self.state["error"] = None
            self.state["task_type"] = None
            self._save_to_disk()
            return res, err, used, task, secs, thoughts

    def _save_to_disk(self):
        try:
            with open(STATE_PATH, "w", encoding="utf-8") as f:
                json.dump(self.state, f)
        except Exception:
            pass

    def _load_from_disk(self):
        try:
            if os.path.exists(STATE_PATH):
                with open(STATE_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    data["running"] = False
                    self.state.update(data)
        except Exception:
            pass


@st.cache_resource
def get_pool(version):
    try:
        keys = list(st.secrets.get("GEMINI_KEYS", []))
    except Exception:
        keys = []
    return KeyPool(keys)


@st.cache_resource
def get_worker(version):
    return BackgroundWorker()


@st.cache_data(ttl=3600)
def get_models(version):
    return get_pool(version).list_models()


def resolve(models, wanted, keyword=None):
    for w in wanted:
        if w in models:
            return w
    if keyword:
        for m in models:
            if keyword in m:
                return m
    return models[0]


def build_chain(models, wanted, first=None):
    chain = [m for m in wanted if m in models]
    if first:
        chain = [first] + [m for m in chain if m != first]
    # Always guarantee 3.5-flash-lite as the ultimate safety net
    lite_model = resolve(models, ["gemini-3.5-flash-lite"], "lite")
    if lite_model not in chain:
        chain.append(lite_model)
    return chain or [models[0]]


def make_spec(pool, chain, idea, words, notify=None):
    if words:
        length = f"Write the prompt at about {words} words."
    else:
        length = "Choose the length that fits the project's complexity."
    text, _, _, _, _ = pool.generate(
        f"Idea: {idea}\n\n{length}", chain,
        system=FACTORY_SYSTEM, thinking="low", notify=notify,
    )
    count = len(text.split())
    if words and abs(count - words) / words > 0.15:
        fix = (
            f"Rewrite this prompt to be about {words} words "
            f"(it is currently {count}). Keep every essential requirement. "
            f"Output only the prompt.\n\n{text}"
        )
        text, _, _, _, _ = pool.generate(fix, chain, thinking="low", notify=notify)
    return text.strip()


def say(role, text):
    st.session_state["history"].append({"role": role, "text": text})


def autosave(files):
    try:
        with open(SAVE_PATH, "w", encoding="utf-8") as f:
            json.dump(files, f)
        with open(SPEC_PATH, "w", encoding="utf-8") as f:
            f.write(st.session_state.get("spec", ""))
    except Exception:
        pass


def restore_last():
    if "project_files" in st.session_state:
        return
    if st.session_state.get("restore_done"):
        return
    st.session_state["restore_done"] = True
    try:
        if os.path.exists(SAVE_PATH):
            with open(SAVE_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            if data and isinstance(data, dict):
                st.session_state["project_files"] = data
                st.session_state["stage"] = "built"
                if os.path.exists(SPEC_PATH):
                    with open(SPEC_PATH, "r", encoding="utf-8") as f:
                        st.session_state["spec"] = f.read()
                say("assistant", "Restored your active multi-file workspace.")
    except Exception:
        pass


def reset_all():
    for k in ("spec", "project_files", "previous_files", "loaded_sig",
              "saved_sig", "last_used_model", "target_model", "last_thoughts", "last_error"):
        st.session_state.pop(k, None)
    for p in (SAVE_PATH, SPEC_PATH, STATE_PATH):
        try:
            os.remove(p)
        except OSError:
            pass
    st.session_state["up_n"] = st.session_state.get("up_n", 0) + 1
    st.session_state["stage"] = "idea"
    st.session_state["history"] = []


def undo_refine():
    if st.session_state.get("previous_files"):
        st.session_state["project_files"] = dict(st.session_state.pop("previous_files"))
        say("assistant", "Rolled back to previous code version.")


def get_password():
    try:
        return str(st.secrets.get("APP_PASSWORD", "") or "")
    except Exception:
        return ""


def password_ok():
    pw = get_password()
    if not pw or st.session_state.get("authed"):
        return True
    st.markdown('<div class="ag-title"><span class="ag-sparkle"></span>GEMINI <b>ANTIGRAVITY</b></div>', unsafe_allow_html=True)
    entered = st.text_input("Access Key", type="password")
    if entered:
        if hmac.compare_digest(entered.encode(), pw.encode()):
            st.session_state["authed"] = True
            st.rerun()
        else:
            st.error("Invalid key.")
    return False


st.set_page_config(page_title="Gemini Antigravity", layout="wide",
                   initial_sidebar_state="collapsed")
st.markdown(CSS, unsafe_allow_html=True)

if not password_ok():
    st.stop()

st.session_state.setdefault("stage", "idea")
st.session_state.setdefault("history", [])
st.session_state.setdefault("up_n", 0)
st.session_state.setdefault("thinking_level", "Low")
st.session_state.setdefault("primary_model_choice", "gemini-3.8-flash")

pool = get_pool(APP_VERSION)
worker = get_worker(APP_VERSION)

if not pool.keys:
    st.warning("No API keys found.")
    st.stop()

models = get_models(APP_VERSION)
if not models:
    st.error("Endpoints unavailable. Check API keys.")
    st.stop()

restore_last()

# Process background worker completion
res_raw, err, used, task, secs, thoughts = worker.clear_finished()
if res_raw and len(res_raw.strip()) > 0:
    st.session_state.pop("last_error", None)
    if thoughts:
        st.session_state["last_thoughts"] = thoughts
    parsed_files = extract_project_files(res_raw)
    
    if task == "Build":
        st.session_state["project_files"] = parsed_files
        st.session_state["stage"] = "built"
        st.session_state["last_used_model"] = used
        say("assistant", f"Synthesized {len(parsed_files)} file(s) in {secs:.0f}s via **{used}**. Canvas updated!")
    elif task == "Refine":
        st.session_state["previous_files"] = dict(st.session_state.get("project_files", {}))
        st.session_state["project_files"] = parsed_files
        st.session_state["last_used_model"] = used
        say("assistant", f"Refined {len(parsed_files)} file(s) in {secs:.0f}s via **{used}**. Canvas updated!")
elif err:
    st.session_state["last_error"] = str(err)
    say("assistant", f"Build notice: {err}")

# ---------------- Sidebar ----------------
with st.sidebar:
    st.markdown('<div class="ag-title"><span class="ag-sparkle"></span>GEMINI <b>CORE</b></div>', unsafe_allow_html=True)
    st.caption(f"{len(pool.keys)} project keys loaded | Multi-File Engine")
    
    words = st.number_input("Spec Word Target (0 = Auto)", 0, 3000, 0, 50)
    auto_build_toggle = st.toggle("Auto-Synthesize (Bolt Style)", value=True, help="Automatically builds immediately after spec is generated.")

    st.divider()
    st.markdown("<b>Model & Thinking Engine</b>", unsafe_allow_html=True)
    
    # Model Dropdown matching Gemini Desktop
    preferred_models = [m for m in ["gemini-3.8-flash", "gemini-3.6-flash", "gemini-3.5-flash-lite"] if m in models] or models
    primary_model = st.selectbox(
        "Primary Engine",
        preferred_models,
        index=0,
        key="primary_model_choice"
    )

    # Thinking Level Selector matching screenshot
    thinking_level_ui = st.select_slider(
        "Thinking Level",
        options=["Off", "Low", "Medium", "High"],
        value=st.session_state["thinking_level"],
        key="thinking_level"
    )

    patience_choice = st.radio(
        "Model Patience",
        ["Quick (Fast Fallback)", "Patient (Hold for 3.8)"],
        index=0,
    )
    patience_val = 5 if "Patient" in patience_choice else 2

    no_fallback_refine = st.toggle(
        "Lock Refine to Primary Model",
        value=False,
        help="If off, automatically uses fallback models if 3.8 is busy."
    )
    
    st.divider()
    up = st.file_uploader(
        "Import Workspace (.html or .zip)", type=["html", "htm", "zip"],
        key=f"up_{st.session_state['up_n']}",
    )
    if up is not None:
        sig = (up.name, up.size)
        if st.session_state.get("loaded_sig") != sig:
            if up.name.endswith(".zip"):
                z = zipfile.ZipFile(io.BytesIO(up.getvalue()))
                st.session_state["project_files"] = {name: z.read(name).decode("utf-8", errors="ignore") for name in z.namelist() if not name.endswith("/")}
            else:
                st.session_state["project_files"] = {"index.html": up.getvalue().decode("utf-8", errors="ignore")}
            st.session_state["loaded_sig"] = sig
            st.session_state["stage"] = "built"
            say("assistant", f"Loaded `{up.name}` into canvas.")
            st.rerun()

    st.divider()
    with st.expander("Telemetry & Quotas"):
        st.write(pool.status())
        c1, c2 = st.columns(2)
        with c1:
            if st.button("Reset Quotas"):
                pool.reset()
                st.rerun()
        with c2:
            speed = st.button("Ping Latency")
        if speed:
            t0 = time.time()
            try:
                m = resolve(models, ["gemini-3.5-flash-lite"], "lite")
                pool.generate("Ping.", [m], thinking="low")
                st.write(f"{m}: {time.time()-t0:.1f}s")
            except Exception as e:
                st.error(str(e))
    st.button("Clear Workspace", on_click=reset_all)

# ---------------- Active Models ----------------
spec_chain = build_chain(models, SPEC_CHAIN)
build_chain_list = build_chain(models, [primary_model, "gemini-3.6-flash", "gemini-3.5-flash-lite"], first=primary_model)
build_thinking = st.session_state["thinking_level"]
stage = st.session_state["stage"]


def background_task_runner(w_inst, prompt, chain, system, thinking, max_tokens, no_fallback):
    target = chain[0]
    w_inst.log(f"Synthesizing via {target}...")
    text, used, _, _, thoughts = pool.generate(
        prompt, chain, system=system, thinking=thinking,
        max_tokens=max_tokens, notify=lambda m: w_inst.log(m),
        patience=patience_val, no_fallback=no_fallback,
        stop_check=lambda: w_inst.check_stop(),
    )
    note = ""
    if used != target:
        note = f" (fallback: {used})"
    return text, used, note, thoughts


# ---------------- Top Bar ----------------
last_model = st.session_state.get("last_used_model")
target_model = st.session_state.get("target_model") or build_chain_list[0]

chip_badge = ""
if last_model:
    if last_model == target_model:
        chip_badge = f'<span class="ag-badge-active">● {last_model}</span>'
    else:
        chip_badge = f'<span class="ag-badge-fallback">▲ {last_model}</span>'
else:
    chip_badge = f'<span class="ag-badge">● {target_model}</span>'

st.markdown(
    '<div class="ag-bar">'
    '<div class="ag-title"><span class="ag-sparkle"></span>GEMINI <b>ANTIGRAVITY</b></div>'
    '<div class="ag-badges">'
    f'<span class="ag-badge">{build_thinking.upper()} THINKING</span>'
    f'{chip_badge}'
    f'<span class="ag-badge">{len(pool.keys)} KEYS ACTIVE</span>'
    '</div></div>',
    unsafe_allow_html=True,
)

# ---------------- AFK Worker Status Ribbon ----------------
snap = worker.get_snapshot()
is_busy = snap["running"]

if is_busy:
    st.markdown(
        f'<div class="ag-worker-banner">'
        f'<div><span class="ag-pulse-dot"></span><b>AGENT ACTIVE:</b> {snap["status_msg"]} '
        f'<span style="color:#818cf8; font-family:monospace;">[{int(snap["elapsed_seconds"])}s]</span></div>'
        f'</div>',
        unsafe_allow_html=True,
    )
    col_c1, col_c2 = st.columns([5, 1])
    with col_c1:
        with st.expander("Live Agent Operations Stream", expanded=False):
            st.code("\n".join(snap["logs"]), language="text")
    with col_c2:
        if st.button("Abort Task"):
            worker.stop()
            st.rerun()

    time.sleep(2.5)
    st.rerun()

def format_files_for_prompt(files):
    out = []
    for path, code in files.items():
        out.append(f'<boltAction type="file" filePath="{path}">\n{code}\n</boltAction>')
    return "\n".join(out)

# ---------------- Stage View ----------------
if stage == "idea":
    st.markdown(
        '<div class="gem-hero">'
        '<div class="gem-greeting">Hi, <span>what’s on your mind?</span></div>'
        f'<div class="gem-tag">✦ {primary_model} • {build_thinking} Thinking</div>'
        '</div>',
        unsafe_allow_html=True,
    )

    st.markdown("<b>Instant presets:</b>", unsafe_allow_html=True)
    c_s1, c_s2, c_s3 = st.columns(3)
    preset_prompt = None
    with c_s1:
        if st.button("✎ 3D Voxel Sandbox\nWith dynamic water shaders", use_container_width=True):
            preset_prompt = "Build a 3D Minecraft voxel clone with Three.js, procedural terrain, and dynamic water shaders."
    with c_s2:
        if st.button("⚡ Neon Dash 3D\nFast lane runner with audio", use_container_width=True):
            preset_prompt = "Build a 3D Neon Dash runner game with procedural obstacles, touch controls, and Web Audio synth."
    with c_s3:
        if st.button("🎮 2D Retro Terraria\nSide-scroller canvas mining", use_container_width=True):
            preset_prompt = "Build a 2D Terraria-style platformer sandbox with block breaking, inventory, and dynamic water."

    user_text = st.chat_input("Ask Gemini, specify an idea to build...", disabled=is_busy)
    if preset_prompt:
        user_text = preset_prompt

    if user_text and user_text.strip():
        text = user_text.strip()
        say("user", text)
        ph = st.empty()
        try:
            ph.caption(f"Architecting specification with {spec_chain[0]}...")
            spec = make_spec(pool, spec_chain, text, int(words), notify=lambda m: ph.caption(m))
            st.session_state["spec"] = spec
            ph.empty()
            
            if auto_build_toggle:
                st.session_state["target_model"] = build_chain_list[0]
                st.session_state["stage"] = "spec"
                say("assistant", f"Specification mapped ({len(spec.split())} words). Dispatched synthesizer agent to build project...")
                worker.start(
                    "Build",
                    background_task_runner,
                    (spec, build_chain_list, BUILDER_SYSTEM, build_thinking, 32000, False)
                )
            else:
                st.session_state["stage"] = "spec"
                say("assistant", f"Specification mapped ({len(spec.split())} words). Review below and trigger **Synthesize**.")
        except Exception as e:
            say("assistant", f"Notice: {e}")
        st.rerun()

else:
    user_text = st.chat_input("Refine instruction or paste console errors...", disabled=is_busy)

    left, right = st.columns([2, 3], gap="large")

    with left:
        # Engine Control Card on active workspace
        c_m1, c_m2 = st.columns(2)
        with c_m1:
            st.caption(f"Engine: **{primary_model}**")
        with c_m2:
            st.caption(f"Thinking: **{build_thinking}**")

        if st.session_state.get("last_thoughts"):
            with st.expander("💭 View Model Thought Process", expanded=False):
                st.markdown(st.session_state["last_thoughts"])

        if user_text and user_text.strip():
            text = user_text.strip()
            say("user", text)
            files = st.session_state.get("project_files", {})
            st.session_state["target_model"] = build_chain_list[0]
            
            prompt_payload = (
                f"USER REQUEST:\n{text}\n\n"
                f"CURRENT PROJECT ARTIFACTS:\n{format_files_for_prompt(files)}"
            )
            worker.start(
                "Refine",
                background_task_runner,
                (prompt_payload, build_chain_list, REFINE_SYSTEM,
                 build_thinking, 32000, no_fallback_refine)
            )
            st.rerun()

        for msg in st.session_state["history"]:
            with st.chat_message(msg["role"]):
                st.markdown(msg["text"])

        if stage == "spec":
            st.text_area("Build Specification (Editable)", key="spec", height=240)
            if st.button("Synthesize Project", type="primary", use_container_width=True, disabled=is_busy):
                st.session_state["target_model"] = build_chain_list[0]
                worker.start(
                    "Build",
                    background_task_runner,
                    (st.session_state["spec"], build_chain_list,
                     BUILDER_SYSTEM, build_thinking, 32000, False)
                )
                st.rerun()

        if stage == "built":
            c_undo, _ = st.columns([1, 1])
            with c_undo:
                if st.session_state.get("previous_files"):
                    st.button("Rollback Mutation", on_click=undo_refine, disabled=is_busy)

            with st.expander("Manual AI Studio Bridge"):
                st.caption("Copy this payload directly to Google AI Studio if local queues are saturated:")
                curr_files = st.session_state.get("project_files", {})
                manual_bundle = (
                    f"{REFINE_SYSTEM}\n\n"
                    f"CURRENT PROJECT ARTIFACTS:\n{format_files_for_prompt(curr_files)}\n\n"
                    f"DIRECTIVE:\n{st.session_state['history'][-1]['text'] if st.session_state['history'] else 'Apply changes.'}\n"
                )
                st.code(manual_bundle, language="markdown", wrap_lines=True)
                pasted_code = st.text_area("Paste Generated Artifact Block (<boltArtifact>...)", height=120)
                if st.button("Load Artifact into Canvas"):
                    if pasted_code.strip():
                        st.session_state["previous_files"] = dict(curr_files)
                        st.session_state["project_files"] = extract_project_files(pasted_code)
                        say("assistant", "Manually injected external artifacts into workspace.")
                        st.rerun()

    with right:
        files = st.session_state.get("project_files")
        last_err = st.session_state.get("last_error")

        if files:
            autosave(files)
            assembled_html = bundle_for_preview(files)
            
            c_d1, c_d2 = st.columns(2)
            with c_d1:
                st.download_button(
                    "📦 Download Project (.ZIP)",
                    data=create_zip_bundle(files),
                    file_name="nexus_project.zip",
                    mime="application/zip",
                    use_container_width=True
                )
            with c_d2:
                st.download_button(
                    "📄 Export Standalone HTML",
                    data=assembled_html,
                    file_name="nexus_project.html",
                    mime="text/html",
                    use_container_width=True
                )

            t_prev, t_files, t_spec = st.tabs(["Canvas Preview", "Project Files", "Spec"])
            with t_prev:
                st.markdown(
                    '<div class="ag-chassis">'
                    '<div class="ag-controls"><span class="ag-c-red"></span><span class="ag-c-yellow"></span><span class="ag-c-green"></span></div>'
                    f'<div class="ag-chassis-title">sandbox_virtual_bundle ({len(files)} files)</div>'
                    '<div></div>'
                    '</div>',
                    unsafe_allow_html=True,
                )
                components.html(assembled_html, height=720, scrolling=False)
            with t_files:
                selected_file = st.selectbox("Inspect File:", list(files.keys()))
                if selected_file:
                    ext = selected_file.split(".")[-1]
                    lang = "javascript" if ext == "js" else ("css" if ext == "css" else "html")
                    st.code(files[selected_file], language=lang, wrap_lines=True)
            with t_spec:
                st.code(st.session_state.get("spec", "(no spec yet)"), language="markdown", wrap_lines=True)

        elif last_err and not is_busy:
            # Active Crash Recovery Card
            st.markdown(
                '<div class="ag-chassis">'
                '<div class="ag-controls"><span class="ag-c-red"></span><span class="ag-c-yellow"></span><span class="ag-c-green"></span></div>'
                '<div class="ag-chassis-title">synthesis_interrupted</div>'
                '<div></div>'
                '</div>',
                unsafe_allow_html=True,
            )
            st.markdown(
                '<div class="ag-recovery-card">'
                '<h3 style="color:#ef4444; margin-bottom:8px;">▲ Server Congestion Detected</h3>'
                '<p style="color:#94a3b8; font-size:0.85rem;">Google\'s 3.8 and 3.6 endpoints are currently shedding load (HTTP 503). Your specification is safely preserved.</p>'
                '</div>',
                unsafe_allow_html=True,
            )
            c_r1, c_r2 = st.columns(2)
            with c_r1:
                if st.button("⚡ Fast Re-Build with Flash-Lite (Guaranteed 15s)", type="primary", use_container_width=True):
                    lite_chain = ["gemini-3.5-flash-lite"]
                    st.session_state["target_model"] = "gemini-3.5-flash-lite"
                    st.session_state.pop("last_error", None)
                    worker.start(
                        "Build",
                        background_task_runner,
                        (st.session_state.get("spec", ""), lite_chain,
                         BUILDER_SYSTEM, "off", 32000, False)
                    )
                    st.rerun()
            with c_r2:
                if st.button("🔄 Retry with 3.8", use_container_width=True):
                    st.session_state.pop("last_error", None)
                    worker.start(
                        "Build",
                        background_task_runner,
                        (st.session_state.get("spec", ""), build_chain_list,
                         BUILDER_SYSTEM, build_thinking, 32000, False)
                    )
                    st.rerun()

        else:
            status_text = "AGENT SYNTHESIZING CODE..." if is_busy else "CANVAS IDLE"
            sub_text = "Building multi-file project in background..." if is_busy else "Awaiting agent build output."
            pulse_badge = '<span class="ag-pulse-dot"></span>' if is_busy else ''
            
            st.markdown(
                '<div class="ag-chassis">'
                '<div class="ag-controls"><span class="ag-c-red"></span><span class="ag-c-yellow"></span><span class="ag-c-green"></span></div>'
                f'<div class="ag-chassis-title">{"sandbox_active" if is_busy else "sandbox_idle"}</div>'
                '<div></div>'
                '</div>'
                f'<div style="border: 1px solid #1a1b24; border-radius: 0 0 8px 8px; background: #0c0d14; padding: 6rem 1rem; text-align: center; color: {"#818cf8" if is_busy else "#475569"};">'
                f'<h3>{pulse_badge}{status_text}</h3>'
                f'{sub_text}'
                '</div>',
                unsafe_allow_html=True,
            )
