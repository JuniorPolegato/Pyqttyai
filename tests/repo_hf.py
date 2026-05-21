from huggingface_hub import model_info
models = [
    "Qwen/Qwen2.5-32B-Instruct",
    "Qwen/Qwen2.5-35B-Instruct",
    "Qwen/Qwen3.5-32B-Instruct",
    "Qwen/Qwen3.5-35B-Instruct",
    "Qwen/Qwen3.6-32B-Instruct",
    "Qwen/Qwen3.6-35B-Instruct",
    "Qwen/Qwen2.5-32B-Instruct-A3B",
    "Qwen/Qwen2.5-35B-Instruct-A3B",
    "Qwen/Qwen3.5-32B-Instruct-A3B",
    "Qwen/Qwen3.5-35B-Instruct-A3B",
    "Qwen/Qwen3.6-32B-Instruct-A3B",
    "Qwen/Qwen3.6-35B-Instruct-A3B",
    "Qwen/Qwen2.5-32B-A3B-Instruct",
    "Qwen/Qwen2.5-35B-A3B-Instruct",
    "Qwen/Qwen3.5-32B-A3B-Instruct",
    "Qwen/Qwen3.5-35B-A3B-Instruct",
    "Qwen/Qwen3.6-32B-A3B-Instruct",
    "Qwen/Qwen3.6-35B-A3B-Instruct",

    "Qwen/Qwen2.5-32B-Instruct",
    "Qwen/Qwen2.5-35B-Instruct-A3B",
    "Qwen/Qwen2.5-14B-Instruct",
    "deepseek-ai/DeepSeek-Coder-V2-Lite-Instruct" # Excelente para scripts de rede
]

for model in models:
    try:
        info = model_info(model)
        print(f"Repositório encontrado! [{model}]")
    except Exception as e:
        print(f"Erro [{model}]: {e}")
