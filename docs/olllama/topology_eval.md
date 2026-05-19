# Prepare

`curl -fsSL https://ollama.com/install.sh | sh`

`ollama pull qwen3.6:35b`

`nano Modelfile_qwen3.6:35b_cisco`
```
FROM qwen3.6:35b
PARAMETER num_thread 4           # 🧵 CPU threads 4 P-core
PARAMETER num_ctx 32768          # 📜 context window
PARAMETER num_batch 256          # 📦 batch size for prompt eval (default 512)
PARAMETER num_keep 24            # 🧠 keep N tokens from start on context shift
PARAMETER temperature 0.3        # 🎯 lower = more deterministic (good for configs)
PARAMETER top_k 40               # 🎲 sampling
PARAMETER top_p 0.9              # 🎲 sampling
PARAMETER repeat_penalty 1.1     # 🔁 avoid loops
PARAMETER stop "<|im_end|>"      # 🛑 Qwen's stop token

# Optional: bake in a system prompt
SYSTEM """You are a Cisco network configuration expert. Generate precise IOS configurations."""
```

`ollama create qwen3.6:35b_cisco -f <(sed 's/\s*#.*//' Modelfile_qwen3.6:35b_cisco)`

`cat /etc/systemd/system/ollamaservice`
```
[Unit]
Description=Ollama Service
After=network-online.target

[Service]
ExecStart=/usr/local/bin/ollama serve
User=ollama
Group=ollama
Restart=always
RestartSec=3
Environment="PATH=/home/junior/.nvm/versions/node/v24.14.1/bin:/home/junior/.local/bin:/home/junior/bin:/usr/lib/ccache:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/snap/bin:/home/junior/Android/Sdk/emulator:/home/junior/Android/Sdk/platform-tools:/home/junior/esp/xtensa-esp32-elf/bin:/opt/mssql-tools18/bin"

[Install]
WantedBy=default.target
```

`sudo systemctl edit ollama.service`
```
# /etc/systemd/system/ollama.service.d/override.conf
[Service]
CPUAffinity=0 1 2 3
Environment="OLLAMA_MODELS=/var/lib/ollama_storage"
Environment="CUDA_VISIBLE_DEVICES=-1"
Environment="OLLAMA_GPU_OVERHEAD=0"
Environment="OLLAMA_NUM_THREAD=4"
```

`sudo systemctl restart ollama.service`

```
time ollama run --verbose qwen3.6:35b_cisco '/home/junior/Projetos/pyqttyai/topologies/LAB_BGP_CCNP_ENARSI_AULA.png Describe this ENV-NG network diagram image in detail: Each cable segment has a network, connecting just 2 closer neighbors. Each interface has closer its a last IP octet. ASN has local network(s) next a router. I want a table with each line "ASN number | router number | interface | IP | network | neighbor number | neighbor interface", other table with "ASN number | ASN network | router closer publishing network". Include in tables columns for IPv4 and IPv6."'
```

# Thinking...

`Added image '/home/junior/Projetos/pyqttyai/topologies/LAB_BGP_CCNP_ENARSI_AULA.png'`

The user wants a detailed description of the provided network diagram, specifically formatted into two tables.

**Table 1: Link-by-Link Connectivity**
*   **Columns:** ASN number | router number | interface | IP | network | neighbor number | neighbor interface
*   **Requirement:** Include IPv4 and IPv6 columns.

**Table 2: ASN Network Summary**
*   **Columns:** ASN number | ASN network | router closer publishing network
*   **Requirement:** Include IPv4 and IPv6 columns.

**Step 1: Analyze the Diagram - ASN by ASN**

*   **ASN 1111 (Orange box):**
    *   Router R4.
    *   Local Network: 11.11.11.0/24, 11:11:11:11::/64.
    *   Interface e0/1 connects to R2 (ASN 3030). IP: .1 (11.11.11.1? No, wait, looking at the line).
    *   Let's trace the line from R4 e0/1. It goes to R2 e0/1.
    *   Network on that link: 40.40.40.0/30.
    *   R4 e0/1 IP: .2 (40.40.40.2).
    *   R2 e0/1 IP: .1 (40.40.40.1).

*   **ASN 1212 (Blue box):**
    *   Router R5.
    *   Local Network: 12.12.12.0/24, 12:12:12:12::/64.
    *   Interface e0/1 connects to R9 (ASN 2020).
    *   Network on that link: 60.60.60.0/30.
    *   R5 e0/1 IP: .1 (60.60.60.1).
    *   R9 e0/0 IP: .2 (60.60.60.2).
    *   Interface e0/0 connects to R4 (ASN 1111).
    *   Network on that link: 50.50.50.0/30.
    *   R5 e0/0 IP: .2 (50.50.50.2).
    *   R4 e0/0 IP: .1 (50.50.50.1).

*   **ASN 3030 (Grey oval):**
    *   Routers: R1, R2, R3.
    *   **R1:**
        *   Local: 30.30.30.0/24, 30:30:30::/64.
        *   e0/0 connects to R2. Network: 31.31.31.0/30. R1 e0/0: .1, R2 e0/0: .2.
        *   e0/1 connects to R3. Network: 31.31.31.4/30. R1 e0/1: .5, R3 e0/0: .6.
    *   **R2:**
        *   e0/1 connects to R4 (ASN 1111). Network: 40.40.40.0/30. R2 e0/1: .1, R4 e0/1: .2.
        *   e0/2 connects to R3. Network: 31.31.31.8/30. R2 e0/2: .10, R3 e0/3: .9.
    *   **R3:**
        *   e0/2 connects to R19 (ASN 1414). Network: 100.100.100.0/30. R3 e0/2: .1, R19 e0/0: .2.
        *   e0/1 connects to R8 (ASN 1313). Network: 90.90.90.0/30. R3 e0/1: .1, R8 e0/1: .2.
        *   e0/3 connects to R2 (ASN 3030). Network: 31.31.31.8/30. R3 e0/3: .9, R2 e0/2: .10. (Wait, let me re-check the R2-R3 link).
        *   Looking closely at R2-R3 link: R2 e0/2 is .10, R3 e0/3 is .9. Network is 31.31.31.8/30.
        *   Looking closely at R3-R8 link: R3 e0/1 is .1, R8 e0/1 is .2. Network is 90.90.90.0/30.

