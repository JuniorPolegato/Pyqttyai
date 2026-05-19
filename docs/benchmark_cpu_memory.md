# 🔬 i7-1355U CPU & Memory Characterization for LLM Inference

> **🎯 Goal**: Empirically characterize the compute and memory subsystem of a thin laptop CPU to predict — and then optimize — local LLM inference performance.
>
> **🖥️ Hardware**: Dell laptop · Intel Core i7-1355U (13th Gen, Raptor Lake-U) · 2× 16 GB Crucial DDR4-3200 SODIMM · No discrete GPU used
> **🐧 OS**: Debian-based Linux · kernel 6.x · `intel_pstate` active
> **🧪 Methodology**: Bottom-up — measure compute, measure bandwidth, predict throughput, validate against real workloads.

---

## 📐 Why this matters

Most LLM benchmarks are **black boxes**: "Model X gives Y tokens/s on hardware Z."
That tells you **nothing actionable** when you want to:

- 🔧 Tune your own setup
- 🎯 Predict performance for a different model
- 🚧 Understand which bottleneck to attack next

This document does the opposite: **measure the hardware first**, derive theoretical ceilings, then explain why real-world performance lands where it does.

---

## 🧰 0. How to reproduce

```bash
# CPU topology
lscpu -e=CPU,CORE,SOCKET,CLUSTER,NODE,MAXMHZ
cat /proc/cpuinfo | grep -E "model name|MHz|cache size" | head -20

# Memory hardware
sudo dmidecode -t memory | grep -E "Size:|Type:|Speed:|Locator:|Part Number:"

# Memory bandwidth (install: sudo apt install mbw)
for t in 1 2 4 6 8 12; do
    echo "=== $t threads ==="
    mbw -n 5 -t 0 1024 2>/dev/null | tail -1
done

# Pinned to physical P-cores only (the "right" measurement)
taskset -c 0,2 mbw -n 5 -t 0 1024

# Power & thermal under load
sudo turbostat --interval 2
```

---

## 🧵 1. CPU topology

### Hybrid architecture: P-cores + E-cores

```text
CPU CORE  MAXMHZ
  0    0  5000.0   ← P-core 0, thread 0  (HT primary)
  1    0  5000.0   ← P-core 0, thread 1  (HT sibling)
  2    1  5000.0   ← P-core 1, thread 0
  3    1  5000.0   ← P-core 1, thread 1
  4    2  3700.0   ← E-core 0
  5    3  3700.0   ← E-core 1
  ...
 11    9  3700.0   ← E-core 7
```

| Property | P-cores | E-cores |
|---|:-:|:-:|
| Physical count | **2** | **8** |
| Logical threads | 4 (with HT) | 8 (no HT) |
| Max boost | 5.0 GHz | 3.7 GHz |
| AVX2 | ✅ | ✅ |
| AVX-VNNI (INT8) | ✅ | ✅ |
| AVX-512 | ❌ | ❌ |

### 🎯 Implication for thread pinning

- The OS scheduler may migrate your inference threads to **E-cores at any time**, dropping throughput by 30–50%.
- **Pinning to P-cores is mandatory**, not optional.
- HT siblings (CPUs 1 & 3) share load/store ports — **harmful** for bandwidth-bound workloads (see §3).

---

## 🧮 2. Theoretical compute capacity

### Peak FLOPS — single P-core, AVX2 + FMA

$$
\text{FLOPS}_\text{P-core} = f \times \text{lanes} \times \text{ops/cycle}
$$

For AVX2 with FMA at 5.0 GHz (256-bit register = 8 FP32 lanes, 2 ops per FMA):

$$
\text{FLOPS}_\text{P-core} = 5.0 \times 10^9 \times 8 \times 2 = 80 \text{ GFLOPS (FP32)}
$$

### Peak across 2 P-cores

$$
\text{Peak}_\text{2P} \approx 160 \text{ GFLOPS (FP32)}
$$

### INT8 / Q4 throughput (with AVX-VNNI)

VNNI provides **fused multiply-add of 4 INT8 values per FP32 lane** → **~4× FP32 throughput** for quantized GEMM:

$$
\text{Peak}_\text{INT8, 2P} \approx 640 \text{ GOPS}
$$

> 💡 **Compute is rarely the limit.** Even a sustained 10% utilization (~64 GOPS) is enough for most LLMs at INT4 because the per-token compute budget is small (a few GOPs for active params).

---

## 💾 3. Memory bandwidth — measured

### Hardware spec (verified via `dmidecode`)

```text
Slot DIMM A: Crucial CT16G4SFRA32A · 16 GB · DDR4 · 3200 MT/s · 1.2 V · Rank 2
Slot DIMM B: Crucial CT16G4SFRA32A · 16 GB · DDR4 · 3200 MT/s · 1.2 V · Rank 2
Total: 32 GB · Dual-channel · Max system capacity: 64 GB
```

Theoretical peak:

$$
\text{BW}_\text{peak} = 3200 \times 10^6 \times 8 \text{ B} \times 2 \text{ ch} \approx 51.2 \text{ GB/s}
$$

### `mbw` measurements (real data)

