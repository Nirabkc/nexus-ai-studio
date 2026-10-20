import os
import re
import hmac
import time
import random
import tempfile
import threading
import streamlit as st
import streamlit.components.v1 as components
from google import genai
from google.genai import errors, types

APP_VERSION = "v8"
COOLDOWN_SECONDS = 60
SKIP_WORDS = ("image", "tts", "embed", "live", "audio", "veo",
              "imagen", "robotics", "computer", "aqa")
SAVE_PATH = os.path.join(tempfile.gettempdir(), "nexus_last_project.html")
SPEC_PATH = os.path.join(tempfile.gettempdir(), "nexus_last_spec.txt")

PRESETS = {
    "Fast": {"chain": ["gemini-3.6-flash", "gemini-3.5-flash",
                       "gemini-3.5-flash-lite"],
             "thinking": "low",
             "desc": "Quick builds, light reasoning."},
    "Balanced": {"chain": ["gemini-3.8-flash", "gemini-3.6-flash",
                           "gemini-3.5-flash", "gemini-3.5-flash-lite"],
                 "thinking": "low",
                 "desc": "Best quality for the time. Recommended."},
    "Deep": {"chain": ["gemini-3.8-flash", "gemini-3.6-flash",
                       "gemini-3.5-flash"],
             "thinking": "high",
             "desc": "Slowest, most careful."},
}
SPEC_CHAIN = ["gemini-3.5-flash-lite", "gemini-3.5-flash",
              "gemini-3.6-flash"]

FACTORY_SYSTEM = """You are a senior software architect who writes build \
specifications for an AI coding agent. Turn the user's short idea into ONE \
complete, copy-paste-ready prompt. Output ONLY the prompt text, with no \
preamble and no commentary.

The prompt you write must contain:
1. GOAL: the core experience in 2-3 sentences.
2. TECH CONSTRAINTS: one self-contained HTML file, vanilla JavaScript. If a \
library is needed, only Three.js from cdnjs.cloudflare.com at a pinned \
version; write any noise, math or helper functions inline instead of \
loading extra libraries. No external images, fonts or audio files: draw \
textures on a canvas and synthesize sound with the Web Audio API. Must run \
on iPad Safari with touch controls.
3. MODULAR ARCHITECTURE: named modules inside the file and the \
responsibility of each.
4. MUST-HAVE (MVP) vs STRETCH: list the core features that must work first, \
then optional stretch features to add only if the MVP is stable. Prefer \
simple, reliable techniques (for example, hidden-face culling instead of \
greedy meshing; fresnel and color-gradient effects instead of depth-buffer \
tricks).
5. PHASED PLAN: Phase 1 core engine and state; Phase 2 visuals and layout; \
Phase 3 mechanics, physics, edge cases; Phase 4 audio, polish, optimization.
6. TECHNICAL DETAIL: the specific formulas, algorithms and data structures \
this project needs.
7. MOBILE PERFORMANCE: cap the pixel ratio at 2, limit render distance and \
object counts, avoid per-frame allocations.
8. ACCEPTANCE CRITERIA: a checkable list a script could verify (canvas \
exists, zero console errors, no TODO or placeholder text, each listed \
feature present and named).
9. ZERO-PLACEHOLDER RULE: no TODO, no stubs, no omitted code; every \
function fully written.
Be specific, not generic. Do not add features unrelated to the idea."""

BUILDER_SYSTEM = """You are an expert front-end and WebGL engineer. Build \
exactly what the specification asks for.

Rules:
- Output ONE complete, self-contained HTML file inside a single ```html \
code block. No explanation before or after.
- Zero placeholders: no TODO, no stubs, no "implement later", no omitted \
code. Every function is fully written.
- Vanilla JavaScript. External scripts only from cdnjs.cloudflare.com at \
pinned versions. No external images, fonts or audio files.
- Must work on iPad Safari: touch controls, responsive canvas, pixel ratio \
capped at 2.
- Build the MUST-HAVE features first and make them reliable. Add stretch \
features only if they are safe.
- Wrap risky initialization in try/catch and report problems with \
console.error so they can be diagnosed."""

REFINE_SYSTEM = """You are an expert front-end and WebGL engineer fixing an \
existing single-file HTML project. Apply the requested fixes or changes to \
the CURRENT code. Keep everything that already works unchanged.

When the request describes wrong behavior (for example a reversed \
direction), trace the full data flow from input to what is rendered on \
screen: input values and signs, index or lane mapping, world coordinates, \
camera orientation and any mirrored axes. Find the single root cause and \
fix it there. Do not stack compensating patches in several places, and \
check for accidental double inversion.

Output the COMPLETE updated file inside a single ```html code block, with \
no explanation and no omitted sections."""