*   **ASN 1313 (Cyan box):**
    *   Routers: R6, R7, R8.
    *   **R6:**
        *   Local: 13.13.13.0/24, 13:13:13:13::/64.
        *   e0/0 connects to R7. Network: 13.14.14.0/30. R6 e0/0: .1, R7 e0/0: .2.
    *   **R7:**
        *   e0/1 connects to R8. Network: 13.15.15.0/30. R7 e0/1: .1, R8 e0/0: .2.
    *   **R8:**
        *   e0/1 connects to R3 (ASN 3030). Network: 90.90.90.0/30. R8 e0/1: .2, R3 e0/1: .1.
        *   e0/3 connects to R14 (ASN 1818). Network: 80.80.80.0/30. R8 e0/3: .1, R14 e0/1: .2.
        *   e0/2 connects to R11 (ASN 2020). Network: 70.70.70.0/30. R8 e0/2: .1, R11 e0/0: .2.

*   **ASN 1414 (Light Blue box):**
    *   Router R19.
    *   Local: 14.14.14.0/24, 14:14:14:14::/64.
    *   e0/1 connects to R20 (ASN 1515). Network: 110.110.110.0/30. R19 e0/1: .1, R20 e0/0: .2.
    *   e0/2 connects to R17 (ASN 1616). Network: 120.120.120.0/30. R19 e0/2: .1, R17 e0/0: .2.

*   **ASN 1515 (Light Green box):**
    *   Router R20.
    *   Local: 15.15.15.0/24, 15:15:15::/64.
    *   e0/1 connects to R18 (ASN 1717). Network: 170.170.170.0/30. R20 e0/1: .1, R18 e0/0: .2.

*   **ASN 1616 (Orange box):**
    *   Router R17.
    *   Local: 16.16.16.0/24, 16:16:16:16::/64.
    *   e0/1 connects to R14 (ASN 1818). Network: 140.140.140.0/30. R17 e0/1: .1, R14 e0/2: .2.
    *   e0/2 connects to R18 (ASN 1717). Network: 130.130.130.0/30. R17 e0/2: .1, R18 e0/2: .2.

*   **ASN 1717 (Pink box):**
    *   Router R18.
    *   Local: 17.17.17.0/24, 17:17:17:17::/64.
    *   e0/1 connects to R16 (ASN 1919). Network: 160.160.160.0/30. R18 e0/1: .1, R16 e0/0: .2.

*   **ASN 1818 (Yellow box):**
    *   Routers: R14, R15.
    *   **R14:**
        *   Local: 18.20.20.0/30 (Wait, looking at the label "18.20.20.0/30" near R14/R15 link).
        *   Actually, looking at the text near R14/R15: "18.20.20.0/30".
        *   R14 e0/0 connects to R15 e0/0. R14 e0/0: .1, R15 e0/0: .2.
        *   e0/1 connects to R8 (ASN 1313). Network: 80.80.80.0/30. R14 e0/1: .2, R8 e0/3: .1.
        *   e0/2 connects to R17 (ASN 1616). Network: 140.140.140.0/30. R14 e0/2: .2, R17 e0/1: .1.
    *   **R15:**
        *   Local: 18.18.18.0/24, 18:18:18:18::/64.
        *   e0/1 connects to R16 (ASN 1919). Network: 150.150.150.0/30. R15 e0/1: .1, R16 e0/1: .2.

