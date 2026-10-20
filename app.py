import os
import re
import json
import hmac
import time
import random
import tempfile
import threading
import streamlit as st
import streamlit.components.v1 as components
from google import genai
from google.genai import errors, types

APP_VERSION = "v12"
COOLDOWN_SECONDS = 60
SKIP_WORDS = ("image", "tts", "embed", "live", "audio", "veo",
              "imagen", "robotics", "computer", "aqa")
SAVE_PATH = os.path.join(tempfile.gettempdir(), "nexus_last_project.html")
SPEC_PATH = os.path.join(tempfile.gettempdir(), "nexus_last_spec.txt")
STATE_PATH = os.path.join(tempfile.gettempdir(), "nexus_worker_state.json")

PRESETS = {
    "Turbo": {
        "chain": ["gemini-3.6-flash", "gemini-3.5-flash", "gemini-3.5-flash-lite"],
        "thinking": "low",
        "desc": "Ultra-fast execution with lightweight reasoning passes.",
    },
    "High": {
        "chain": ["gemini-3.8-flash", "gemini-3.6-flash", "gemini-3.5-flash", "gemini-3.5-flash-lite"],
        "thinking": "low",
        "desc": "Antigravity standard. Uses gemini-3.8-flash with automatic model fallback.",
    },
    "Deep": {
        "chain": ["gemini-3.8-flash", "gemini-3.6-flash", "gemini-3.5-flash"],
        "thinking": "high",
        "desc": "Maximum latent reasoning. Slowest, highest-fidelity outputs.",
    },
}
SPEC_CHAIN = ["gemini-3.5-flash-lite", "gemini-3.5-flash", "gemini-3.6-flash"]

FACTORY_SYSTEM = """You are a senior software architect who writes build specifications for an AI coding agent. Turn the user's short idea into ONE complete, copy-paste-ready prompt. Output ONLY the prompt text, with no preamble and no commentary.

The prompt you write must contain:
1. GOAL: the core experience in 2-3 sentences.
2. TECH CONSTRAINTS: one self-contained HTML file, vanilla JavaScript. If a library is needed, only Three.js from cdnjs.cloudflare.com at a pinned version; write any noise, math or helper functions inline instead of loading extra libraries. No external images, fonts or audio files: draw textures on a canvas and synthesize sound with the Web Audio API. Must run on iPad Safari with touch controls.
3. MODULAR ARCHITECTURE: named modules inside the file and the responsibility of each.
4. MUST-HAVE (MVP) vs STRETCH: list the core features that must work first, then optional stretch features to add only if the MVP is stable. Prefer simple, reliable techniques (for example, hidden-face culling instead of greedy meshing; fresnel and color-gradient effects instead of depth-buffer tricks).
5. PHASED PLAN: Phase 1 core engine and state; Phase 2 visuals and layout; Phase 3 mechanics, physics, edge cases; Phase 4 audio, polish, optimization.
6. TECHNICAL DETAIL: the specific formulas, algorithms and data structures this project needs.
7. MOBILE PERFORMANCE: cap the pixel ratio at 2, limit render distance and object counts, avoid per-frame allocations.
8. ACCEPTANCE CRITERIA: a checkable list a script could verify (canvas exists, zero console errors, no TODO or placeholder text, each listed feature present and named).
9. ZERO-PLACEHOLDER RULE: no TODO, no stubs, no omitted code; every function fully written.
Be specific, not generic. Do not add features unrelated to the idea."""

BUILDER_SYSTEM = """You are an expert front-end and WebGL engineer. Build exactly what the specification asks for.

Rules:
- Output ONE complete, self-contained HTML file inside a single ```html code block. No explanation before or after.
- Zero placeholders: no TODO, no stubs, no "implement later", no omitted code. Every function is fully written.
- Vanilla JavaScript. External scripts only from cdnjs.cloudflare.com at pinned versions. No external images, fonts or audio files.
- Must work on iPad Safari: touch controls, responsive canvas, pixel ratio capped at 2.
- Build the MUST-HAVE features first and make them reliable. Add stretch features only if they are safe.
- Wrap risky initialization in try/catch and report problems with console.error so they can be diagnosed."""

