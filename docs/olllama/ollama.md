sudo systemclt edit ollama.service

lscpu -e=CPU,CORE,MAXMHZ

ollama create qwen3-vl:2b_4cpu -f <(sed 's/#.*//' Modelfile_qwen3-vl:2b_4cpu)


# Optimizing Ollama for Hybrid CPU Architectures (P-Cores vs. E-Cores)

For processors with a hybrid architecture (like the i7-1355U), managing how Large Language Models (LLMs) utilize Performance (P) and Efficiency (E) cores is critical for maintaining high inference speeds.

## 1. Thread Selection: Physical P-Cores vs. Hyper-threading
For LLM inference (Ollama/llama.cpp), it is generally better to use **physical P-cores only** rather than including their logical hyper-threads.

* **The Cache Bottleneck:** LLM inference is heavily bound by memory bandwidth and L1/L2 cache access. 
* **Performance Hit:** Hyper-threading splits the pipeline of a single physical core. When two threads try to process large model weights through the same cache simultaneously, "cache thrashing" occurs, often resulting in lower tokens-per-second (t/s) than using physical cores alone.

**Recommendation:** Use a thread count equal to your physical P-cores (e.g., 2 threads for 2 P-cores).

## 2. Core Discovery and Pinning (CPU Affinity)
On Linux systems, you can isolate Ollama to specific high-performance cores to prevent it from being scheduled on slower E-cores.

### Step A: Discover the Core Topology
Identify which CPU IDs correspond to your P-cores by checking their maximum frequencies:
```bash
lscpu -e=CPU,CORE,MAXMHZ
```
*P-cores will show significantly higher MAXMHZ values (e.g., 5000MHz) compared to E-cores.*

### Step B: Configure CPU Affinity in Systemd
1.  Edit the Ollama service override:
    ```bash
    sudo systemctl edit ollama.service
    ```
2.  Add the `CPUAffinity` directive under the `[Service]` section (replace `0,1` with your actual P-core CPU IDs):
    ```ini
    [Service]
    CPUAffinity=0,1
    Environment="OLLAMA_NUM_PARALLEL=1"
    ```
3.  Reload and restart the service:
    ```bash
    sudo systemctl daemon-reload
    sudo systemctl restart ollama
    ```

## 3. Maximize Clock Speeds (CPU Governor)
To ensure the P-cores operate at their maximum frequency without latency spikes, switch the Linux CPU governor to `performance`.

1.  **Install the management tool:**
    ```bash
    sudo apt update && sudo apt install linux-cpupower
    ```
2.  **Set the governor to performance:**
    ```bash
    sudo cpupower frequency-set -g performance
    ```

## 4. Thermal Management Warning
Forcing P-cores to run at 100% speed during long inference tasks (like processing a 35B model) generates significant heat.
* **Thermal Throttling:** If the CPU hits its thermal limit (TJMax), the hardware will automatically downclock to protect itself.
* **Monitoring:** It is recommended to monitor temperatures during heavy use. Sometimes allowing the system to scale frequencies naturally provides better sustained performance by avoiding aggressive thermal throttling.



# Updated CPU Pinning for i7-1355U

```lscpu -e=CPU,CORE,SOCKET,CLUSTER,NODE,MAXMHZ                                                                                                                                            ─╯

CPU CORE SOCKET CLUSTER NODE    MAXMHZ
  0    0      0       -    0 5000.0000
  1    0      0       -    0 5000.0000
  2    1      0       -    0 5000.0000
  3    1      0       -    0 5000.0000
  4    2      0       -    0 3700.0000
  5    3      0       -    0 3700.0000
  6    4      0       -    0 3700.0000
  7    5      0       -    0 3700.0000
  8    6      0       -    0 3700.0000
  9    7      0       -    0 3700.0000
 10    8      0       -    0 3700.0000
 11    9      0       -    0 3700.0000
```

Based on your `lscpu` output, your P-cores are mapped as follows:
* **Core 0:** CPUs 0 and 1
* **Core 1:** CPUs 2 and 3

To maximize performance for **Qwen 3.6:35b**, you should pin Ollama to one thread per physical core.

## 1. Apply CPU Affinity
1.  Open the service override:
    ```bash
    sudo systemctl edit ollama.service
    ```
2.  Update the `[Service]` block:
    ```ini
    [Service]
    CPUAffinity=0,2
    Environment="OLLAMA_NUM_PARALLEL=1"
    ```
3.  Reload and restart:
    ```bash
    sudo systemctl daemon-reload
    sudo systemctl restart ollama
    ```

## 2. Verify Thread Count
When you run the model, ensure Ollama is actually using only 2 threads. You can check this in the terminal where you run the model or by looking at `btop`. If it tries to use more, it will spill over into the E-cores (CPUs 4-11), which will slow down the overall generation speed because the P-cores will have to wait for the slower E-cores to finish their calculations.

## 3. Why this works
By using **0 and 2**, you are giving Ollama the full "attention" of your two fastest physical cores without the interference of hyper-threading. This is the "sweet spot" for memory-heavy tasks like LLM inference on mobile chips.