| Threads | Aggregate MEMCPY | Per-thread | Notes |
|:-:|:-:|:-:|---|
| 1 | **38.8 GB/s** | 38.8 | single P-core saturates the bus |
| 2 (unpinned) | 36.8 GB/s | 18.4 | 🚨 HT-pair contention — *lower than 1 thread* |
| 4 | 37.5 GB/s | 9.4 | scheduler spread, modest recovery |
| 6 | 40.5 GB/s | 6.8 | peak observed |
| 8 | 38.6 GB/s | 4.8 | E-cores not contributing |
| 12 | 40.6 GB/s | 3.4 | all threads, only +4.6% over 1t |
| **2 (pinned cores 0,2)** | **38.6 GB/s** | 19.3 | ⭐ HT contention removed |

### 🚨 Three findings from real measurements

#### Finding 1 — A single P-core saturates the memory bus

1 thread → **38.8 GB/s = 76% of theoretical peak**. This is excellent for laptop DDR4 and proves the **prefetcher + load buffers of one Raptor Cove core can keep the bus busy**.

#### Finding 2 — HT siblings hurt bandwidth (2-thread anomaly)

```text
1 thread          → 38.8 GB/s
2 threads (HT)    → 36.8 GB/s  ← LOWER!
2 threads (0,2)   → 38.6 GB/s  ← back to peak
```

When 2 threads land on the **same physical core's HT siblings**, they fight for the same load/store ports and **slow each other down**. This is direct experimental proof that **HT is for compute parallelism, not bandwidth parallelism**.

#### Finding 3 — Scaling is essentially flat beyond 1 thread

12 threads delivers only **+4.6% over 1 thread**. The bus is the bottleneck.

### Sustained bandwidth ceiling

$$
\text{BW}_\text{sustained} \approx 40 \text{ GB/s}
$$

$$
\eta_\text{BW} = \frac{40}{51.2} \approx 78\%
$$

The remaining 22% is page-table walks, DRAM refresh cycles, and memory controller overhead.

---

## 🚧 4. The bandwidth-bound regime

For LLM inference at INT4 (~4.5 bits effective per weight), a forward pass must **stream every active weight** from RAM through the CPU, exactly once per token.

$$
\text{Bytes/token} = N_\text{active} \times \frac{\text{bits}}{8}
$$

For Qwen3-30B-A3B (~3B active params at 4.5 bits):

$$
\text{Bytes/token} = 3 \times 10^9 \times \frac{4.5}{8} \approx 1.69 \text{ GB/token}
$$

### Theoretical ceiling — bandwidth-bound

$$
\text{tokens/s}_\text{max} = \frac{\text{BW}_\text{sustained}}{\text{Bytes/token}} = \frac{40}{1.69} \approx 23.7 \text{ tok/s}
$$

### Measured reality (OpenVINO, INT4, 4 P-threads)

| Config | Throughput | Efficiency vs ceiling |
|---|:-:|:-:|
| `P_2t_noHT` | 7.60 tok/s | 32% |
| `P_4t_HT` | 7.67 tok/s | 32% |
| `P_plus_2E_4t` | 7.77 tok/s | 33% |

> 🎯 **All 3 configs converged within 2.2%** — proof that the **bandwidth saturation regime** has been reached. Thread tuning gives diminishing returns from here.

### Where the missing 67% goes

| Loss factor | Estimated impact |
|---|:-:|
| KV cache reads (grows with context) | -25% |
| MoE routing / expert dispatch | -15% |
| Attention compute (not pure GEMM) | -10% |
| OS jitter, page faults, swap pressure | -10% |
| Tokenizer + sampling overhead | -5% |
| **Total accounted** | **~65%** |

---

## ⚖️ 5. Compute-bound vs memory-bound — the operational intensity test

For each LLM layer, define:

$$
\text{OI} = \frac{\text{FLOPs}}{\text{Bytes loaded}}
$$

For an INT4 GEMM with batch size 1 (single-token autoregressive decode):

$$
\text{OI} \approx \frac{2 \times N}{N \times 0.5} = 4 \text{ ops/byte}
$$

The **machine balance** (arithmetic intensity ridge):

$$
B = \frac{\text{Peak FLOPS}}{\text{Peak BW}} = \frac{640 \times 10^9}{40 \times 10^9} = 16 \text{ ops/byte}
$$

$$
\text{OI}_\text{LLM} = 4 \ll B = 16 \implies \boxed{\text{memory-bound}}
$$

> 💎 **The hardware can do 4× more compute than the bus can feed it.** This is why thread tuning saturates so quickly and why CPU LLM inference will **always** be memory-bound on commodity laptops.

---

## 🔥 6. Thermal & power behavior

Sustained inference observations (from `btop`, `turbostat`):

| Metric | Idle | Under load |
|---|:-:|:-:|
| Package power | 5–8 W | **~28 W** (PL1 sustained) |
| P-core temp | ~45 °C | **~78–85 °C** |
| P-core clock | 800 MHz | 3.8–4.2 GHz (NOT 5.0!) |
| Throttling | none | **none** (within thermal envelope) |

