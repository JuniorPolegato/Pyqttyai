"""🧪 Smoke test for an OpenVINO-exported LLM (Qwen-2.5 / Qwen-3 / etc.)."""

import sys
import time
import openvino_genai as ov_genai

MODEL_DIR = "qwen_moe_int4_ov"   # 📁 your folder
DEVICE    = "CPU"                # 💻 try "GPU" for Intel iGPU/dGPU
PROMPT    = "Explique em uma frase por que o céu é azul."

print(f"📦 Loading {MODEL_DIR} on {DEVICE}…")
t0 = time.time()
pipe = ov_genai.LLMPipeline(MODEL_DIR, DEVICE)
print(f"✅ Loaded in {time.time() - t0:.1f}s\n")

# 🎚️ Generation parameters
config = ov_genai.GenerationConfig()
config.max_new_tokens = 200
config.do_sample      = True
config.temperature    = 0.7
config.top_p          = 0.9
config.repetition_penalty = 1.05

# 📊 Streaming token printer + tok/s counter
n_tokens = {"count": 0}
t_start = {"t": None}

def streamer(subword: str) -> bool:
    if t_start["t"] is None:
        t_start["t"] = time.time()  # ⏱️ start timing on first token
    n_tokens["count"] += 1
    print(subword, end="", flush=True)
    return False  # 🛑 return True to abort

print("📝 Prompt:", PROMPT)
print("─" * 60)

t0 = time.time()
pipe.start_chat()                         # 🗣️ uses chat_template.jinja
result = pipe.generate(PROMPT, config, streamer)
elapsed = time.time() - t0
gen_time = time.time() - t_start["t"]

print("\n" + "─" * 60)
print(f"🪙 {n_tokens['count']} tokens in {elapsed:.1f}s "
      f"({n_tokens['count'] / max(gen_time, 0.001):.1f} tok/s)")
