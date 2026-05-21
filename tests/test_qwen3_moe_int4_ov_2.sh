#! /bin/bash

sudo sync && echo 3 | sudo tee /proc/sys/vm/drop_caches
sudo sysctl vm.swappiness=1
vmtouch -t /var/huggingface/qwen3_moe_int4_ov/
python test_qwen3_moe_int4_ov.py > results.txt 2>&1 &
