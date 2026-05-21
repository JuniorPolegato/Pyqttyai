#!/usr/bin/env python3
"""
Benchmark OpenVINO GenAI on i7-1355U (2P + 8E cores).
Tests different P/E core combinations and performance hints.
Run with: python3 bench_pe.py
(do NOT prepend taskset — the script uses os.sched_setaffinity per run)
"""
import openvino_genai as ov_genai
import time
import gc
import os

MODEL_DIR  = "qwen3_moe_int4_ov"
DEVICE     = "CPU"
PROMPT     = "Por que o céu é azul?"
MAX_TOKENS = 200
N_RUNS     = 2
CACHE_ROOT = "/var/huggingface"

# CPU topology of i7-1355U:
#   P-cores: logical CPUs 0,1 (core0)  and 2,3 (core1)  -> HT pairs
#   E-cores: logical CPUs 4..11 (no HT)
CONFIGS = [
    # name,           hint,        affinity,           ov_threads
    ("P_2t_noHT",    "LATENCY",   {0, 2},             2),   # gold standard
    ("P_4t_HT",      "LATENCY",   {0, 1, 2, 3},       4),   # +HT for stall hiding
    ("P_plus_2E_4t", "LATENCY",   {0, 2, 4, 5},       4),   # P + 2E, no HT
]


def run(name, hint, affinity, threads):
    print(f"\n{'='*70}")
    print(f"🧪 {name}  hint={hint}  cpus={sorted(affinity)}  ov_threads={threads}")
    print(f"{'='*70}")

    # Pin THIS process to the chosen CPUs
    os.sched_setaffinity(0, affinity)

    properties = {
        "PERFORMANCE_HINT":      hint,
        "INFERENCE_NUM_THREADS": threads,
        "CACHE_DIR":             f"{CACHE_ROOT}/ov_cache_{name}",
    }

    t0 = time.perf_counter()
    pipe = ov_genai.LLMPipeline(MODEL_DIR, DEVICE, **properties)
    load_s = time.perf_counter() - t0
    print(f"📦 Load/compile: {load_s:.1f} s")

    gen_cfg = ov_genai.GenerationConfig()
    gen_cfg.max_new_tokens      = MAX_TOKENS
    gen_cfg.do_sample           = False
    gen_cfg.apply_chat_template = True

    runs = []
    for i in range(N_RUNS):
        print(f"  ▶ Run {i+1}/{N_RUNS} ...", end=" ", flush=True)
        t0 = time.perf_counter()
        result = pipe.generate([PROMPT], gen_cfg)
        wall = time.perf_counter() - t0

        m = result.perf_metrics
        runs.append({
            "wall":       wall,
            "ttft":       m.get_ttft().mean,
            "tpot":       m.get_tpot().mean,
            "throughput": m.get_throughput().mean,
            "n_out":      m.get_num_generated_tokens(),
        })
        print(f"{runs[-1]['throughput']:.2f} tok/s "
              f"(TTFT {runs[-1]['ttft']/1000:.1f}s, "
              f"TPOT {runs[-1]['tpot']:.0f}ms)")

    measured = runs[1:] if N_RUNS > 1 else runs
    avg = {k: sum(r[k] for r in measured) / len(measured)
           for k in ("wall", "ttft", "tpot", "throughput")}

    del pipe
    gc.collect()

    return {"name": name, "load_s": load_s, "avg": avg}


def summary(results):
    print(f"\n\n{'='*78}")
    print(f"📊 RESULTS  (avg of {N_RUNS-1} measured run(s), 1st = warm-up)")
    print(f"{'='*78}")
    print(f"{'Config':<22}{'Load(s)':>10}{'TTFT(s)':>10}"
          f"{'TPOT(ms)':>11}{'Tok/s':>10}{'Wall(s)':>10}")
    print("-" * 73)
    for r in results:
        a = r["avg"]
        print(f"{r['name']:<22}"
              f"{r['load_s']:>10.1f}"
              f"{a['ttft']/1000:>10.1f}"
              f"{a['tpot']:>11.1f}"
              f"{a['throughput']:>10.2f}"
              f"{a['wall']:>10.1f}")
    best = max(results, key=lambda r: r["avg"]["throughput"])
    print(f"\n🏆 Best: {best['name']} "
          f"({best['avg']['throughput']:.2f} tok/s)")


if __name__ == "__main__":
    print(f"🖥️  i7-1355U  |  device={DEVICE}  |  model={MODEL_DIR}")
    results = []
    for cfg in CONFIGS:
        try:
            results.append(run(*cfg))
        except Exception as e:
            print(f"❌ {cfg[0]} failed: {e}")
    if results:
        summary(results)
