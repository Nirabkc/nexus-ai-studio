import time
import threading
import streamlit as st
from google import genai
from google.genai import errors, types

APP_VERSION = "v4"
COOLDOWN_SECONDS = 60
SKIP_WORDS = ("image", "tts", "embed", "live", "audio", "veo",
              "imagen", "robotics", "computer", "aqa")

FACTORY_SYSTEM = """You are a senior software architect who writes build \
specifications for an AI coding agent. Turn the user's short idea into ONE \
complete, copy-paste-ready prompt. Output ONLY the prompt text, with no \
preamble and no commentary.

The prompt you write must contain:
1. GOAL: the core experience in 2-3 sentences.
2. TECH CONSTRAINTS: one self-contained HTML file, vanilla JavaScript, \
libraries only from cdnjs.cloudflare.com at pinned versions, must run on \
iPad Safari with touch controls.
3. MODULAR ARCHITECTURE: named modules inside the file and the \
responsibility of each.
4. PHASED PLAN: Phase 1 core engine and state; Phase 2 visuals, shaders, \
lighting, responsive layout; Phase 3 mechanics, physics, edge cases; \
Phase 4 audio, polish, optimization.
5. TECHNICAL DETAIL: the specific formulas, algorithms and data structures \
this project needs (for 3D/WebGL: camera, lighting model, shader approach, \
noise functions, collision method).
6. ACCEPTANCE CRITERIA: a checkable list (loads with zero console errors, \
target frame rate, touch controls work, every listed feature present).
7. ZERO-PLACEHOLDER RULE: no TODO, no stubs, no "implement later", no \
omitted code; every function fully written.
Be specific, not generic. Do not add features unrelated to the idea."""


class KeyPool:
    """Rotates through API keys. A key that hits a rate limit (429)
    is benched for 60 seconds while other keys keep working."""

    def __init__(self, keys):
        self.keys = list(keys)
        self.next_index = 0
        self.cooldown_until = {i: 0.0 for i in range(len(self.keys))}
        self.lock = threading.Lock()
        self.no_thinking = set()

    def _pick(self):
        with self.lock:
            now = time.time()
            n = len(self.keys)
            for offset in range(n):
                i = (self.next_index + offset) % n
                if self.cooldown_until[i] <= now:
                    self.next_index = (i + 1) % n
                    return i, 0.0
            soonest = min(self.cooldown_until.values())
            return None, max(0.0, soonest - now)

    def _bench(self, i, seconds):
        with self.lock:
            self.cooldown_until[i] = time.time() + seconds

    def _config(self, model, system, thinking):
        kwargs = {}
        if system:
            kwargs["system_instruction"] = system
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

    def generate(self, prompt, model, system=None, thinking="low",
                 max_attempts=30):
        log = []
        for _ in range(max_attempts):
            i, wait = self._pick()
            if i is None:
                time.sleep(min(wait, 5) + 0.1)
                continue
            config = self._config(model, system, thinking)
            t0 = time.time()
            try:
                client = genai.Client(api_key=self.keys[i])
                response = client.models.generate_content(
                    model=model, contents=prompt, config=config
                )
                log.append(f"Key {i+1}: OK in {time.time()-t0:.1f}s")
                return (response.text or ""), i + 1, log
            except errors.APIError as e:
                log.append(
                    f"Key {i+1}: error {e.code} after {time.time()-t0:.1f}s"
                )
                if (e.code == 400 and thinking != "off"
                        and model not in self.no_thinking):
                    self.no_thinking.add(model)
                    log.append("Thinking setting rejected, retrying without")
                elif e.code == 429:
                    self._bench(i, COOLDOWN_SECONDS)
                elif e.code in (401, 403):
                    self._bench(i, 3600)
                elif e.code in (500, 502, 503, 504):
                    time.sleep(1)
                else:
                    raise RuntimeError("; ".join(log) + f" | {e}")
        raise RuntimeError("All keys failed. " + "; ".join(log))

    def status(self):
        now = time.time()
        return [
            max(0, int(self.cooldown_until[i] - now))
            for i in range(len(self.keys))
        ]


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