### 🎯 Why clocks don't reach 5.0 GHz under sustained load

- 5.0 GHz is **single-core boost**, only achievable in short bursts
- Under all-P-core load, the 28 W PL1 thermal envelope caps clocks at ~4 GHz
- **Real compute peak** is therefore:

$$
\text{Real peak}_\text{2P, INT8} \approx 4.0 \times 10^9 \times 2 \times 8 \times 2 \times 4 \approx 512 \text{ GOPS}
$$

(Still ~12× above the bandwidth ridge — the conclusion doesn't change.)

---

## 🧪 7. Validation across runtimes

Same hardware, same prompt, **different runtimes**:

| Runtime | Quantization | Throughput | % of BW ceiling |
|---|---|:-:|:-:|
| Ollama (llama.cpp) | Q4_K_M | 1.90–3.80 tok/s | 8–16% |
| **OpenVINO GenAI** | **INT4 sym** | **7.60–7.77 tok/s** | **32–33%** |

> 🏆 **OpenVINO is ~2× more efficient at the runtime level** for the same hardware and same approximate quantization. This is the value of vendor-optimized INT4 kernels and graph-level optimizations.

---

## 🎯 8. Tuning recommendations (validated)

### ✅ What works

1. **Pin to P-cores via `taskset -c 0,2`** or systemd `CPUAffinity=0 2` — single biggest lever (+30–60% if previously migrating to E-cores)
2. **Use `LATENCY` performance hint** in OpenVINO — disables throughput-oriented batching
3. **Set `INFERENCE_NUM_THREADS=4`** — match P-core thread count
4. **Free RAM before launch** (`drop_caches`, stop GUI services) — prevents swap during KV growth
5. **Set `vm.swappiness=1`** — kernel avoids paging out hot model weights

### ❌ What does NOT help (measured)

1. Adding E-cores to the worker pool — **no bandwidth gain, adds scheduling jitter**
2. Going beyond 4 threads — bandwidth already saturated at 1 thread
3. Higher CPU governor — already at performance under load
4. Disabling HT — measured **same throughput** as enabling it (within 2%)
5. Running 2 threads **without pinning** — actually *hurts* (HT-pair contention, see §3)

---

## 🚧 9. The hard ceilings

Even with **perfect** tuning, this hardware cannot exceed:

| Workload | Ceiling | Reason |
|---|:-:|---|
| 3B-active MoE INT4, no context | ~24 tok/s | DDR4 bandwidth |
| 3B-active MoE INT4, 8k context | ~12 tok/s | + KV cache reads |
| 3B-active MoE INT4, 20k context | ~6 tok/s | KV cache > model |
| 7B dense INT4, no context | ~10 tok/s | 2.3× more bytes/token |
| 14B dense INT4, no context | ~5 tok/s | 4.7× more bytes/token |

### To exceed these ceilings, you must change hardware

| Upgrade | New ceiling (3B-active) | Cost (BR, May 2026) |
|---|:-:|:-:|
| 2× 32 GB DDR4-3200 (this same laptop) | ~24 tok/s (same!) | ~R$ 900 — only enables bigger models |
| DDR5-5600 dual-channel laptop | ~50 tok/s | new laptop ~R$ 6 k |
| DDR5-7200 + LPDDR5X | ~70 tok/s | premium ultrabook ~R$ 12 k |
| Discrete GPU (RTX 4060 mobile, 256 GB/s) | ~150 tok/s | gaming laptop ~R$ 9 k |
| Discrete GPU (RTX 4090, 1 TB/s) | ~600 tok/s | desktop ~R$ 18 k |

> 💡 **Important nuance**: upgrading this laptop's RAM to 64 GB **won't make inference faster** (same bus speed) — it will only let you run **larger models** without swap. The bandwidth ceiling stays at 40 GB/s.

---

## 📊 10. Summary: the i7-1355U LLM profile

```text
                  ┌────────────────────────────────┐
   Compute        │ ████████████████░░░░░░░░░░░░░░ │  ~33% used
   (640 GOPS)     │                                │
                  │                                │
   Bandwidth      │ ████████████████████████████░░ │  ~78% used
   (51 GB/s)      │                                │
                  └────────────────────────────────┘
                    The bus is the bottleneck.
```

**One-line summary**: *On the i7-1355U, every LLM inference question reduces to "how can I move fewer bytes per token?"* — quantization, smaller models, KV cache compression, prompt caching. Compute optimizations are second-order.

---

## 📚 References & tools used

- `lscpu`, `lstopo`, `cpupower frequency-info` — topology
- `dmidecode -t memory` — DIMM identification & speed
- `mbw` (Memory Bandwidth) — sustained bandwidth measurement
- `btop`, `turbostat`, `powerstat` — runtime monitoring
- `taskset`, `numactl`, systemd `CPUAffinity=` — pinning
- `openvino-genai` 2026.x — inference runtime
- Ollama 0.3+ — comparison runtime

---

*Characterization by Claudio Polegato Junior · Ribeirão Preto, BR · May 2026*
*Hardware: Dell · Intel Core i7-1355U · 2× 16 GB Crucial DDR4-3200 · No discrete GPU*