REFINE_SYSTEM = """You are an expert front-end and WebGL engineer fixing an existing single-file HTML project. Apply the requested fixes or changes to the CURRENT code. Keep everything that already works unchanged.

When the request describes wrong behavior (for example a reversed direction), trace the full data flow from input to what is rendered on screen: input values and signs, index or lane mapping, world coordinates, camera orientation and any mirrored axes. Find the single root cause and fix it there. Do not stack compensating patches in several places, and check for accidental double inversion.

Output the COMPLETE updated file inside a single ```html code block, with no explanation and no omitted sections."""

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
@import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');

html, body, [class*="css"] {
    font-family: 'Plus Jakarta Sans', -apple-system, sans-serif !important;
}

.stApp {
    background-color: #08080a !important;
    background-image: 
        radial-gradient(at 0% 0%, rgba(30, 27, 75, 0.18) 0px, transparent 50%),
        radial-gradient(at 100% 100%, rgba(15, 23, 42, 0.25) 0px, transparent 50%) !important;
    color: #e2e2e8 !important;
}

[data-testid="stHeader"] {display: none !important;}
footer {visibility: hidden !important;}

.block-container {
    padding-top: 1.2rem !important;
    padding-bottom: 4rem !important;
    max-width: 98% !important;
}

[data-testid="stSidebar"] {
    background-color: #0c0d12 !important;
    border-right: 1px solid #1a1b24 !important;
}

.ag-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    flex-wrap: wrap;
    padding: 6px 4px 14px 4px;
    margin-bottom: 14px;
    border-bottom: 1px solid #181922;
}

.ag-logo {
    display: flex;
    align-items: center;
    gap: 9px;
    font-size: 0.95rem;
    font-weight: 700;
    letter-spacing: 0.05em;
    color: #f1f1f5;
    text-transform: uppercase;
}

.ag-logo span {
    color: #818cf8;
}

.ag-glyph {
    width: 14px;
    height: 14px;
    background: linear-gradient(135deg, #6366f1, #a855f7);
    border-radius: 3px;
    box-shadow: 0 0 10px rgba(99, 102, 241, 0.6);
}

.ag-badges {
    display: flex;
    align-items: center;
    gap: 6px;
    flex-wrap: wrap;
}

.ag-pill {
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.72rem;
    color: #94a3b8;
    background: #111218;
    border: 1px solid #1e202c;
    border-radius: 6px;
    padding: 3px 9px;
}

.ag-pill-active {
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.72rem;
    color: #a5b4fc;
    background: #141624;
    border: 1px solid #312e81;
    border-radius: 6px;
    padding: 3px 9px;
}

.ag-pill-fallback {
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.72rem;
    color: #fbbf24;
    background: #1c1911;
    border: 1px solid #453412;
    border-radius: 6px;
    padding: 3px 9px;
}

.ag-worker-banner {
    display: flex;
    align-items: center;
    justify-content: space-between;
    background: #0f1017;
    border: 1px solid #282a3d;
    border-left: 3px solid #6366f1;
    border-radius: 8px;
    padding: 10px 14px;
    margin-bottom: 14px;
    box-shadow: 0 4px 16px rgba(0, 0, 0, 0.5);
}

.ag-worker-left {
    display: flex;
    align-items: center;
    gap: 10px;
    font-size: 0.84rem;
    color: #e2e8f0;
}

.ag-pulse-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: #6366f1;
    box-shadow: 0 0 8px #6366f1;
    animation: ag-pulse 1.4s infinite ease-in-out;
}

@keyframes ag-pulse {
    0%, 100% { transform: scale(0.9); opacity: 0.5; }
    50% { transform: scale(1.3); opacity: 1; }
}