def pick_default(models, preferred, keyword=None):
    for p in preferred:
        if p in models:
            return models.index(p)
    if keyword:
        for i, m in enumerate(models):
            if keyword in m:
                return i
    return 0


def make_spec(pool, model, thinking, idea, words):
    if words:
        length = f"Write the prompt at about {words} words."
    else:
        length = "Choose the length that fits the project's complexity."
    text, _, log = pool.generate(
        f"Idea: {idea}\n\n{length}", model=model,
        system=FACTORY_SYSTEM, thinking=thinking,
    )
    count = len(text.split())
    if words and abs(count - words) / words > 0.15:
        fix = (
            f"Rewrite this prompt to be about {words} words "
            f"(it is currently {count}). Keep every essential requirement. "
            f"Output only the prompt.\n\n{text}"
        )
        text, _, log2 = pool.generate(fix, model=model, thinking=thinking)
        log += ["Length adjustment pass"] + log2
    return text.strip(), log


st.set_page_config(page_title="NEXUS AI STUDIO", layout="wide")
st.title("NEXUS AI STUDIO")

pool = get_pool(APP_VERSION)
if not pool.keys:
    st.warning("No API keys found yet.")
    st.stop()

models = get_models(APP_VERSION)
if not models:
    st.error("Couldn't load the model list. Reboot the app and try again.")
    st.stop()

with st.sidebar:
    st.header("Settings")
    st.caption(f"{len(pool.keys)} keys loaded")
    fast_model = st.selectbox(
        "Fast model (Prompt Factory)", models,
        index=pick_default(models, ["gemini-3.5-flash-lite"], "lite"),
    )
    build_model = st.selectbox(
        "Builder model (used in the next step)", models,
        index=pick_default(
            models, ["gemini-3.6-flash", "gemini-3.5-flash"]
        ),
    )
    thinking = st.selectbox("Thinking depth", ["off", "low", "medium", "high"],
                            index=1)

tab1, tab2 = st.tabs(["Prompt Factory", "Model test"])

with tab1:
    st.subheader("Mini Gemini: Prompt Factory")
    idea = st.text_area(
        "Your idea (one casual sentence is fine)",
        placeholder="make a 3D Minecraft clone with realistic water",
    )
    words = st.number_input(
        "Target word count (0 = let the model decide)",
        min_value=0, max_value=3000, value=0, step=50,
    )
    if st.button("Generate prompt", type="primary"):
        if not idea.strip():
            st.warning("Type an idea first.")
        else:
            start = time.time()
            with st.spinner("Writing your spec..."):
                try:
                    spec, log = make_spec(
                        pool, fast_model, thinking, idea.strip(), int(words)
                    )
                    st.session_state["spec"] = spec
                    st.session_state["spec_info"] = (
                        f"{len(spec.split())} words | {fast_model} | "
                        f"{time.time()-start:.1f}s"
                    )
                    st.session_state["spec_log"] = log
                except Exception as e:
                    st.error(f"Error: {e}")

    if st.session_state.get("spec"):
        st.caption(st.session_state["spec_info"])
        st.caption("Tap the copy icon at the top right of the box:")
        st.code(st.session_state["spec"], language="markdown",
                wrap_lines=True)
        with st.expander("Attempt log"):
            for line in st.session_state.get("spec_log", []):
                st.write(line)

with tab2:
    prompt = st.text_area("Test prompt", "Say hello in one short sentence.")
    if st.button("Run test"):
        start = time.time()
        with st.spinner("Thinking..."):
            try:
                text, key_no, log = pool.generate(
                    prompt, model=fast_model, thinking=thinking
                )
                st.write(text)
                st.caption(
                    f"{fast_model} | key #{key_no} | "
                    f"{time.time()-start:.1f}s"
                )
            except Exception as e:
                st.error(f"Error: {e}")
    with st.expander("Key status (seconds of cooldown left)"):
        st.write(pool.status())
