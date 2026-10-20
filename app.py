import time
import threading
import streamlit as st
from google import genai
from google.genai import errors, types

MODEL = "gemini-3.8-flash"
COOLDOWN_SECONDS = 60


class KeyPool:
    """Rotates through API keys. A key that hits a rate limit (429)
    is benched for 60 seconds while other keys keep working."""

    def __init__(self, keys):
        self.keys = list(keys)
        self.next_index = 0
        self.cooldown_until = {i: 0.0 for i in range(len(self.keys))}
        self.lock = threading.Lock()
        self.thinking_ok = True

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

    def generate(self, prompt, thinking="low", max_attempts=30):
        log = []
        config = None
        if thinking and self.thinking_ok:
            config = types.GenerateContentConfig(
                thinking_config=types.ThinkingConfig(thinking_level=thinking)
            )
        for _ in range(max_attempts):
            i, wait = self._pick()
            if i is None:
                time.sleep(min(wait, 5) + 0.1)
                continue
            t0 = time.time()
            try:
                client = genai.Client(api_key=self.keys[i])
                response = client.models.generate_content(
                    model=MODEL, contents=prompt, config=config
                )
                log.append(f"Key {i+1}: OK in {time.time()-t0:.1f}s")
                return (response.text or ""), i + 1, log
            except errors.APIError as e:
                log.append(
                    f"Key {i+1}: error {e.code} after {time.time()-t0:.1f}s"
                )
                if e.code == 400 and config is not None:
                    # thinking setting not accepted; retry without it
                    self.thinking_ok = False
                    config = None
                    log.append("Thinking setting rejected, retrying without it")
                elif e.code == 429:
                    self._bench(i, COOLDOWN_SECONDS)
                elif e.code in (401, 403):
                    self._bench(i, 3600)  # bad or blocked key
                elif e.code in (500, 502, 503, 504):
                    time.sleep(1)
                else:
                    raise RuntimeError("; ".join(log))
        raise RuntimeError("All keys failed. " + "; ".join(log))

    def status(self):
        now = time.time()
        return [
            max(0, int(self.cooldown_until[i] - now))
            for i in range(len(self.keys))
        ]


@st.cache_resource
def get_pool():
    try:
        keys = list(st.secrets.get("GEMINI_KEYS", []))
    except Exception:
        keys = []
    return KeyPool(keys)


st.set_page_config(page_title="NEXUS AI STUDIO", layout="wide")
st.title("NEXUS AI STUDIO")

pool = get_pool()

if not pool.keys:
    st.warning("No API keys found yet.")
    st.stop()

st.caption(f"{len(pool.keys)} keys loaded | model: {MODEL}")

prompt = st.text_area("Test prompt", "Say hello in one short sentence.")
thinking = st.selectbox(
    "Thinking depth (low = fast, high = smarter but slower)",
    ["low", "medium", "high"],
    index=0,
)

if st.button("Run test"):
    start = time.time()
    with st.spinner("Thinking..."):
        try:
            text, key_no, log = pool.generate(prompt, thinking=thinking)
            st.write(text)
            st.caption(
                f"Answered by key #{key_no} in {time.time()-start:.1f}s"
            )
            with st.expander("Attempt log"):
                for line in log:
                    st.write(line)
        except Exception as e:
            st.error(f"Error: {e}")

with st.expander("Key status (seconds of cooldown left)"):
    st.write(pool.status())
