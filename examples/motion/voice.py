"""Generate Russian narration offline. Arguments: ONNX file, work directory."""

import json
import re
import sys
import wave
from pathlib import Path

import numpy as np
from piper import PiperVoice, SynthesisConfig

# A clip and its on-screen captions are the same phrase. Scene switches follow pauses.
SCENES = [
    [
        ("До цели не хватает", "До цели не хватает"),
        ("шести миллионов рублей.", "шести миллионов рублей."),
    ],
    [
        ("Стратег предлагает начать", "Стратег предлагает начать"),
        ("с девяноста тысяч.", "с девяноста тысяч."),
    ],
    [
        ("На эти деньги — проверить,", "На эти деньги — проверить,"),
        ("когда у близких", "когда у близких"),
        ("заканчивается интернет.", "заканчивается интернет."),
    ],
    [
        ("А теперь — слепое сравнение.", "А теперь — слепое сравнение."),
        ("Двое из трёх рецензентов", "Двое из трёх рецензентов"),
        ("предпочли ответ Стратега", "предпочли ответ Стратега"),
        ("обычному чату.", "обычному чату."),
    ],
]


def save(path, sound, rate):
    with wave.open(str(path), "wb") as w:
        w.setparams((1, 2, rate, 0, "NONE", "not compressed"))
        w.writeframes(np.clip(sound * 32767, -32767, 32767).astype("<i2").tobytes())


def main():
    model, directory = map(Path, sys.argv[1:3])
    directory.mkdir(exist_ok=True, parents=True)
    voice = PiperVoice.load(model, include_alignments=True)
    settings = SynthesisConfig(length_scale=1.13, noise_scale=0.48, noise_w_scale=0.33)
    rate = voice.config.sample_rate
    audio = []
    cursor = 0
    timing = []
    starts = []

    def push(data):
        nonlocal cursor
        audio.append(data)
        cursor += len(data)

    def pause(seconds):
        push(np.zeros(round(rate * seconds), np.float32))

    pause(0.19)
    for scene, pairs in enumerate(SCENES):
        starts.append(0 if scene == 0 else (cursor / rate - 0.20))
        for j, (phrase, caption) in enumerate(pairs):
            chunks = list(voice.synthesize(phrase, settings, include_alignments=True))
            sound = np.concatenate([chunk.audio_float_array for chunk in chunks])
            boundaries = []
            phoneme_offset = 0
            first = None
            last = None
            for chunk in chunks:
                if not chunk.phoneme_alignments:
                    raise RuntimeError("Install piper-tts[alignment] for word timing")
                for item in chunk.phoneme_alignments:
                    symbol = item.phoneme
                    if symbol.isspace() or symbol in ("^", "$"):
                        if first is not None:
                            boundaries.append((first, last))
                        first = last = None
                    elif symbol not in ",;:.!?—-":
                        if first is None:
                            first = phoneme_offset
                        last = phoneme_offset + int(item.num_samples)
                    phoneme_offset += int(item.num_samples)
            if first is not None:
                boundaries.append((first, last))
            display = re.findall(r"[А-Яа-яЁёA-Za-z0-9]+", caption)
            if len(display) != len(boundaries):
                raise ValueError((phrase, display, boundaries))
            assert phoneme_offset == len(sound)
            loc = np.flatnonzero(np.abs(sound) > 0.008)
            trim = max(0, loc[0] - int(rate * 0.042))
            sound = sound[trim : min(len(sound), loc[-1] + int(rate * 0.071))]
            fade = min(int(rate * 0.007), len(sound) // 2)
            sound[:fade] *= np.linspace(0, 1, fade)
            sound[-fade:] *= np.linspace(1, 0, fade)
            t0 = cursor / rate
            push(sound)
            t1 = cursor / rate
            timing.append(
                {
                    "scene": scene,
                    "caption": caption,
                    "start": round(t0, 3),
                    "end": round(t1, 3),
                    "words": [
                        {
                            "text": word,
                            "start": round(t0 + max(0, (lo - trim) / rate), 3),
                            "end": round(min(t1, t0 + (hi - trim) / rate), 3),
                        }
                        for word, (lo, hi) in zip(display, boundaries, strict=False)
                    ],
                }
            )
            pause(0.39 if j == len(pairs) - 1 else 0.11)
    pause(0.46)
    save(directory / "voice.wav", np.concatenate(audio), rate)
    (directory / "timing.json").write_text(
        json.dumps(
            {"duration": cursor / rate, "scene_starts": starts, "phrases": timing},
            ensure_ascii=False,
            indent=2,
        )
    )
    print(cursor / rate, starts)


if __name__ == "__main__":
    main()
