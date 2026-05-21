import huggingface_hub as hf_hub
import openvino_genai as ov_genai
import librosa
import time
import json
import sys

# Definindo a configuração para limitar threads
# No seu i7, geralmente os P-cores são os primeiros índices (0, 1, 2, 3...)
ov_config = {
    "device": "GPU",
    #"inference_num_threads": 4,           # Limita a 4 threads de processamento
    #"cpu_bind_threads": "YES",            # Tenta fixar as threads nos cores
    #"scheduling_core_type": "PCORE_ONLY"  # Garante o uso de P-cores em vez de E-cores
}


t0 = time.time()
print("\n1. Carregue o áudio convertendo automaticamente para 16kHz e float32")
print("O librosa já normaliza o áudio entre -1.0 e 1.0 por padrão\n")
raw_speech, _ = librosa.load(sys.argv[1], sr=16000)
raw_speech_list = raw_speech.tolist()
librosa_time = tf = time.time() - t0
print(f"\nlibrosa: {tf:.3f}s")

for quant in ('int4', 'int8', 'fp16'):
    model_id = f"OpenVINO/whisper-large-v3-{quant}-ov"
    model_path = f"whisper-large-v3-{quant}-ov"
    t1 = time.time()

    print("\nDownload do snapshot (se necessário)\n")
    hf_hub.snapshot_download(model_id, local_dir=model_path)
    print(f"\nDownload: {(t2 := time.time()) - t1:.3f}s")

    print("\nPipe...\n")
    pipe = ov_genai.WhisperPipeline(model_path, **ov_config)
    print(f"\nPipe: {(load_time := (t3 := time.time()) - t2):.3f}s")

    print("\n1. Configurar para retornar timestamps")
    config = pipe.get_generation_config()
    config.return_timestamps = True
    # config.language = "<|pt|>"
    print(f"\nconfig: {(t4 := time.time()) - t3:.3f}s")

    print("\n2. Converta para uma lista ou mantenha como array (o OpenVINO aceita a sequência)")
    print("O WhisperPipeline do OpenVINO GenAI espera o input direto\n")
    result = pipe.generate(raw_speech_list, config)
    print(f"\ngenerate: {(transcribe_time := (t5 := time.time()) - t4):.3f}s")

    print("\n3. Construir o dicionário completo (estilo JSON)")
    verbose_json = {
        "task": "transcribe",
        #"language": "portuguese", # Você pode extrair isso se usar detecção automática
        "duration": len(raw_speech) / 16000, # Duração baseada no sample rate
        "text": "".join(result.texts),
        "segments": [],
        "quantizes": quant,
        "load_time": load_time,
        "librosa_time": librosa_time,
        "transcribe_time" : transcribe_time,
        "per_audio_time": librosa_time + transcribe_time
    }
    for i, chunk in enumerate(result.chunks):
        verbose_json["segments"].append({
            "id": i,
            "start": chunk.start_ts,
            "end": chunk.end_ts,
            "text": chunk.text,
            # Nota: O OpenVINO GenAI foca em performance e pode não exportar
            # todos os metadados probabilísticos (como avg_logprob) nativamente ainda.
        })
    print(f"\nVerbose JSON: {(t6 := time.time()) - t5}s")

    print("\nExemplo de visualização")
    print('_' * 100)
    print(json.dumps(verbose_json, indent=4, ensure_ascii=False))
    print('‾' * 100)
    print(f"\nshow: {(t7 := time.time()) - t6}s")

    tf += t7 - t1

print(f"\nTotal: {tf:.3f}s")