ERROR_SNIPPET = r"""<script>
(function(){
  var errs=[];
  function show(m){
    errs.push(m);
    var b=document.getElementById('__nexus_err');
    if(!b){
      b=document.createElement('pre');
      b.id='__nexus_err';
      b.style.cssText='position:fixed;left:0;right:0;bottom:0;max-height:40%;overflow:auto;margin:0;padding:8px;background:rgba(120,0,0,.92);color:#fff;font:12px monospace;z-index:2147483647;white-space:pre-wrap;user-select:text;-webkit-user-select:text';
      (document.body||document.documentElement).appendChild(b);
    }
    b.textContent='NEXUS ERRORS ('+errs.length+'):\n'+errs.join('\n');
  }
  window.addEventListener('error',function(e){
    if(e.target && e.target!==window && (e.target.src||e.target.href)){
      show('FAILED TO LOAD: '+(e.target.src||e.target.href));
    } else {
      show('ERROR: '+e.message+' @ line '+e.lineno);
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
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');
.stApp {
    font-family: 'Inter', -apple-system, sans-serif;
    background:
        radial-gradient(1100px 520px at 12% -8%, #1b2347 0%, transparent 62%),
        radial-gradient(900px 480px at 100% 0%, #22183f 0%, transparent 58%),
        #0b0d12;
}
[data-testid="stCode"] pre, code {
    font-family: 'JetBrains Mono', monospace !important;
}
[data-testid="stHeader"] {background: transparent;}
footer {visibility: hidden;}
.block-container {
    padding-top: 3.6rem; padding-bottom: 7rem; max-width: 100%;
}
[data-testid="stSidebar"] {
    background: #0f121a; border-right: 1px solid #1f2433;
}
.nx-top {
    display: flex; align-items: center; justify-content: space-between;
    flex-wrap: wrap; gap: 8px;
    padding: 0 0 14px 0; margin-bottom: 14px;
    border-bottom: 1px solid #1f2433;
}
.nx-brand {font-size: 1.05rem; font-weight: 600; letter-spacing: .02em;
           color: #e6e8ef; display: flex; align-items: center; gap: 10px;}
.nx-brand b {color: #8fa8ff; font-weight: 700;}
.nx-dot {width: 12px; height: 12px; border-radius: 50%;
         background: linear-gradient(135deg, #6c8cff, #b56cff);
         box-shadow: 0 0 14px #6c8cff99;}
.nx-chips {display: flex; gap: 8px; flex-wrap: wrap;}
.nx-chip {
    font-size: .74rem; color: #aab2c8; background: #141824;
    border: 1px solid #232838; border-radius: 999px; padding: 4px 12px;
}
.nx-win {
    display: flex; align-items: center; gap: 7px;
    background: #141824; border: 1px solid #232838;
    border-bottom: none; border-radius: 12px 12px 0 0;
    padding: 9px 14px; margin-top: 6px;
    font-size: .76rem; color: #7d859c;
}
.nx-win i {width: 10px; height: 10px; border-radius: 50%; display: inline-block;}
.nx-win i:nth-child(1) {background: #ff5f57;}
.nx-win i:nth-child(2) {background: #febc2e;}
.nx-win i:nth-child(3) {background: #28c840;}
.nx-win span {margin-left: 10px;}
iframe {
    border: 1px solid #232838 !important;
    border-radius: 0 0 12px 12px; background: #000;
}
.nx-empty {
    border: 1px dashed #2a3045; border-radius: 16px; padding: 5rem 1.5rem;
    text-align: center; color: #7d859c; background: #0f121a;
}
[data-testid="stChatMessage"] {
    background: rgba(255,255,255,.03); border: 1px solid #232838;
    border-radius: 14px;
}
[data-testid="stChatInput"] {
    border-radius: 16px; border: 1px solid #2a3045;
}
.stButton > button, .stDownloadButton > button {
    border-radius: 10px; border: 1px solid #2a3045; background: #141824;
    color: #dfe3ef; font-weight: 500;
}
.stButton > button:hover, .stDownloadButton > button:hover {
    border-color: #6c8cff; color: #fff;
}
.stButton > button[kind="primary"] {
    background: linear-gradient(135deg, #5f7fff, #9a62ff);
    border: none; color: #fff; font-weight: 600;
}
textarea {
    background: #0f121a !important; border-radius: 12px !important;
    font-family: 'JetBrains Mono', monospace !important; font-size: .82rem;
}
div[role="radiogroup"] {gap: 8px;}
div[role="radiogroup"] label {
    background: #141824; border: 1px solid #232838; border-radius: 999px;
    padding: 4px 16px; margin: 0;
}
div[role="radiogroup"] label > div:first-child {display: none;}
div[role="radiogroup"] label:has(input:checked) {
    background: linear-gradient(135deg, #3b4a9a, #5b3a9a);
    border-color: #6c8cff;
}
.stTabs [data-baseweb="tab-list"] {
    gap: 4px; border-bottom: 1px solid #1f2433;
}
.stTabs [data-baseweb="tab"] {
    border-radius: 8px 8px 0 0; padding: 8px 18px; color: #8b92a8;
}
.stTabs [aria-selected="true"] {color: #e6e8ef;}
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
    """Rotates API keys, retries overloaded models with backoff, and falls
    back through a list of models so one busy model never stops a build."""

    def __init__(self, keys):
        self.keys = list(keys)
        self.next_index = 0
        self.cool = {}          # (key_index, model) -> unix time
        self.model_down = {}    # model -> unix time
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
        if thinking != "off" and model not in self.no_thinking:
            kwargs["thinking_config"] = types.ThinkingConfig(
                thinking_level=thinking
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
                 max_tokens=None, notify=None, patience=3):
        """Try each model in order. Returns (text, model_used, key_no, log)."""
        if isinstance(models, str):
            models = [models]
        tell = notify or (lambda m: None)
        log = []
        last = len(models) - 1
        for idx, model in enumerate(models):
            if idx != last and self.model_down.get(model, 0) > time.time():
                log.append(f"{model}: skipped (recently overloaded)")
                continue
            overloaded = limited = other = 0
            deadline = time.time() + 240
            while time.time() < deadline:
                i, wait = self._pick(model)
                if i is None:
                    if idx != last:
                        break
                    tell(f"{model}: waiting {int(wait)}s for rate limits...")
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
                    log.append(f"{model} key {i+1}: OK in "
                               f"{time.time()-t0:.1f}s")
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
                            tell(f"{model} is overloaded. Switching to the "
                                 "next model...")
                            break
                        delay = 4 * 2 ** (overloaded - 1) + random.random()
                        tell(f"{model} is busy (error {code}). Retrying in "
                             f"{delay:.0f}s...")
                        time.sleep(delay)
                    elif code == 429:
                        limited += 1
                        self.cool[(i, model)] = time.time() + COOLDOWN_SECONDS
                        if limited >= len(self.keys):
                            self.model_down[model] = time.time() + 300
                            tell(f"{model} hit its rate limit on every key. "
                                 "Switching...")
                            break
                    elif code in (401, 403):
                        self.cool[(i, model)] = time.time() + 3600
                    elif code == 404:
                        log.append(f"{model}: not available")
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
        raise RuntimeError(
            "Every model is busy or limited right now. Wait a couple of "
            f"minutes and try again. (Last: {tail})"
        )

    def reset(self):
        self.cool.clear()
        self.model_down.clear()

    def status(self):
        now = time.time()
        out = []
        for (i, m), t in self.cool.items():
            if t > now:
                out.append(f"{m} / key {i+1}: cooling {int(t-now)}s")
        for m, t in self.model_down.items():
            if t > now:
                out.append(f"{m}: paused {int(t-now)}s")
        return out or ["nothing paused"]


@st.cache_resource
def get_pool(version):
    try:
        keys = list(st.secrets.get("GEMINI_KEYS", []))
    except Exception:
        keys = []
    return KeyPool(keys)


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
                say("assistant", "Restored your last project. Describe a "
                                 "change in the box below to keep working.")
    except Exception:
        pass


def reset_all():
    for k in ("spec", "project_html", "previous_html", "loaded_sig",
              "saved_sig"):
        st.session_state.pop(k, None)
    for p in (SAVE_PATH, SPEC_PATH):
        try:
            os.remove(p)
        except OSError:
            pass
    st.session_state["up_n"] = st.session_state.get("up_n", 0) + 1
    st.session_state["stage"] = "idea"
    st.session_state["history"] = []


def undo_refine():
    if st.session_state.get("previous_html"):
        st.session_state["project_html"] = st.session_state.pop(
            "previous_html"
        )
        say("assistant", "Undid the last refine.")


def get_password():
    try:
        return str(st.secrets.get("APP_PASSWORD", "") or "")
    except Exception:
        return ""


def password_ok():
    pw = get_password()
    if not pw or st.session_state.get("authed"):
        return True
    st.markdown('<div class="nx-brand"><span class="nx-dot"></span>NEXUS '
                '<b>AI STUDIO</b></div>', unsafe_allow_html=True)
    entered = st.text_input("Password", type="password")
    if entered:
        if hmac.compare_digest(entered.encode(), pw.encode()):
            st.session_state["authed"] = True
            st.rerun()
        else:
            st.error("Wrong password.")
    return False


st.set_page_config(page_title="NEXUS AI STUDIO", layout="wide",
                   initial_sidebar_state="collapsed")
st.markdown(CSS, unsafe_allow_html=True)

if not password_ok():
    st.stop()

st.session_state.setdefault("stage", "idea")
st.session_state.setdefault("history", [])
st.session_state.setdefault("mode", "Balanced")
st.session_state.setdefault("up_n", 0)

pool = get_pool(APP_VERSION)
if not pool.keys:
    st.warning("No API keys found yet.")
    st.stop()

models = get_models(APP_VERSION)
if not models:
    st.error("Couldn't load the model list. Reboot the app and try again.")
    st.stop()

restore_last()

# ---------------- Sidebar ----------------
with st.sidebar:
    st.markdown('<div class="nx-brand"><span class="nx-dot"></span>NEXUS '
                '<b>AI STUDIO</b></div>', unsafe_allow_html=True)
    st.caption(f"{len(pool.keys)} keys loaded | password gate: "
               f"{'on' if get_password() else 'off'}")
    words = st.number_input("Spec length in words (0 = auto)", 0, 3000, 0, 50)
    manual = st.toggle("Choose first-choice models manually")
    manual_build = manual_spec = None
    if manual:
        manual_spec = st.selectbox(
            "Spec model", models,
            index=models.index(resolve(models, ["gemini-3.5-flash-lite"],
                                       "lite")),
        )
        manual_build = st.selectbox(
            "Builder model", models,
            index=models.index(resolve(models, ["gemini-3.8-flash"])),
        )
    st.divider()
    up = st.file_uploader(
        "Open a saved .html project", type=["html", "htm"],
        key=f"up_{st.session_state['up_n']}",
    )
    if up is not None:
        sig = (up.name, up.size)
        if st.session_state.get("loaded_sig") != sig:
            st.session_state["project_html"] = up.getvalue().decode(
                "utf-8", errors="ignore"
            )
            st.session_state["loaded_sig"] = sig
            st.session_state["stage"] = "built"
            say("assistant", f"Loaded **{up.name}**. Describe a change, or "
                             "paste errors, in the box below.")
            st.rerun()
    st.divider()
    with st.expander("Diagnostics"):
        st.write(pool.status())
        c1, c2 = st.columns(2)
        with c1:
            if st.button("Reset cooldowns"):
                pool.reset()
                st.rerun()
        with c2:
            speed = st.button("Speed test")
        if speed:
            t0 = time.time()
            try:
                m = resolve(models, ["gemini-3.5-flash-lite"], "lite")
                pool.generate("Say hi.", [m], thinking="off")
                st.write(f"{m}: {time.time()-t0:.1f}s")
            except Exception as e:
                st.error(str(e))
    st.button("Start a new project", on_click=reset_all)

# ---------------- Models for this run ----------------
mode = st.session_state["mode"]
spec_chain = build_chain(models, SPEC_CHAIN, manual_spec)
build_chain_list = build_chain(models, PRESETS[mode]["chain"], manual_build)
build_thinking = PRESETS[mode]["thinking"]
stage = st.session_state["stage"]


def run_ai(prompt, chain, system, thinking, max_tokens, label):
    ph = st.empty()
    ph.caption(f"{label} with {chain[0]}...")
    start = time.time()
    try:
        text, used, _, _ = pool.generate(
            prompt, chain, system=system, thinking=thinking,
            max_tokens=max_tokens, notify=lambda m: ph.caption(m),
        )
    finally:
        ph.empty()
    note = ""
    if used != chain[0]:
        note = f" ({chain[0]} was busy, so a fallback model was used)"
    return text, used, time.time() - start, note


# ---------------- Top bar ----------------
st.markdown(
    '<div class="nx-top"><div class="nx-brand"><span class="nx-dot"></span>'
    'NEXUS <b>AI STUDIO</b></div><div class="nx-chips">'
    f'<span class="nx-chip">{mode} mode</span>'
    f'<span class="nx-chip">{build_chain_list[0]}</span>'
    f'<span class="nx-chip">{len(pool.keys)} keys</span>'
    '</div></div>',
    unsafe_allow_html=True,
)

placeholder = (
    "Describe a change, or paste the red-box errors..."
    if stage == "built" else "Describe what you want to build..."
)
user_text = st.chat_input(placeholder)

left, right = st.columns([2, 3], gap="large")

with left:
    st.radio("Mode", list(PRESETS), horizontal=True,
             label_visibility="collapsed", key="mode")
    st.caption(PRESETS[mode]["desc"])

    if user_text and user_text.strip():
        text = user_text.strip()
        if stage in ("idea", "spec"):
            say("user", text)
            ph = st.empty()
            try:
                ph.caption(f"Writing your build spec with {spec_chain[0]}...")
                spec = make_spec(pool, spec_chain, text, int(words),
                                 notify=lambda m: ph.caption(m))
                st.session_state["spec"] = spec
                st.session_state["stage"] = "spec"
                say("assistant",
                    f"Here's the build spec ({len(spec.split())} words). "
                    "Edit it if you like, then tap **Build project**.")
            except Exception as e:
                say("assistant", f"Error: {e}")
            st.rerun()
        else:
            say("user", text)
            html = st.session_state.get("project_html", "")
            try:
                out, used, secs, note = run_ai(
                    f"REQUEST:\n{text}\n\nCURRENT CODE:\n{html}",
                    build_chain_list, REFINE_SYSTEM, build_thinking,
                    32000, "Refining",
                )
                st.session_state["previous_html"] = html
                st.session_state["project_html"] = extract_html(out)
                say("assistant",
                    f"Refined in {secs:.0f}s with {used}{note}. Playtest it, "
                    "or tap **Undo last refine** if it got worse.")
            except Exception as e:
                say("assistant", f"Error: {e}")
            st.rerun()

    if not st.session_state["history"]:
        st.info("Type an idea below to begin, for example: "
                "*a 3D neon cube dodging game*.")

    for msg in st.session_state["history"]:
        with st.chat_message(msg["role"]):
            st.markdown(msg["text"])

    if stage == "spec":
        st.text_area("Build spec (editable)", key="spec", height=280)
        with st.expander("Copy spec"):
            st.code(st.session_state.get("spec", ""), language="markdown",
                    wrap_lines=True)
        if st.button("Build project", type="primary",
                     use_container_width=True):
            try:
                out, used, secs, note = run_ai(
                    st.session_state["spec"], build_chain_list,
                    BUILDER_SYSTEM, build_thinking, 32000, "Building",
                )
                st.session_state["project_html"] = extract_html(out)
                st.session_state["stage"] = "built"
                say("assistant",
                    f"Built in {secs:.0f}s with {used}{note}. Playtest it on "
                    "the right. If a red box appears, press and hold to "
                    "copy it, then paste it in the box below.")
            except Exception as e:
                say("assistant", f"Error: {e}")
            st.rerun()

    if stage == "built" and st.session_state.get("previous_html"):
        st.button("Undo last refine", on_click=undo_refine)

with right:
    html = st.session_state.get("project_html")
    if html:
        autosave(html)
        if "</html>" not in html.lower():
            st.warning("The file looks cut off. Ask for a fix in the chat "
                       "box: 'finish the file, it was cut off'.")
        st.download_button(
            "Download standalone HTML", data=html,
            file_name="nexus_project.html", mime="text/html",
        )
        t_prev, t_code, t_spec = st.tabs(["Preview", "Code", "Spec"])
        with t_prev:
            st.markdown('<div class="nx-win"><i></i><i></i><i></i>'
                        '<span>live preview</span></div>',
                        unsafe_allow_html=True)
            components.html(inject_errors(html), height=720, scrolling=False)
        with t_code:
            st.code(html, language="html", wrap_lines=True)
        with t_spec:
            st.code(st.session_state.get("spec", "(no spec yet)"),
                    language="markdown", wrap_lines=True)
    else:
        st.markdown(
            '<div class="nx-empty"><h3>No project yet</h3>'
            'Your live preview will appear here.</div>',
            unsafe_allow_html=True,
        )