*   **ASN 1919 (Light Blue box):**
    *   Router R16.
    *   Local: 19.19.19.0/24, 19:19:19:19::/64.
    *   e0/0 connects to R15 (ASN 1818). Network: 150.150.150.0/30. R16 e0/1: .2, R15 e0/1: .1. (Wait, looking at the diagram, R16 e0/1 connects to R15 e0/1? No, R16 e0/1 connects to
R15 e0/1? Let's check the line).
    *   Line from R15 e0/1 goes to R16 e0/1. Network: 150.150.150.0/30.
    *   Wait, let's look at the label "160.160.160.0/30" near R18/R16.
    *   R18 e0/1 connects to R16 e0/0. Network: 160.160.160.0/30. R18 e0/1: .1, R16 e0/0: .2.
    *   Wait, let's re-read the R15-R16 link.
    *   R15 e0/1 connects to R16 e0/1. Network: 150.150.150.0/30. R15 e0/1: .1, R16 e0/1: .2.
    *   Wait, looking at the diagram again.
    *   R15 e0/1 connects to R16 e0/1. Network label is "150.150.150.0/30".
    *   R18 e0/1 connects to R16 e0/0. Network label is "160.160.160.0/30".

*   **ASN 2020 (Green box - EIGRP 100):**
    *   Routers: R9, R10, R11, R12, R13.
    *   **R9:**
        *   Local: 10.10.10.1/32 (Loopback).
        *   e0/0 connects to R5 (ASN 1212). Network: 60.60.60.0/30. R9 e0/0: .2, R5 e0/1: .1.
        *   e0/1 connects to R10. Network: 21.21.21.0/30. R9 e0/1: .2, R10 e0/0: .1.
        *   e0/2 connects to R12. Network: 21.21.21.16/30. R9 e0/2: .17, R12 e0/1: .18.
    *   **R10:**
        *   Local: 10.10.10.2/32.
        *   e0/1 connects to R11. Network: 21.21.21.4/30. R10 e0/1: .5, R11 e0/1: .6.
        *   e0/2 connects to R12. Network: 21.21.21.12/30. R10 e0/2: .13, R12 e0/0: .14.
        *   e0/3 connects to R13. Network: 21.21.21.8/30. R10 e0/3: .9, R13 e0/1: .10.
    *   **R11:**
        *   Local: 10.10.10.3/32.
        *   e0/0 connects to R8 (ASN 1313). Network: 70.70.70.0/30. R11 e0/0: .2, R8 e0/2: .1.
        *   e0/2 connects to R13. Network: 21.21.21.20/30. R11 e0/2: .21, R13 e0/0: .22.
    *   **R12:**
        *   Local: 25.25.25.0/24, 25:25:25:25::/64.
        *   e0/1 connects to R9. Network: 21.21.21.16/30. R12 e0/1: .18, R9 e0/2: .17.
        *   e0/0 connects to R10. Network: 21.21.21.12/30. R12 e0/0: .14, R10 e0/2: .13.
    *   **R13:**
        *   Local: 20.20.20.0/24, 20:20:20::/64.
        *   e0/0 connects to R11. Network: 21.21.21.20/30. R13 e0/0: .22, R11 e0/2: .21.
        *   e0/1 connects to R10. Network: 21.21.21.8/30. R13 e0/1: .10, R10 e0/3: .9.

**Step 2: Construct Table 1 (Link Connectivity)**

I need to be careful with the "closer IP octet" rule.
*   R4 (ASN 1111) e0/1 -> R2 (ASN 3030) e0/1. Network 40.40.40.0/30. R4 is .2, R2 is .1.
*   R5 (ASN 1212) e0/0 -> R4 (ASN 1111) e0/0. Network 50.50.50.0/30. R5 is .2, R4 is .1.
*   R5 (ASN 1212) e0/1 -> R9 (ASN 2020) e0/0. Network 60.60.60.0/30. R5 is .1, R9 is .2.
*   R1 (ASN 3030) e0/0 -> R2 (ASN 3030) e0/0. Network 31.31.31.0/30. R1 is .1, R2 is .2.
*   R1 (ASN 3030) e0/1 -> R3 (ASN 3030) e0/0. Network 31.31.31.4/30. R1 is .5, R3 is .6.
*   R2 (ASN 3030) e0/1 -> R4 (ASN 1111) e0/1. Network 40.40.40.0/30. R2 is .1, R4 is .2.
*   R2 (ASN 3030) e0/2 -> R3 (ASN 3030) e0/3. Network 31.31.31.8/30. R2 is .10, R3 is .9.
*   R3 (ASN 3030) e0/2 -> R19 (ASN 1414) e0/0. Network 100.100.100.0/30. R3 is .1, R19 is .2.
*   R3 (ASN 3030) e0/1 -> R8 (ASN 1313) e0/1. Network 90.90.90.0/30. R3 is .1, R8 is .2.
*   R6 (ASN 1313) e0/0 -> R7 (ASN 1313) e0/0. Network 13.14.14.0/30. R6 is .1, R7 is .2.
*   R7 (ASN 1313) e0/1 -> R8 (ASN 1313) e0/0. Network 13.15.15.0/30. R7 is .1, R8 is .2.
*   R8 (ASN 1313) e0/3 -> R14 (ASN 1818) e0/1. Network 80.80.80.0/30. R8 is .1, R14 is .2.
*   R8 (ASN 1313) e0/2 -> R11 (ASN 2020) e0/0. Network 70.70.70.0/30. R8 is .1, R11 is .2.
*   R19 (ASN 1414) e0/1 -> R20 (ASN 1515) e0/0. Network 110.110.110.0/30. R19 is .1, R20 is .2.
*   R19 (ASN 1414) e0/2 -> R17 (ASN 1616) e0/0. Network 120.120.120.0/30. R19 is .1, R17 is .2.
*   R20 (ASN 1515) e0/1 -> R18 (ASN 1717) e0/0. Network 170.170.170.0/30. R20 is .1, R18 is .2.
*   R17 (ASN 1616) e0/1 -> R14 (ASN 1818) e0/2. Network 140.140.140.0/30. R17 is .1, R14 is .2.
*   R17 (ASN 1616) e0/2 -> R18 (ASN 1717) e0/2. Network 130.130.130.0/30. R17 is .1, R18 is .2.
*   R18 (ASN 1717) e0/1 -> R16 (ASN 1919) e0/0. Network 160.160.160.0/30. R18 is .1, R16 is .2.
*   R14 (ASN 1818) e0/0 -> R15 (ASN 1818) e0/0. Network 18.20.20.0/30. R14 is .1, R15 is .2.
*   R15 (ASN 1818) e0/1 -> R16 (ASN 1919) e0/1. Network 150.150.150.0/30. R15 is .1, R16 is .2.
*   R9 (ASN 2020) e0/1 -> R10 (ASN 2020) e0/0. Network 21.21.21.0/30. R9 is .2, R10 is .1.
*   R9 (ASN 2020) e0/2 -> R12 (ASN 2020) e0/1. Network 21.21.21.16/30. R9 is .17, R12 is .18.
*   R10 (ASN 2020) e0/1 -> R11 (ASN 2020) e0/1. Network 21.21.21.4/30. R10 is .5, R11 is .6.
*   R10 (ASN 2020) e0/2 -> R12 (ASN 2020) e0/0. Network 21.21.21.12/30. R10 is .13, R12 is .14.
*   R10 (ASN 2020) e0/3 -> R13 (ASN 2020) e0/1. Network 21.21.21.8/30. R10 is .9, R13 is .10.
*   R11 (ASN 2020) e0/2 -> R13 (ASN 2020) e0/0. Network 21.21.21.20/30. R11 is .21, R13 is .22.

**Step 3: Construct Table 2 (ASN Networks)**

*   ASN 1111: 11.11.11.0/24, 11:11:11:11::/64 (R4)
*   ASN 1212: 12.12.12.0/24, 12:12:12:12::/64 (R5)
*   ASN 3030: 30.30.30.0/24, 30:30:30::/64 (R1)
*   ASN 1313: 13.13.13.0/24, 13:13:13:13::/64 (R6)
*   ASN 1414: 14.14.14.0/24, 14:14:14:14::/64 (R19)
*   ASN 1515: 15.15.15.0/24, 15:15:15::/64 (R20)
*   ASN 1616: 16.16.16.0/24, 16:16:16:16::/64 (R17)
*   ASN 1717: 17.17.17.0/24, 17:17:17:17::/64 (R18)
*   ASN 1818: 18.18.18.0/24, 18:18:18:18::/64 (R15)
*   ASN 1919: 19.19.19.0/24, 19:19:19:19::/64 (R16)
*   ASN 2020: 25.25.25.0/24, 25:25:25:25::/64 (R12) AND 20.20.20.0/24, 20:20:20::/64 (R13). Wait, looking at the diagram, R12 has 25.25.25.0/24 and R13 has 20.20.20.0/24. Both are
inside the ASN 2020 box. So ASN 2020 has two local networks.

**Refining Table 1 Columns:**
ASN number | router number | interface | IP (IPv4) | Network (IPv4) | Neighbor number | Neighbor interface | IP (IPv6) | Network (IPv6)

Wait, the prompt asks for: "ASN number | router number | interface | IP | network | neighbor number | neighbor interface". And "Include in tables columns for IPv4 and IPv6."
So I need to split the IP and Network columns or add suffixes.
Let's do:
ASN | Router | Interface | IPv4 IP | IPv4 Network | Neighbor | Neighbor Interface | IPv6 IP | IPv6 Network

Actually, the prompt says "Each cable segment has a network... Each interface has closer its a last IP octet."
So for IPv6, the last octet (or hextet) usually matches the IPv4 last octet in these labs.
Example: 40.40.40.0/30 -> R4 is .2, R2 is .1.
IPv6: 40:40:40::/64? No, usually it's a /64 link.
Let's look at the labels.
"11.11.11.0/24" -> "11:11:11:11::/64".
"30.30.30.0/24" -> "30:30:30::/64".
"13.13.13.0/24" -> "13:13:13:13::/64".
"14.14.14.0/24" -> "14:14:14:14::/64".
"15.15.15.0/24" -> "15:15:15::/64".
"16.16.16.0/24" -> "16:16:16:16::/64".
"17.17.17.0/24" -> "17:17:17:17::/64".
"18.18.18.0/24" -> "18:18:18:18::/64".
"19.19.19.0/24" -> "19:19:19:19::/64".
"25.25.25.0/24" -> "25:25:25:25::/64".
"20.20.20.0/24" -> "20:20:20::/64".

For the link networks (e.g., 40.40.40.0/30), the IPv6 is usually derived.
Looking at R1/R2 link: 31.31.31.0/30. No IPv6 label.
Looking at R4/R5 link: 50.50.50.0/30. No IPv6 label.
Looking at R5/R9 link: 60.60.60.0/30. No IPv6 label.
Looking at R3/R19 link: 100.100.100.0/30. No IPv6 label.
Looking at R3/R8 link: 90.90.90.0/30. No IPv6 label.
Looking at R6/R7 link: 13.14.14.0/30. No IPv6 label.
Looking at R7/R8 link: 13.15.15.0/30. No IPv6 label.
Looking at R8/R14 link: 80.80.80.0/30. No IPv6 label.
Looking at R8/R11 link: 70.70.70.0/30. No IPv6 label.
Looking at R19/R20 link: 110.110.110.0/30. No IPv6 label.
Looking at R19/R17 link: 120.120.120.0/30. No IPv6 label.
Looking at R20/R18 link: 170.170.170.0/30. No IPv6 label.
Looking at R17/R14 link: 140.140.140.0/30. No IPv6 label.
Looking at R17/R18 link: 130.130.130.0/30. No IPv6 label.
Looking at R18/R16 link: 160.160.160.0/30. No IPv6 label.
Looking at R14/R15 link: 18.20.20.0/30. No IPv6 label.
Looking at R15/R16 link: 150.150.150.0/30. No IPv6 label.
Looking at R9/R10 link: 21.21.21.0/30. No IPv6 label.
Looking at R9/R12 link: 21.21.21.16/30. No IPv6 label.
Looking at R10/R11 link: 21.21.21.4/30. No IPv6 label.
Looking at R10/R12 link: 21.21.21.12/30. No IPv6 label.
Looking at R10/R13 link: 21.21.21.8/30. No IPv6 label.
Looking at R11/R13 link: 21.21.21.20/30. No IPv6 label.

Wait, looking at the diagram again, there are IPv6 labels for the *local* networks (the big boxes).
For the *link* networks, there are no explicit IPv6 labels.
However, the prompt asks to "Include in tables columns for IPv4 and IPv6."
I will assume standard IPv6 link-local or global unicast derivation if not explicitly shown, but since it's not shown, I will leave IPv6 columns blank or note "Not specified" for link
networks, OR I can infer based on the pattern.
Actually, looking at the local networks:
ASN 1111: 11:11:11:11::/64
ASN 1212: 12:12:12:12::/64
ASN 3030: 30:30:30::/64
ASN 1313: 13:13:13:13::/64
ASN 1414: 14:14:14:14::/64
ASN 1515: 15:15:15::/64
ASN 1616: 16:16:16:16::/64
ASN 1717: 17:17:17:17::/64
ASN 1818: 18:18:18:18::/64
ASN 1919: 19:19:19:19::/64
ASN 2020: 25:25:25:25::/64 (R12) and 20:20:20::/64 (R13).

For the links, usually in these labs (CCNP ENARSI), if not specified, they might just use IPv4. But the prompt asks for IPv6 columns. I will put "N/A" or leave blank for link IPv6
unless I can infer it.
Wait, let's look at the R1/R2 link again. 31.31.31.0/30.
Is there an IPv6 label? No.
However, the prompt says "Each cable segment has a network...".
I will assume the IPv6 column is for the *local* ASN networks primarily, but I need to include it for links if possible.
Actually, looking at the prompt "Include in tables columns for IPv4 and IPv6."
I will add columns for IPv6 IP and IPv6 Network. For links where it's not explicitly drawn, I will mark it as "Not shown" or infer based on the pattern (e.g., if IPv4 is x.x.x.0/30,
maybe IPv6 is x:x:x::/64? No, that's guessing).
Actually, looking at the diagram, the IPv6 labels are *only* next to the ASN local networks (the /24s).
The link networks are /30s.
I will leave the IPv6 columns for links blank or mark "Not specified" to be accurate to the image.
Wait, let's look at the ASN 2020 box.
R9: 10.10.10.1/32
R10: 10.10.10.2/32
R11: 10.10.10.3/32
R12: 25.25.25.0/24, 25:25:25:25::/64
R13: 20.20.20.0/24, 20:20:20::/64
The loopbacks (10.10.10.x/32) don't have IPv6 labels next to them.

Okay, I will construct the tables.

**Table 1 Construction Plan:**
Rows will be unique links.
Columns: ASN | Router | Interface | IPv4 IP | IPv4 Network | Neighbor | Neighbor Interface | IPv6 IP | IPv6 Network

**Table 2 Construction Plan:**
Rows will be unique ASNs.
Columns: ASN | IPv4 Network | IPv6 Network | Router publishing

Let's refine the data for Table 1.
Link 1: R4 (ASN 1111) e0/1 <-> R2 (ASN 3030) e0/1. Net: 40.40.40.0/30. R4: .2, R2: .1.
Link 2: R5 (ASN 1212) e0/0 <-> R4 (ASN 1111) e0/0. Net: 50.50.50.0/30. R5: .2, R4: .1.
Link 3: R5 (ASN 1212) e0/1 <-> R9 (ASN 2020) e0/0. Net: 60.60.60.0/30. R5: .1, R9: .2.
Link 4: R1 (ASN 3030) e0/0 <-> R2 (ASN 3030) e0/0. Net: 31.31.31.0/30. R1: .1, R2: .2.
Link 5: R1 (ASN 3030) e0/1 <-> R3 (ASN 3030) e0/0. Net: 31.31.31.4/30. R1: .5, R3: .6.
Link 6: R2 (ASN 3030) e0/2 <-> R3 (ASN 3030) e0/3. Net: 31.31.31.8/30. R2: .10, R3: .9.
Link 7: R3 (ASN 3030) e0/2 <-> R19 (ASN 1414) e0/0. Net: 100.100.100.0/30. R3: .1, R19: .2.
Link 8: R3 (ASN 3030) e0/1 <-> R8 (ASN 1313) e0/1. Net: 90.90.90.0/30. R3: .1, R8: .2.
Link 9: R6 (ASN 1313) e0/0 <-> R7 (ASN 1313) e0/0. Net: 13.14.14.0/30. R6: .1, R7: .2.
Link 10: R7 (ASN 1313) e0/1 <-> R8 (ASN 1313) e0/0. Net: 13.15.15.0/30. R7: .1, R8: .2.
Link 11: R8 (ASN 1313) e0/3 <-> R14 (ASN 1818) e0/1. Net: 80.80.80.0/30. R8: .1, R14: .2.
Link 12: R8 (ASN 1313) e0/2 <-> R11 (ASN 2020) e0/0. Net: 70.70.70.0/30. R8: .1, R11: .2.
Link 13: R19 (ASN 1414) e0/1 <-> R20 (ASN 1515) e0/0. Net: 110.110.110.0/30. R19: .1, R20: .2.
Link 14: R19 (ASN 1414) e0/2 <-> R17 (ASN 1616) e0/0. Net: 120.120.120.0/30. R19: .1, R17: .2.
Link 15: R20 (ASN 1515) e0/1 <-> R18 (ASN 1717) e0/0. Net: 170.170.170.0/30. R20: .1, R18: .2.
Link 16: R17 (ASN 1616) e0/1 <-> R14 (ASN 1818) e0/2. Net: 140.140.140.0/30. R17: .1, R14: .2.
Link 17: R17 (ASN 1616) e0/2 <-> R18 (ASN 1717) e0/2. Net: 130.130.130.0/30. R17: .1, R18: .2.
Link 18: R18 (ASN 1717) e0/1 <-> R16 (ASN 1919) e0/0. Net: 160.160.160.0/30. R18: .1, R16: .2.
Link 19: R14 (ASN 1818) e0/0 <-> R15 (ASN 1818) e0/0. Net: 18.20.20.0/30. R14: .1, R15: .2.
Link 20: R15 (ASN 1818) e0/1 <-> R16 (ASN 1919) e0/1. Net: 150.150.150.0/30. R15: .1, R16: .2.
Link 21: R9 (ASN 2020) e0/1 <-> R10 (ASN 2020) e0/0. Net: 21.21.21.0/30. R9: .2, R10: .1.
Link 22: R9 (ASN 2020) e0/2 <-> R12 (ASN 2020) e0/1. Net: 21.21.21.16/30. R9: .17, R12: .18.
Link 23: R10 (ASN 2020) e0/1 <-> R11 (ASN 2020) e0/1. Net: 21.21.21.4/30. R10: .5, R11: .6.
Link 24: R10 (ASN 2020) e0/2 <-> R12 (ASN 2020) e0/0. Net: 21.21.21.12/30. R10: .13, R12: .14.
Link 25: R10 (ASN 2020) e0/3 <-> R13 (ASN 2020) e0/1. Net: 21.21.21.8/30. R10: .9, R13: .10.
Link 26: R11 (ASN 2020) e0/2 <-> R13 (ASN 2020) e0/0. Net: 21.21.21.20/30. R11: .21, R13: .22.

**Table 2 Construction Plan:**
ASN 1111 | 11.11.11.0/24 | 11:11:11:11::/64 | R4
ASN 1212 | 12.12.12.0/24 | 12:12:12:12::/64 | R5
ASN 3030 | 30.30.30.0/24 | 30:30:30::/64 | R1
ASN 1313 | 13.13.13.0/24 | 13:13:13:13::/64 | R6
ASN 1414 | 14.14.14.0/24 | 14:14:14:14::/64 | R19
ASN 1515 | 15.15.15.0/24 | 15:15:15::/64 | R20
ASN 1616 | 16.16.16.0/24 | 16:16:16:16::/64 | R17
ASN 1717 | 17.17.17.0/24 | 17:17:17:17::/64 | R18
ASN 1818 | 18.18.18.0/24 | 18:18:18:18::/64 | R15
ASN 1919 | 19.19.19.0/24 | 19:19:19:19::/64 | R16
ASN 2020 | 25.25.25.0/24, 20.20.20.0/24 | 25:25:25:25::/64, 20:20:20::/64 | R12, R13

Wait, for ASN 2020, there are two local networks. I should list both or combine them.
The prompt asks for "ASN network". I will list both.

One detail: "Each interface has closer its a last IP octet."
This confirms the .1, .2, .5, .6, .9, .10, .13, .14, .17, .18, .21, .22 pattern.

Let's double check the IPv6 for links.
The prompt says "Include in tables columns for IPv4 and IPv6."
Since the diagram *only* provides IPv6 for the local ASN networks (the /24s), I will leave the IPv6 columns for the links blank or mark "Not specified in diagram". This is the most
accurate representation.
However, looking at the ASN 2020 box, there are loopbacks 10.10.10.1/32 etc. No IPv6.
So, for Table 1 (Links), IPv6 columns will be empty/not applicable.
For Table 2 (ASN Networks), IPv6 columns will have the values from the diagram.

Wait, looking at the diagram again very closely.
Are there IPv6 labels for the links?
No. The labels like "31.31.31.0/30" are purely IPv4.
The labels like "11:11:11:11::/64" are next to the ASN boxes.
So, Table 1 IPv6 columns will be empty.
Table 2 IPv6 columns will be populated.

Let's do a final check of the data.
R4 (ASN 1111) e0/1 -> R2 (ASN 3030) e0/1.
R4 IP: .2 (40.40.40.2).
R2 IP: .1 (40.40.40.1).
Correct.

R5 (ASN 1212) e0/0 -> R4 (ASN 1111) e0/0.
R5 IP: .2 (50.50.50.2).
R4 IP: .1 (50.50.50.1).
Correct.

R5 (ASN 1212) e0/1 -> R9 (ASN 2020) e0/0.
R5 IP: .1 (60.60.60.1).
R9 IP: .2 (60.60.60.2).
Correct.

R1 (ASN 3030) e0/0 -> R2 (ASN 3030) e0/0.
R1 IP: .1 (31.31.31.1).
R2 IP: .2 (31.31.31.2).
Correct.

R1 (ASN 3030) e0/1 -> R3 (ASN 3030) e0/0.
R1 IP: .5 (31.31.31.5).
R3 IP: .6 (31.31.31.6).
Correct.

R2 (ASN 3030) e0/2 -> R3 (ASN 3030) e0/3.
R2 IP: .10 (31.31.31.10).
R3 IP: .9 (31.31.31.9).
Correct.

R3 (ASN 3030) e0/2 -> R19 (ASN 1414) e0/0.
R3 IP: .1 (100.100.100.1).
R19 IP: .2 (100.100.100.2).
Correct.

R3 (ASN 3030) e0/1 -> R8 (ASN 1313) e0/1.
R3 IP: .1 (90.90.90.1).
R8 IP: .2 (90.90.90.2).
Correct.

R6 (ASN 1313) e0/0 -> R7 (ASN 1313) e0/0.
R6 IP: .1 (13.14.14.1).
R7 IP: .2 (13.14.14.2).
Correct.

R7 (ASN 1313) e0/1 -> R8 (ASN 1313) e0/0.
R7 IP: .1 (13.15.15.1).
R8 IP: .2 (13.15.15.2).
Correct.

R8 (ASN 1313) e0/3 -> R14 (ASN 1818) e0/1.
R8 IP: .1 (80.80.80.1).
R14 IP: .2 (80.80.80.2).
Correct.

R8 (ASN 1313) e0/2 -> R11 (ASN 2020) e0/0.
R8 IP: .1 (70.70.70.1).
R11 IP: .2 (70.70.70.2).
Correct.

R19 (ASN 1414) e0/1 -> R20 (ASN 1515) e0/0.
R19 IP: .1 (110.110.110.1).
R20 IP: .2 (110.110.110.2).
Correct.

R19 (ASN 1414) e0/2 -> R17 (ASN 1616) e0/0.
R19 IP: .1 (120.120.120.1).
R17 IP: .2 (120.120.120.2).
Correct.

R20 (ASN 1515) e0/1 -> R18 (ASN 1717) e0/0.
R20 IP: .1 (170.170.170.1).
R18 IP: .2 (170.170.170.2).
Correct.

R17 (ASN 1616) e0/1 -> R14 (ASN 1818) e0/2.
R17 IP: .1 (140.140.140.1).
R14 IP: .2 (140.140.140.2).
Correct.

R17 (ASN 1616) e0/2 -> R18 (ASN 1717) e0/2.
R17 IP: .1 (130.130.130.1).
R18 IP: .2 (130.130.130.2).
Correct.

R18 (ASN 1717) e0/1 -> R16 (ASN 1919) e0/0.
R18 IP: .1 (160.160.160.1).
R16 IP: .2 (160.160.160.2).
Correct.

R14 (ASN 1818) e0/0 -> R15 (ASN 1818) e0/0.
R14 IP: .1 (18.20.20.1).
R15 IP: .2 (18.20.20.2).
Correct.

R15 (ASN 1818) e0/1 -> R16 (ASN 1919) e0/1.
R15 IP: .1 (150.150.150.1).
R16 IP: .2 (150.150.150.2).
Correct.

R9 (ASN 2020) e0/1 -> R10 (ASN 2020) e0/0.
R9 IP: .2 (21.21.21.2).
R10 IP: .1 (21.21.21.1).
Correct.

R9 (ASN 2020) e0/2 -> R12 (ASN 2020) e0/1.
R9 IP: .17 (21.21.21.17).
R12 IP: .18 (21.21.21.18).
Correct.

R10 (ASN 2020) e0/1 -> R11 (ASN 2020) e0/1.
R10 IP: .5 (21.21.21.5).
R11 IP: .6 (21.21.21.6).
Correct.

R10 (ASN 2020) e0/2 -> R12 (ASN 2020) e0/0.
R10 IP: .13 (21.21.21.13).
R12 IP: .14 (21.21.21.14).
Correct.

R10 (ASN 2020) e0/3 -> R13 (ASN 2020) e0/1.
R10 IP: .9 (21.21.21.9).
R13 IP: .10 (21.21.21.10).
Correct.

R11 (ASN 2020) e0/2 -> R13 (ASN 2020) e0/0.
R11 IP: .21 (21.21.21.21).
R13 IP: .22 (21.21.21.22).
Correct.

Okay, I have all the data. I will format it into the requested tables.
I will add a note about IPv6 for links being not specified in the diagram.

One final check on ASN 2020 local networks.
R12 has 25.25.25.0/24.
R13 has 20.20.20.0/24.
Both are inside the ASN 2020 box.
So ASN 2020 publishes both.

One final check on ASN 1818 local networks.
R15 has 18.18.18.0/24.
R14 has 18.20.20.0/30 (this is a link network, not local).
Wait, looking at R14.
R14 is in ASN 1818.
Next to R14, there is "18.20.20.0/30". This is the link to R15.
Is there a local network for R14?
Looking at the yellow box (ASN 1818).
There is "18.20.20.0/30" near the link.
There is "18.18.18.0/24" near R15.
Is there a local network for R14?
The text "18.20.20.0/30" is clearly a link network (between R14 and R15).
Wait, looking at the text "18.18.18.0/24" and "18:18:18:18::/64". This is next to R15.
Is there a local network for R14?
The diagram doesn't explicitly show a local network for R14 inside the yellow box, other than the link network.
However, usually every router has a loopback or local network.
Looking at the text "18.20.20.0/30" again. It's right next to the link between R14 and R15.
Wait, looking at the text "18.18.18.0/24" and "18:18:18:18::/64". This is near R15.
Is it possible that R14 has no local network listed? Or is "18.20.20.0/30" actually a local network for R14?
No, it's a /30, so it's a point-to-point link.
So R14 might not have a specific /24 local network listed in the box, or it's implied.
But R15 definitely has 18.18.18.0/24.
I will list ASN 1818 with 18.18.18.0/24 published by R15.

Wait, looking at the yellow box again.
There is "18.20.20.0/30" near the link.
There is "18.18.18.0/24" near R15.
There is "18:18:18:18::/64" near R15.
So ASN 1818 has 18.18.18.0/24.

Okay, ready to write.

Structure:
1.  Introduction.
2.  Table 1: Link Connectivity.
3.  Table 2: ASN Network Summary.
4.  Note on IPv6.

Table 1 Columns:
ASN Number | Router Number | Interface | IPv4 IP | IPv4 Network | Neighbor Number | Neighbor Interface | IPv6 IP | IPv6 Network

Table 2 Columns:
ASN Number | IPv4 Network | IPv6 Network | Router Closer Publishing Network

I will combine the IPv4/IPv6 columns as requested.
"Include in tables columns for IPv4 and IPv6."
So columns like "IPv4 IP", "IPv4 Network", "IPv6 IP", "IPv6 Network".

Let's do this.
...done thinking.

# Response

Based on the provided network diagram (LAB BGP - CCNP ENARSI), here are the detailed configuration tables describing the connectivity and network assignments.

### Table 1: Link Connectivity Details
This table details every cable segment, the routers involved, their interfaces, IP addresses (following the "last octet" rule), and the network they belong to. Note that IPv6 addresses
for link networks are not explicitly labeled in the diagram, so they are marked as "Not Specified".

| ASN Number | Router Number | Interface | IPv4 IP | IPv4 Network | Neighbor Number | Neighbor Interface | IPv6 IP | IPv6 Network |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **1111** | R4 | e0/1 | 40.40.40.2 | 40.40.40.0/30 | **3030** | R2 e0/1 | Not Specified | Not Specified |
| **1111** | R4 | e0/0 | 50.50.50.1 | 50.50.50.0/30 | **1212** | R5 e0/0 | Not Specified | Not Specified |
| **1212** | R5 | e0/0 | 50.50.50.2 | 50.50.50.0/30 | **1111** | R4 e0/0 | Not Specified | Not Specified |
| **1212** | R5 | e0/1 | 60.60.60.1 | 60.60.60.0/30 | **2020** | R9 e0/0 | Not Specified | Not Specified |
| **3030** | R1 | e0/0 | 31.31.31.1 | 31.31.31.0/30 | **3030** | R2 e0/0 | Not Specified | Not Specified |
| **3030** | R1 | e0/1 | 31.31.31.5 | 31.31.31.4/30 | **3030** | R3 e0/0 | Not Specified | Not Specified |
| **3030** | R2 | e0/0 | 31.31.31.2 | 31.31.31.0/30 | **3030** | R1 e0/0 | Not Specified | Not Specified |
| **3030** | R2 | e0/1 | 40.40.40.1 | 40.40.40.0/30 | **1111** | R4 e0/1 | Not Specified | Not Specified |
| **3030** | R2 | e0/2 | 31.31.31.10 | 31.31.31.8/30 | **3030** | R3 e0/3 | Not Specified | Not Specified |
| **3030** | R3 | e0/0 | 31.31.31.6 | 31.31.31.4/30 | **3030** | R1 e0/1 | Not Specified | Not Specified |
| **3030** | R3 | e0/1 | 90.90.90.1 | 90.90.90.0/30 | **1313** | R8 e0/1 | Not Specified | Not Specified |
| **3030** | R3 | e0/2 | 100.100.100.1 | 100.100.100.0/30 | **1414** | R19 e0/0 | Not Specified | Not Specified |
| **3030** | R3 | e0/3 | 31.31.31.9 | 31.31.31.8/30 | **3030** | R2 e0/2 | Not Specified | Not Specified |
| **1313** | R6 | e0/0 | 13.14.14.1 | 13.14.14.0/30 | **1313** | R7 e0/0 | Not Specified | Not Specified |
| **1313** | R7 | e0/0 | 13.14.14.2 | 13.14.14.0/30 | **1313** | R6 e0/0 | Not Specified | Not Specified |
| **1313** | R7 | e0/1 | 13.15.15.1 | 13.15.15.0/30 | **1313** | R8 e0/0 | Not Specified | Not Specified |
| **1313** | R8 | e0/0 | 13.15.15.2 | 13.15.15.0/30 | **1313** | R7 e0/1 | Not Specified | Not Specified |
| **1313** | R8 | e0/1 | 90.90.90.2 | 90.90.90.0/30 | **3030** | R3 e0/1 | Not Specified | Not Specified |
| **1313** | R8 | e0/2 | 70.70.70.1 | 70.70.70.0/30 | **2020** | R11 e0/0 | Not Specified | Not Specified |
| **1313** | R8 | e0/3 | 80.80.80.1 | 80.80.80.0/30 | **1818** | R14 e0/1 | Not Specified | Not Specified |
| **1414** | R19 | e0/0 | 100.100.100.2 | 100.100.100.0/30 | **3030** | R3 e0/2 | Not Specified | Not Specified |
| **1414** | R19 | e0/1 | 110.110.110.1 | 110.110.110.0/30 | **1515** | R20 e0/0 | Not Specified | Not Specified |
| **1414** | R19 | e0/2 | 120.120.120.1 | 120.120.120.0/30 | **1616** | R17 e0/0 | Not Specified | Not Specified |
| **1515** | R20 | e0/0 | 110.110.110.2 | 110.110.110.0/30 | **1414** | R19 e0/1 | Not Specified | Not Specified |
| **1515** | R20 | e0/1 | 170.170.170.1 | 170.170.170.0/30 | **1717** | R18 e0/0 | Not Specified | Not Specified |
| **1616** | R17 | e0/0 | 120.120.120.2 | 120.120.120.0/30 | **1414** | R19 e0/2 | Not Specified | Not Specified |
| **1616** | R17 | e0/1 | 140.140.140.1 | 140.140.140.0/30 | **1818** | R14 e0/2 | Not Specified | Not Specified |
| **1616** | R17 | e0/2 | 130.130.130.1 | 130.130.130.0/30 | **1717** | R18 e0/2 | Not Specified | Not Specified |
| **1717** | R18 | e0/0 | 170.170.170.2 | 170.170.170.0/30 | **1515** | R20 e0/1 | Not Specified | Not Specified |
| **1717** | R18 | e0/1 | 160.160.160.1 | 160.160.160.0/30 | **1919** | R16 e0/0 | Not Specified | Not Specified |
| **1717** | R18 | e0/2 | 130.130.130.2 | 130.130.130.0/30 | **1616** | R17 e0/2 | Not Specified | Not Specified |
| **1818** | R14 | e0/0 | 18.20.20.1 | 18.20.20.0/30 | **1818** | R15 e0/0 | Not Specified | Not Specified |
| **1818** | R14 | e0/1 | 80.80.80.2 | 80.80.80.0/30 | **1313** | R8 e0/3 | Not Specified | Not Specified |
| **1818** | R14 | e0/2 | 140.140.140.2 | 140.140.140.0/30 | **1616** | R17 e0/1 | Not Specified | Not Specified |
| **1818** | R15 | e0/0 | 18.20.20.2 | 18.20.20.0/30 | **1818** | R14 e0/0 | Not Specified | Not Specified |
| **1818** | R15 | e0/1 | 150.150.150.1 | 150.150.150.0/30 | **1919** | R16 e0/1 | Not Specified | Not Specified |
| **1919** | R16 | e0/0 | 160.160.160.2 | 160.160.160.0/30 | **1717** | R18 e0/1 | Not Specified | Not Specified |
| **1919** | R16 | e0/1 | 150.150.150.2 | 150.150.150.0/30 | **1818** | R15 e0/1 | Not Specified | Not Specified |
| **2020** | R9 | e0/0 | 60.60.60.2 | 60.60.60.0/30 | **1212** | R5 e0/1 | Not Specified | Not Specified |
| **2020** | R9 | e0/1 | 21.21.21.2 | 21.21.21.0/30 | **2020** | R10 e0/0 | Not Specified | Not Specified |
| **2020** | R9 | e0/2 | 21.21.21.17 | 21.21.21.16/30 | **2020** | R12 e0/1 | Not Specified | Not Specified |
| **2020** | R10 | e0/0 | 21.21.21.1 | 21.21.21.0/30 | **2020** | R9 e0/1 | Not Specified | Not Specified |
| **2020** | R10 | e0/1 | 21.21.21.5 | 21.21.21.4/30 | **2020** | R11 e0/1 | Not Specified | Not Specified |
| **2020** | R10 | e0/2 | 21.21.21.13 | 21.21.21.12/30 | **2020** | R12 e0/0 | Not Specified | Not Specified |
| **2020** | R10 | e0/3 | 21.21.21.9 | 21.21.21.8/30 | **2020** | R13 e0/1 | Not Specified | Not Specified |
| **2020** | R11 | e0/0 | 70.70.70.2 | 70.70.70.0/30 | **1313** | R8 e0/2 | Not Specified | Not Specified |
| **2020** | R11 | e0/1 | 21.21.21.6 | 21.21.21.4/30 | **2020** | R10 e0/1 | Not Specified | Not Specified |
| **2020** | R11 | e0/2 | 21.21.21.21 | 21.21.21.20/30 | **2020** | R13 e0/0 | Not Specified | Not Specified |
| **2020** | R12 | e0/0 | 21.21.21.14 | 21.21.21.12/30 | **2020** | R10 e0/2 | Not Specified | Not Specified |
| **2020** | R12 | e0/1 | 21.21.21.18 | 21.21.21.16/30 | **2020** | R9 e0/2 | Not Specified | Not Specified |
| **2020** | R13 | e0/0 | 21.21.21.22 | 21.21.21.20/30 | **2020** | R11 e0/2 | Not Specified | Not Specified |
| **2020** | R13 | e0/1 | 21.21.21.10 | 21.21.21.8/30 | **2020** | R10 e0/3 | Not Specified | Not Specified |

### Table 2: ASN Network Summary
This table lists the local networks associated with each Autonomous System and the specific router closest to publishing that network.

| ASN Number | IPv4 Network | IPv6 Network | Router Closer Publishing Network |
| :--- | :--- | :--- | :--- |
| **1111** | 11.11.11.0/24 | 11:11:11:11::/64 | R4 |
| **1212** | 12.12.12.0/24 | 12:12:12:12::/64 | R5 |
| **3030** | 30.30.30.0/24 | 30:30:30::/64 | R1 |
| **1313** | 13.13.13.0/24 | 13:13:13:13::/64 | R6 |
| **1414** | 14.14.14.0/24 | 14:14:14:14::/64 | R19 |
| **1515** | 15.15.15.0/24 | 15:15:15::/64 | R20 |
| **1616** | 16.16.16.0/24 | 16:16:16:16::/64 | R17 |
| **1717** | 17.17.17.0/24 | 17:17:17:17::/64 | R18 |
| **1818** | 18.18.18.0/24 | 18:18:18:18::/64 | R15 |
| **1919** | 19.19.19.0/24 | 19:19:19:19::/64 | R16 |
| **2020** | 25.25.25.0/24, 20.20.20.0/24 | 25:25:25:25::/64, 20:20:20::/64 | R12, R13 |

```
total duration:       1h32m6.914170449s
load duration:        10.060484111s
prompt eval count:    1640 token(s)
prompt eval duration: 10m11.416437203s
prompt eval rate:     2.68 tokens/s
eval count:           18587 token(s)
eval duration:        1h21m36.419563879s
eval rate:            3.80 tokens/s

real	5527.15s
user	2.18s
sys	1.53s
cpu	0%
```