.ag-chassis {
    background: #0e0f14;
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

.ag-title {
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
    background: #0d0e14 !important;
    border: 1px solid #181924 !important;
    border-radius: 8px !important;
}

[data-testid="stChatInput"] {
    background-color: #0e0f15 !important;
    border: 1px solid #222330 !important;
    border-radius: 8px !important;
}

.stButton > button, .stDownloadButton > button {
    background: #12131b !important;
    border: 1px solid #232534 !important;
    color: #cbd5e1 !important;
    border-radius: 6px !important;
    font-weight: 500 !important;
    font-size: 0.82rem !important;
    transition: all 0.15s ease !important;
}

.stButton > button:hover, .stDownloadButton > button:hover {
    border-color: #4f46e5 !important;
    color: #ffffff !important;
}

.stButton > button[kind="primary"] {
    background: linear-gradient(135deg, #4f46e5, #7c3aed) !important;
    border: none !important;
    color: #ffffff !important;
    font-weight: 600 !important;
    box-shadow: 0 0 14px rgba(99, 102, 241, 0.3) !important;
}

div[role="radiogroup"] {
    gap: 6px !important;
}

div[role="radiogroup"] label {
    background: #111218 !important;
    border: 1px solid #1c1d28 !important;
    border-radius: 6px !important;
    padding: 3px 14px !important;
    font-size: 0.8rem !important;
}

div[role="radiogroup"] label:has(input:checked) {
    background: #181a29 !important;
    border-color: #4f46e5 !important;
    color: #c7d2fe !important;
}

.stTabs [data-baseweb="tab-list"] {
    gap: 4px !important;
    border-bottom: 1px solid #181924 !important;
}

.stTabs [data-baseweb="tab"] {
    border-radius: 6px 6px 0 0 !important;
    padding: 6px 14px !important;
    color: #64748b !important;
    font-size: 0.8rem !important;
}

.stTabs [aria-selected="true"] {
    color: #f1f5f9 !important;
    border-bottom: 2px solid #6366f1 !important;
    background: #0f1017 !important;
}

[data-testid="stCode"] pre, code {
    font-family: 'JetBrains Mono', monospace !important;
    background-color: #0b0c10 !important;
    border: 1px solid #181924 !important;
    border-radius: 6px !important;
    font-size: 0.78rem !important;
}
</style>
"""


def extract_html(text):
    m = re.search(r"```(?:html)?\s*\n(.*?)```", text, re.S)
    code = m.group(1) if m else text
    start = re.search(r"<!doctype html|<html", code, re.I)
    if start:
        code = code[start.start():]
    return code.strip()


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
        effective_thinking = thinking
        if "3.8" in model and thinking == "off":
            effective_thinking = "low"

        if effective_thinking != "off" and model not in self.no_thinking:
            kwargs["thinking_config"] = types.ThinkingConfig(
                thinking_level=effective_thinking
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
                 max_tokens=None, notify=None, patience=3, no_fallback=False,
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
            deadline = time.time() + (300 if patience > 3 else 180)

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
                    log.append(f"{model} key {i+1}: OK in {time.time()-t0:.1f}s")
                    return (response.text or ""), model, i + 1, log
                except errors.APIError as e:
                    code = e.code
                    log.append(f"{model} key {i+1}: error {code}")
                    if (code == 400 and thinking != "off"
                            and model not in self.no_thinking):
                        self.no_thinking.add(model)
                        continue
                    if code in (500, 502, 503, 504):
                        overloaded += 1
                        if overloaded >= patience:
                            self.model_down[model] = time.time() + 120
                            if no_fallback:
                                raise RuntimeError(
                                    f"{model} is overloaded (503). Never-fallback is enabled. "
                                    "Use Manual Hand-off below or try again in a moment."
                                )
                            tell(f"{model} capacity reached. Shifting to next model...")
                            break
                        delay = min(4 * 2 ** (overloaded - 1) + random.random(), 30)
                        tell(f"{model} queue saturated ({code}). Retry {overloaded}/{patience} in {delay:.0f}s...")
                        time.sleep(delay)
                    elif code == 429:
                        limited += 1
                        self.cool[(i, model)] = time.time() + COOLDOWN_SECONDS
                        if limited >= len(self.keys):
                            self.model_down[model] = time.time() + 300
                            if no_fallback:
                                raise RuntimeError(
                                    f"{model} rate limits exhausted on all keys."
                                )
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
                    if other >= 4:
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
        return out or ["All models & keys nominal"]


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
            "result_html": None,
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
            self.state["status_msg"] = f"Dispatching {task_type}..."
            self.state["task_type"] = task_type
            self.state["target_model"] = args[1][0] if len(args) > 1 and args[1] else "AI"
            self.state["used_model"] = None
            self.state["start_time"] = time.time()
            self.state["elapsed_seconds"] = 0
            self.state["result_html"] = None
            self.state["error"] = None
            self.state["logs"] = [f"[{time.strftime('%H:%M:%S')}] Agent started in background."]
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
            self.state["logs"].append(f"[{time.strftime('%H:%M:%S')}] User requested cancellation.")
            self._save_to_disk()

    def check_stop(self):
        with self.lock:
            return self.stop_flag

    def _run_wrapper(self, task_fn, args):
        try:
            res_html, used_model, note = task_fn(self, *args)
            with self.lock:
                self.state["result_html"] = res_html
                self.state["used_model"] = used_model
                self.state["status_msg"] = f"Completed with {used_model}{note}"
                self.state["logs"].append(f"[{time.strftime('%H:%M:%S')}] Done: {used_model}.")
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
            res = self.state.get("result_html")
            err = self.state.get("error")
            used = self.state.get("used_model")
            task = self.state.get("task_type")
            secs = self.state.get("elapsed_seconds", 0)
            self.state["result_html"] = None
            self.state["error"] = None
            self.state["task_type"] = None
            self._save_to_disk()
            return res, err, used, task, secs

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
    return chain or [models[0]]


def make_spec(pool, chain, idea, words, notify=None):
    if words:
        length = f"Write the prompt at about {words} words."
    else:
        length = "Choose the length that fits the project's complexity."
    text, _, _, _ = pool.generate(
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
        text, _, _, _ = pool.generate(fix, chain, thinking="low",
                                      notify=notify)
    return text.strip()


def say(role, text):
    st.session_state["history"].append({"role": role, "text": text})


def autosave(html):
    sig = (len(html), hash(html))
    if st.session_state.get("saved_sig") == sig:
        return
    try:
        with open(SAVE_PATH, "w", encoding="utf-8") as f:
            f.write(html)
        with open(SPEC_PATH, "w", encoding="utf-8") as f:
            f.write(st.session_state.get("spec", ""))
        st.session_state["saved_sig"] = sig
    except Exception:
        pass


def restore_last():
    if "project_html" in st.session_state:
        return
    if st.session_state.get("restore_done"):
        return
    st.session_state["restore_done"] = True
    try:
        if os.path.exists(SAVE_PATH):
            with open(SAVE_PATH, "r", encoding="utf-8") as f:
                html = f.read()
            if html.strip():
                st.session_state["project_html"] = html
                st.session_state["stage"] = "built"
                if os.path.exists(SPEC_PATH):
                    with open(SPEC_PATH, "r", encoding="utf-8") as f:
                        st.session_state["spec"] = f.read()
                say("assistant", "Restored your last active workspace from disk.")
    except Exception:
        pass


def reset_all():
    for k in ("spec", "project_html", "previous_html", "loaded_sig",
              "saved_sig", "last_used_model", "target_model"):
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
    if st.session_state.get("previous_html"):
        st.session_state["project_html"] = st.session_state.pop("previous_html")
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
    st.markdown('<div class="ag-logo"><span class="ag-glyph"></span>ANTIGRAVITY <span>STUDIO</span></div>', unsafe_allow_html=True)
    entered = st.text_input("Access Key", type="password")
    if entered:
        if hmac.compare_digest(entered.encode(), pw.encode()):
            st.session_state["authed"] = True
            st.rerun()
        else:
            st.error("Invalid key.")
    return False


st.set_page_config(page_title="Antigravity Studio", layout="wide",
                   initial_sidebar_state="collapsed")
st.markdown(CSS, unsafe_allow_html=True)

if not password_ok():
    st.stop()

# --- Auto-migration for legacy session state ---
if "mode" not in st.session_state or st.session_state["mode"] not in PRESETS:
    if st.session_state.get("mode") == "Fast":
        st.session_state["mode"] = "Turbo"
    else:
        st.session_state["mode"] = "High"

st.session_state.setdefault("stage", "idea")
st.session_state.setdefault("history", [])
st.session_state.setdefault("up_n", 0)

pool = get_pool(APP_VERSION)
worker = get_worker(APP_VERSION)

if not pool.keys:
    st.warning("No API keys configured.")
    st.stop()

models = get_models(APP_VERSION)
if not models:
    st.error("Model endpoints unavailable. Check API keys.")
    st.stop()

restore_last()

# Check background task results from disk
res, err, used, task, secs = worker.clear_finished()
if res:
    if task == "Build":
        st.session_state["project_html"] = extract_html(res)
        st.session_state["stage"] = "built"
        st.session_state["last_used_model"] = used
        say("assistant", f"Synthesized in {secs:.0f}s via **{used}**. Preview updated.")
    elif task == "Refine":
        st.session_state["previous_html"] = st.session_state.get("project_html", "")
        st.session_state["project_html"] = extract_html(res)
        st.session_state["last_used_model"] = used
        say("assistant", f"Refined in {secs:.0f}s via **{used}**. Tested & verified.")
elif err:
    say("assistant", f"Task aborted: {err}")

# ---------------- Sidebar ----------------
with st.sidebar:
    st.markdown('<div class="ag-logo"><span class="ag-glyph"></span>ANTIGRAVITY <span>CORE</span></div>', unsafe_allow_html=True)
    st.caption(f"{len(pool.keys)} project keys loaded | AFK Daemon Active")
    
    words = st.number_input("Spec Word Target (0 = Auto)", 0, 3000, 0, 50)
    
    st.divider()
    st.markdown("<b>Agent Configuration</b>", unsafe_allow_html=True)
    patience_choice = st.radio(
        "Model Patience",
        ["Quick (Fast Fallback)", "Patient (Hold for 3.8)"],
        index=0,
        help="Patient retries gemini-3.8-flash for up to 2m before falling back."
    )
    patience_val = 6 if "Patient" in patience_choice else 3

    no_fallback_refine = st.toggle(
        "Lock Refine to Primary Model",
        value=True,
        help="Prevents smaller fallback models from modifying complex 3.8 codebases."
    )

    manual = st.toggle("Override Model Endpoints")
    manual_build = manual_spec = None
    if manual:
        manual_spec = st.selectbox(
            "Architect Model", models,
            index=models.index(resolve(models, ["gemini-3.5-flash-lite"], "lite")),
        )
        manual_build = st.selectbox(
            "Synthesizer Model", models,
            index=models.index(resolve(models, ["gemini-3.8-flash"])),
        )
    
    st.divider()
    up = st.file_uploader(
        "Import Workspace HTML", type=["html", "htm"],
        key=f"up_{st.session_state['up_n']}",
    )
    if up is not None:
        sig = (up.name, up.size)
        if st.session_state.get("loaded_sig") != sig:
            st.session_state["project_html"] = up.getvalue().decode("utf-8", errors="ignore")
            st.session_state["loaded_sig"] = sig
            st.session_state["stage"] = "built"
            say("assistant", f"Loaded `{up.name}` into active workspace.")
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
mode = st.session_state.get("mode", "High")
if mode not in PRESETS:
    mode = "High"
    st.session_state["mode"] = "High"

spec_chain = build_chain(models, SPEC_CHAIN, manual_spec)
build_chain_list = build_chain(models, PRESETS[mode]["chain"], manual_build)
build_thinking = PRESETS[mode]["thinking"]
stage = st.session_state["stage"]


def background_task_runner(w_inst, prompt, chain, system, thinking, max_tokens, no_fallback):
    target = chain[0]
    w_inst.log(f"Synthesizing via {target}...")
    text, used, _, _ = pool.generate(
        prompt, chain, system=system, thinking=thinking,
        max_tokens=max_tokens, notify=lambda m: w_inst.log(m),
        patience=patience_val, no_fallback=no_fallback,
        stop_check=lambda: w_inst.check_stop(),
    )
    note = ""
    if used != target:
        note = f" (fallback: {used})"
    return text, used, note


# ---------------- Antigravity Top Header ----------------
last_model = st.session_state.get("last_used_model")
target_model = st.session_state.get("target_model")

chip_badge = ""
if last_model and target_model:
    if last_model == target_model:
        chip_badge = f'<span class="ag-pill-active">● {last_model}</span>'
    else:
        chip_badge = f'<span class="ag-pill-fallback">▲ {last_model}</span>'
else:
    chip_badge = f'<span class="ag-pill">● {build_chain_list[0]}</span>'

st.markdown(
    '<div class="ag-header">'
    '<div class="ag-logo"><span class="ag-glyph"></span>ANTIGRAVITY <span>STUDIO</span></div>'
    '<div class="ag-badges">'
    f'<span class="ag-pill">{mode.upper()} EFFORT</span>'
    f'{chip_badge}'
    f'<span class="ag-pill">{len(pool.keys)} KEYS ACTIVE</span>'
    '</div></div>',
    unsafe_allow_html=True,
)

# ---------------- Antigravity Agent Status Ribbon ----------------
snap = worker.get_snapshot()
is_busy = snap["running"]

if is_busy:
    st.markdown(
        f'<div class="ag-worker-banner">'
        f'<div class="ag-worker-left">'
        f'<span class="ag-pulse-dot"></span>'
        f'<b>AGENT WORKING:</b> {snap["status_msg"]} '
        f'<span style="color:#818cf8; font-family:monospace;">[{int(snap["elapsed_seconds"])}s]</span>'
        f'</div></div>',
        unsafe_allow_html=True,
    )
    col_c1, col_c2 = st.columns([5, 1])
    with col_c1:
        with st.expander("Inspect Agent Operations (Safe to sleep iPad)", expanded=False):
            st.code("\n".join(snap["logs"]), language="text")
    with col_c2:
        if st.button("Abort Task"):
            worker.stop()
            st.rerun()

    time.sleep(2.5)
    st.rerun()

placeholder = (
    "Refine instruction or paste console errors..."
    if stage == "built" else "Ask anything, specify an idea to build..."
)
user_text = st.chat_input(placeholder, disabled=is_busy)

left, right = st.columns([2, 3], gap="large")

with left:
    st.radio("Effort", list(PRESETS), horizontal=True,
             label_visibility="collapsed", key="mode", disabled=is_busy)
    st.caption(PRESETS[st.session_state["mode"]]["desc"])

    if user_text and user_text.strip():
        text = user_text.strip()
        if stage in ("idea", "spec"):
            say("user", text)
            ph = st.empty()
            try:
                ph.caption(f"Architecting build specification with {spec_chain[0]}...")
                spec = make_spec(pool, spec_chain, text, int(words),
                                 notify=lambda m: ph.caption(m))
                st.session_state["spec"] = spec
                st.session_state["stage"] = "spec"
                say("assistant",
                    f"Specification mapped ({len(spec.split())} words). "
                    "Review below and trigger **Synthesize Project**.")
            except Exception as e:
                say("assistant", f"Error: {e}")
            st.rerun()
        else:
            say("user", text)
            html = st.session_state.get("project_html", "")
            st.session_state["target_model"] = build_chain_list[0]
            worker.start(
                "Refine",
                background_task_runner,
                (f"REQUEST:\n{text}\n\nCURRENT CODE:\n{html}",
                 build_chain_list, REFINE_SYSTEM, build_thinking,
                 32000, no_fallback_refine)
            )
            st.rerun()

    if not st.session_state["history"]:
        st.info("Input a project directive below to initialize workspace.")

    for msg in st.session_state["history"]:
        with st.chat_message(msg["role"]):
            st.markdown(msg["text"])

    if stage == "spec":
        st.text_area("Build Specification", key="spec", height=280)
        with st.expander("Inspect Specification Markdown"):
            st.code(st.session_state.get("spec", ""), language="markdown", wrap_lines=True)
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
            if st.session_state.get("previous_html"):
                st.button("Rollback Last Mutation", on_click=undo_refine, disabled=is_busy)

        with st.expander("Manual AI Studio Bridge"):
            st.caption("Copy this payload directly to Google AI Studio if local queues are saturated:")
            curr_code = st.session_state.get("project_html", "")
            manual_bundle = (
                f"{REFINE_SYSTEM}\n\n"
                f"CURRENT CODE:\n```html\n{curr_code}\n```\n\n"
                f"DIRECTIVE:\n{st.session_state['history'][-1]['text'] if st.session_state['history'] else 'Apply changes.'}\n"
            )
            st.code(manual_bundle, language="markdown", wrap_lines=True)
            pasted_code = st.text_area("Paste Generated HTML Artifact", height=120)
            if st.button("Load Artifact into Canvas"):
                if pasted_code.strip():
                    st.session_state["previous_html"] = curr_code
                    st.session_state["project_html"] = extract_html(pasted_code)
                    say("assistant", "Manually injected external artifact into canvas.")
                    st.rerun()

with right:
    html = st.session_state.get("project_html")
    if html:
        autosave(html)
        if "</html>" not in html.lower():
            st.warning("Artifact generation truncated. Instruct agent to complete stream.")
        st.download_button(
            "Export Standalone Project", data=html,
            file_name="nexus_project.html", mime="text/html",
        )
        t_prev, t_code, t_spec = st.tabs(["Canvas", "Source", "Spec"])
        with t_prev:
            st.markdown(
                '<div class="ag-chassis">'
                '<div class="ag-controls"><span class="ag-c-red"></span><span class="ag-c-yellow"></span><span class="ag-c-green"></span></div>'
                '<div class="ag-title">sandbox_canvas.html</div>'
                '<div></div>'
                '</div>',
                unsafe_allow_html=True,
            )
            components.html(inject_errors(html), height=720, scrolling=False)
        with t_code:
            st.code(html, language="html", wrap_lines=True)
        with t_spec:
            st.code(st.session_state.get("spec", "(no spec yet)"), language="markdown", wrap_lines=True)
    else:
        st.markdown(
            '<div class="ag-chassis">'
            '<div class="ag-controls"><span class="ag-c-red"></span><span class="ag-c-yellow"></span><span class="ag-c-green"></span></div>'
            '<div class="ag-title">sandbox_idle</div>'
            '<div></div>'
            '</div>'
            '<div class="nx-empty" style="border: 1px solid #1a1b24; border-radius: 0 0 8px 8px; background: #0a0b0f; padding: 6rem 1rem; text-align: center; color: #475569;">'
            '<h3>CANVAS IDLE</h3>'
            'Awaiting agent build output.'
            '</div>',
            unsafe_allow_html=True,
        )
