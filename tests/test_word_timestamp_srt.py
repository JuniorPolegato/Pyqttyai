"""
Use the Whisper configuration to output SRT file format for subtitles.
This test set `word_timestamps=True` to use function _process_word_timestamps
from pyqttyai.audio.transcription_worker_process

For Groq (example):
ffmpeg -i videos/Protected_Pyqttyai_v0.1-10fps_hevc.mp4 \
       -vn -acodec libmp3lame -ac 1 -ar 16000 -ab 64k videos/output_audio.mp3

For faster_whisper (example):
ffmpeg -i videos/Protected_Pyqttyai_v0.1-10fps_hevc.mp4 \
       -vn -c:a pcm_s16le videos/audio_output.wav
"""

import os
import sys
import time

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from pyqttyai.audio.transcription_worker_process import (
    WhisperConfig, _load_model, _transcribe_one,
)


def main():
    t0 = time.time()

    audio_file = sys.argv[1]

    config_model = WhisperConfig.load()
    config_transcribe = {k: v for k, v in config_model.__dict__.items()
        if k in ["beam_size", "language", "initial_prompt", "no_speech_text"]}
    config_transcribe["language"] = "pt"
    config_transcribe["initial_prompt"] = (
        "Este áudio é em português do Brasil, com termos técnico em inglês,"
        " sobre uma apresentação de um software para programação Cisco vinculado"
        " ao curso CCNP ENARSI, com imagem de topologia, editor de scripts e"
        " console tty. Faz uso do EVE-NG e comandos Cisco como 'no cdp run',"
        " 'enable', 'configure terminal', 'running-config', dentre outros"
    )

    emit=lambda *args,**kwargs: print(args, kwargs)

    print('t1:', t1 := time.time() - t0, flush=True)
    print("______________ Load model ________________")
    model, load_time = _load_model(config_model, emit=emit)
    print('t2:', t2 := time.time() - t0, t2 - t1, flush=True)

    print('t3:', t3 := time.time() - t0, flush=True)
    print("______________ Transcribe by word ________________")
    _transcribe_one(
        model=model,
        wav_path=audio_file,
        load_time=load_time,
        vad_filter=True,
        **config_transcribe,
        emit=emit,
        word_timestamps=True,
    )
    print('t4:', t4 := time.time() - t0, t4 - t3, flush=True)


if __name__ == "__main__":
    main()
