"""📊 Compare CPU(P-cores) / CPU(all) / GPU on the same model."""

import os
import time
import openvino_genai as ov_genai
import openvino as ov

MODEL_DIR = "qwen3_moe_int4_ov"
PROMPTS = [
    "Por que o céu é azul? Explique em 3 frases.",
    "List 5 prime numbers between 100 and 200.",
    "Escreva um haicai sobre o oceano.",
]

CONFIGS = [
    ("CPU-2P",   "CPU", {0, 2},        {"INFERENCE_NUM_THREADS": "2",
                                         "SCHEDULING_CORE_TYPE": "PCORE_ONLY"}),
    ("CPU-4P",   "CPU", {0, 1, 2, 3},  {"INFERENCE_NUM_THREADS": "4",
                                         "SCHEDULING_CORE_TYPE": "PCORE_ONLY"}),
    ("CPU-all",  "CPU", set(range(12)),{"INFERENCE_NUM_THREADS": "12"}),
    ("GPU",      "GPU", set(range(12)),{}),
]

results = []

for label, device, affinity, extra in CONFIGS:
    print(f"\n{'═' * 60}")
    print(f"🧪 {label} ({device}, affinity={sorted(affinity)})")
    print(f"{'═' * 60}")

    os.sched_setaffinity(0, affinity)
    cfg_ov = {
        "PERFORMANCE_HINT": "LATENCY",
        "CACHE_DIR": f"./ov_cache_{label}",
        **extra,
    }

    try:
        t0 = time.time()
        pipe = ov_genai.LLMPipeline(MODEL_DIR, device, **cfg_ov)
        load_t = time.time() - t0
        print(f"✅ Load: {load_t:.1f}s")
    except Exception as e:
        print(f"❌ Failed: {e}")
        results.append((label, "FAIL", "FAIL", str(e)[:60]))
        continue

    gen_cfg = ov_genai.GenerationConfig()
    gen_cfg.max_new_tokens = 100
    gen_cfg.do_sample = False

    # 🔥 Warmup
    _ = pipe.generate([{"role":"user","content":"Hi"}], gen_cfg)

    # 📊 Measure across prompts
    tps_list, ttft_list = [], []
    for p in PROMPTS:
        history = [{"role":"user","content":p}]
        r = pipe.generate(history, gen_cfg)
        m = r.perf_metrics
        tps_list.append(m.get_throughput().mean)
        ttft_list.append(m.get_ttft().mean)
        print(f"  📝 {p[:40]:<40} → {tps_list[-1]:.2f} tok/s, "
              f"TTFT {ttft_list[-1]:.0f}ms")

    avg_tps = sum(tps_list) / len(tps_list)
    avg_ttft = sum(ttft_list) / len(ttft_list)
    results.append((label, f"{avg_tps:.2f}", f"{avg_ttft:.0f}", f"{load_t:.1f}s"))
    del pipe

# 📊 Final table
print(f"\n\n{'═' * 60}")
print(f"📊 RESULTS — {MODEL_DIR}")
print(f"{'═' * 60}")
print(f"{'Config':<10} {'tok/s':>8} {'TTFT (ms)':>12} {'Load':>10}")
print("─" * 50)
for label, tps, ttft, load in results:
    print(f"{label:<10} {tps:>8} {ttft:>12} {load:>10}")
