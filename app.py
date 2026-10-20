import time
import threading
import streamlit as st
from google import genai
from google.genai import errors, types

APP_VERSION = "v3"
DEFAULT_MODEL = "gemini-3.8-flash"
COOLDOWN_SECONDS = 60
SKIP_WORDS = ("image", "tts", "embed", "live", "audio", "veo",
              "imagen", "robotics", "computer", "aqa")


class KeyPool:
    """Rotates through API keys. A key that hits a rate limit (429)
    is benched for 60 seconds while other keys keep working."""

    def __init__(self, keys):
        self.keys = list(keys)
        self.next_index = 0
        self.cooldown_until = {i: 0.0 for i in range(len(self.keys))}
        self.lock = threading.Lock()
        self.no_thinking = set()  # models that reject the thinking setting

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
            return [DEFAULT_MODEL]

    def generate(self, prompt, model, thinking="low", max_attempts=30):
        log = []
        for _ in range(max_attempts):
            i, wait = self._pick()
            if i is None:
                time.sleep(min(wait, 5) + 0.1)
                continue
            config = None
            if thinking != "off" and model not in self.no_thinking:
                config = types.GenerateContentConfig(
                    thinking_config=types.ThinkingConfig(
                        thinking_level=thinking
                    )
                )
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
                if e.code == 400 and config is not None:
                    self.no_thinking.add(model)
                    log.append("Thinking setting rejected, retrying without it")
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


st.set_page_config(page_title="NEXUS AI STUDIO", layout="wide")
st.title("NEXUS AI STUDIO")

pool = get_pool(APP_VERSION)

if not pool.keys:
    st.warning("No API keys found yet.")
    st.stop()

models = get_models(APP_VERSION)
default_index = 0
for idx, name in enumerate(models):
    if "lite" in name:
        default_index = idx
        break
else:
    if DEFAULT_MODEL in models:
        default_index = models.index(DEFAULT_MODEL)

st.caption(f"{len(pool.keys)} keys loaded | {len(models)} models available")

model = st.selectbox("Model (pick a 'lite' one for speed)", models,
                     index=default_index)
thinking = st.selectbox(
    "Thinking depth",
    ["off", "low", "medium", "high"],
    index=1,
)
prompt = st.text_area("Test prompt", "Say hello in one short sentence.")

if st.button("Run test"):
    start = time.time()
    with st.spinner("Thinking..."):
        try:
            text, key_no, log = pool.generate(
                prompt, model=model, thinking=thinking
            )
            st.write(text)
            st.caption(
                f"{model} | key #{key_no} | {time.time()-start:.1f}s total"
            )
            with st.expander("Attempt log"):
                for line in log:
                    st.write(line)
        except Exception as e:
            st.error(f"Error: {e}")

with st.expander("Key status (seconds of cooldown left)"):
    st.write(pool.status())
