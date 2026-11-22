"""Lower the register in Praat, synthesize graph cues and master the stereo mix."""

import json
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np
import parselmouth as pm
from parselmouth.praat import call

work = Path(sys.argv[1])
timeline = json.loads((work / "timing.json").read_text())
starts = timeline["scene_starts"]
dry = pm.Sound(str(work / "voice.wav"))
v = call(dry, "Change speaker", 60, 330, 0.97, 0.80, 0.94, 1.0)
v.scale_peak(0.85)
v.save(str(work / "voice-low.wav"), "WAV")
sr = 48000
mix = np.zeros((round(timeline["duration"] * sr), 2))
rng = np.random.default_rng(1271)


def place(start, waveform, pan=0.5):
    i = round(start * sr)
    j = min(len(mix), i + len(waveform))
    if i < 0:
        raise ValueError("invalid start")
    for ch, gain in enumerate([np.cos(pan * np.pi / 2), np.sin(pan * np.pi / 2)]):
        mix[i:j, ch] += gain * waveform[: j - i]


def tap(start, hz, pan, level=0.052):
    t = np.arange(0, 0.215, 1 / sr)
    env = (1 - np.exp(-t / 0.004)) * np.exp(-t / 0.044)
    place(
        start,
        level
        * env
        * (np.sin(2 * np.pi * hz * t) + 0.24 * np.sin(2 * np.pi * 1.99 * hz * t)),
        pan,
    )


def whoosh(end):
    t = np.arange(0, 0.27, 1 / sr)
    noise = rng.standard_normal(len(t))
    smooth = np.convolve(noise, np.ones(17) / 17, mode="same") - np.convolve(
        noise, np.ones(69) / 69, mode="same"
    )
    place(end - 0.22, 0.23 * np.sin(np.pi * t / 0.27) ** 2 * smooth, 0.65)
    s = np.arange(0, 0.34, 1 / sr)
    body = (
        np.sin(2 * np.pi * (46 * s + 6.5 * (1 - np.exp(-s * 14))))
        * (1 - np.exp(-s / 0.004))
        * np.exp(-s / 0.074)
    )
    place(end, 0.11 * body, 0.48)


for boundary in starts[1:]:
    whoosh(boundary)
words = {
    word["text"].lower(): word["start"]
    for phrase in timeline["phrases"]
    for word in phrase["words"]
}
tap(0.21, 661, 0.34)
tap(words["шести"], 880, 0.63)
for i, hz in enumerate((330, 370, 392, 440, 494, 523, 587, 659, 740)):
    tap(words["девяноста"] + 0.06 * i, hz, 0.28 + 0.045 * i, 0.025)
tap(words["заканчивается"] + 0.12, 698, 0.63)
tap(words["заканчивается"] + 0.25, 880, 0.6, 0.04)
for i, (word, base) in enumerate(
    zip(("двое", "трёх", "обычному"), (492, 624, 392), strict=False)
):
    tap(words[word], base, 0.36 + i * 0.12, 0.06)
with wave.open(str(work / "sfx.wav"), "wb") as output:
    output.setparams((2, 2, sr, 0, "NONE", ""))
    output.writeframes(np.clip(mix * 32767, -32767, 32767).astype("<i2").tobytes())
vf = (
    "highpass=f=64,equalizer=f=210:t=q:w=1.15:g=-1.8,equalizer=f=2900:t=q:w=1:g=1.5,"
    "acompressor=threshold=0.13:ratio=2.6:attack=12:release=100:makeup=1.25"
)
pre = f"[0:a]{vf},aresample=48000,pan=stereo|c0=c0|c1=c0[n];[n][1:a]amix=inputs=2:normalize=0:duration=longest"


def ff(args):
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", *args], check=True)


common = ["-i", str(work / "voice-low.wav"), "-i", str(work / "sfx.wav")]
ff(
    common
    + [
        "-filter_complex",
        pre,
        "-ar",
        "48000",
        "-c:a",
        "pcm_f32le",
        str(work / "premix.wav"),
    ]
)
ln = "loudnorm=I=-15:TP=-1.6:LRA=6"
probe = subprocess.run(
    [
        "ffmpeg",
        "-hide_banner",
        "-nostats",
        "-i",
        str(work / "premix.wav"),
        "-af",
        ln + ":print_format=json",
        "-f",
        "null",
        "-",
    ],
    capture_output=True,
    text=True,
    check=True,
).stderr
stats = json.loads(probe[probe.rfind("{") : probe.rfind("}") + 1])
measured = ":".join(
    k + "=" + stats[v]
    for k, v in [
        ("measured_I", "input_i"),
        ("measured_TP", "input_tp"),
        ("measured_LRA", "input_lra"),
        ("measured_thresh", "input_thresh"),
        ("offset", "target_offset"),
    ]
)
ff(
    [
        "-i",
        str(work / "premix.wav"),
        "-af",
        ln + ":" + measured + ":linear=true",
        "-ar",
        "48000",
        "-c:a",
        "pcm_s24le",
        str(work / "mix.wav"),
    ]
)


# Standalone subtitles use the actual beginnings and endings of the synthesised phrases.
def stamp(t):
    msec = round(t * 1000)
    return f"00:{msec // 60000:02}:{msec // 1000 % 60:02},{msec % 1000:03}"


(work / "captions.srt").write_text(
    "\n\n".join(
        f"{i}\n{stamp(p['start'])} --> {stamp(p['end'])}\n{p['caption']}"
        for i, p in enumerate(timeline["phrases"], 1)
    )
    + "\n"
)
print(stats)
