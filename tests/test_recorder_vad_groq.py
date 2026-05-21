import os
import sys
import time
import wave
import base64
import json
from PyQt6.QtWidgets import QApplication

import numpy as np
from faster_whisper.vad import get_speech_timestamps, VadOptions

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from pyqttyai.audio.transcription_worker_process import WhisperConfig, _load_model, _transcribe_one
from pyqttyai.audio.recorder import AudioRecorder

from groq import Groq

_audio_detected = float('inf')
_delay_transcription = 1.5
_threshold = 0.3
_segments = 1
t0 : float


def show_level(level: float):
    global _audio_detected, t0, _segments
    t = time.time() - t0
    if level > _threshold:
        _audio_detected = t
    print(f"{t:4.1f}s | Level: {level:4.1%} | "
          f"no voice: {0 if _audio_detected == float('inf') else t - _audio_detected:4.1f} | "
          f"Press [Enter] to stop...\r", end=''
    )
    if t- _audio_detected > _delay_transcription:
        _segments += 1
        print(f'\n\nSegment {_segments}:')

        _audio_detected = float('inf')


def _groq(filename, model, initial_prompt, *args, **kwargs):
    print('  t0:', t0 := time.time())
    client = Groq()
    print('  t1:', time.time() - t0)

    with open(filename, "rb") as file:
        print('  t2:', time.time() - t0)
        transcription = client.audio.transcriptions.create(
            file=(filename, file.read()),
            model="whisper-" + model,
            temperature=0,
            response_format="verbose_json",
            prompt=initial_prompt
        )
        print('  t3:', time.time() - t0)
        print(transcription)


def vad(audio_file, out_file='/tmp/output_no_silence.wav'):
    print('  t0:', t0 := time.time())
    # 1. Load your audio
    # Note: Silero VAD expects 16000Hz. If yours is different, you'll need to resample.
    with wave.open(audio_file, 'rb') as wf:
        params = wf.getparams()
        print('  tx:', time.time() - t0, params)
        audio_bytes = wf.readframes(wf.getnframes())
        # Convert to float32 normalized between -1.0 and 1.0
        audio_np = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0
    print('  t1:', time.time() - t0)

    # 2. Configure VAD to prevent "first letter" clipping
    options = VadOptions(
        threshold=_threshold,
        speech_pad_ms=500
    )
    print('  t2:', time.time() - t0)

    # 3. Get timestamps (uses the ONNX model in your faster_whisper assets)
    # get_speech_timestamps returns a list of dicts: [{'start': 0, 'end': 16000}, ...]
    timestamps = get_speech_timestamps(audio_np, options)
    print('  t3:', time.time() - t0)

    # 4. Stitch speech segments together
    if timestamps:
        speech_chunks = [audio_np[ts['start']:ts['end']] for ts in timestamps]
        print('  t4:', time.time() - t0)
        final_audio = np.concatenate(speech_chunks)
        print('  t5:', time.time() - t0)

        # Convert back to int16 for WAV saving
        final_audio_int16 = (final_audio * 32767).astype(np.int16)
        print('  t6:', time.time() - t0)

        with wave.open(out_file, 'wb') as wf_out:
            wf_out.setparams(params)
            wf_out.writeframes(final_audio_int16.tobytes())
        print('  t7:', time.time() - t0)
        print("Filtered audio saved.")
    else:
        print("No speech detected.")
    return out_file


def main():
    global t0
    if len(sys.argv) > 1:
        audio_file = sys.argv[1]
    else:
        app_id = 'Recorder'
        QApplication.setApplicationName(app_id)
        QApplication.setOrganizationName("Polegatech")
        app = QApplication([])
        rec = AudioRecorder(app)
        rec.level_changed.connect(show_level)
        print("______________ Recording ________________")
        print('t0:', t0 := time.time())
        rec.start()
        input("\nPress [Enter] to stop...\n\nSegment 1:\n")
        print(audio_file := rec.stop())
        print('tf:', time.time() - t0)

    config_model = WhisperConfig.load()
    groq_model = config_model.model
    config_transcribe = {k: v for k, v in config_model.__dict__.items()
        if k in ["beam_size", "language", "initial_prompt", "no_speech_text"]}

    emit=lambda *args,**kwargs: print(args, kwargs)
    t0 = time.time()

    print("______________ Groq ________________")
    print('t1:', t1 := time.time() - t0)
    _groq(audio_file, groq_model, **config_transcribe)
    print('t2:', t2 := time.time() - t0, t2 - t1)

    print("______________ Load model ________________")
    print('t3:', t3 := time.time() - t0)
    model, load_time = _load_model(config_model, emit=emit)
    print('t4:', t4 := time.time() - t0, t4 - t3, model, load_time)

    print("______________ Transcribe vad_filter=False ________________")
    print('t5:', t5 := time.time() - t0)
    _transcribe_one(
        model=model,
        wav_path=audio_file,
        load_time=load_time,
        vad_filter=True,
        **config_transcribe,
        emit=emit
    )
    print('t6:', t6 := time.time() - t0, t6 - t5)

    print("______________ Transcribe vad_filter=True ________________")
    print('t5.1:', t51 := time.time() - t0)
    _transcribe_one(
        model=model,
        wav_path=audio_file,
        load_time=load_time,
        vad_filter=True,
        **config_transcribe,
        emit=emit
    )
    print('t6.1:', t61 := time.time() - t0, t61 - t51)

    print("______________ VAD file ________________")
    print('t7:', t7 := time.time() - t0)
    vad_file = vad(audio_file, audio_file[:-4] + '_vad.wav')
    print('t8:', t8 := time.time() - t0, t8 - t7)

    print("______________ Transcribe VAD file ________________")
    print('t9:', t9 := time.time() - t0)
    _transcribe_one(
        model=model,
        wav_path=vad_file,
        load_time=load_time,
        vad_filter=False,
        **config_transcribe,
        emit=emit
    )
    print('t10:', t10 := time.time() - t0, t10 - t9)

    print("______________ Groq VAD file ________________")
    print('t11:', t11 := time.time() - t0)
    _groq(vad_file, groq_model, **config_transcribe)
    print('t12:', t12 := time.time() - t0, t12 - t11)


if __name__ == "__main__":
    _env = '.env'
    for i in range(5):
        if os.path.exists(_env):
            break
        _env = '../' + _env

    print(f"Loading {_env}...")
    with open(_env, encoding="utf-8") as fd:
        for line in fd:
            var, value = line.split('=')
            os.environ[var.strip()] = value.strip()
    main()
