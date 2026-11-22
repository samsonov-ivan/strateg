"""Draw original motion graphics from a phrase timeline. Requires Pillow and FFmpeg."""

import json
import math
import os
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H, FPS = 1080, 1920, 30
DARK = (14, 31, 34)
DARK2 = (21, 45, 46)
PAPER = (240, 238, 225)
INK = (22, 44, 44)
MINT = (140, 236, 201)
GOLD = (236, 252, 87)
MUTED = (158, 180, 167)
RULE = (68, 90, 84)
WARMRULE = (181, 192, 172)
WHITE = (249, 250, 236)
candidates = (
    [Path(os.environ["STRATEG_FONTS"])] if "STRATEG_FONTS" in os.environ else []
)
candidates += [Path("/usr/share/fonts/truetype/dejavu")]
BASE = next((p for p in candidates if (p / "DejaVuSans.ttf").exists()), None)
if not BASE:
    raise RuntimeError(
        "Set STRATEG_FONTS to directory with DejaVu Sans/Mono TrueType files"
    )


@lru_cache(maxsize=800)
def f(s, mode="reg"):
    name = {
        "reg": "DejaVuSans",
        "bold": "DejaVuSans-Bold",
        "mono": "DejaVuSansMono",
        "heavy": "DejaVuSansCondensed-Bold",
    }[mode]
    return ImageFont.truetype(str(BASE / (name + ".ttf")), round(s))


def put(d, x, y, s, size, color, mode="reg", anchor="lt", stroke=0, outline=None):
    d.text(
        (int(x), int(y)),
        s,
        font=f(size, mode),
        fill=color,
        anchor=anchor,
        stroke_width=stroke,
        stroke_fill=outline,
    )


def sat(t):
    return max(0, min(1, t))


def ease(t):
    t = sat(t)
    return 1 - (1 - t) ** 3


def smooth(t):
    t = sat(t)
    return t * t * (3 - 2 * t)


def mix(a, b, t):
    return a + (b - a) * t


def pill(d, x, y, w, h, color):
    d.rounded_rectangle((x, y, x + w, y + h), radius=h / 2, fill=color)


def check(d, x, y, col, scale=1):
    d.line(
        [
            (x - 12 * scale, y),
            (x - 3 * scale, y + 9 * scale),
            (x + 15 * scale, y - 10 * scale),
        ],
        fill=col,
        width=max(2, round(5 * scale)),
        joint="curve",
    )


def header(d, dark):
    fg = WHITE if dark else INK
    ag = GOLD if dark else INK
    for j in range(3):
        x = 76 + j * 13
        d.line((x, 169, x + 12, 145 + j * 2), fill=ag, width=6)
    put(d, 135, 141, "Стратег", 40, fg, "bold")
    put(d, 868, 151, "учебный кейс", 23, MUTED if dark else (66, 86, 78), "mono", "rt")
    d.line((76, 217, 924, 217), fill=RULE if dark else WARMRULE, width=2)


def title(d, u, a, b, fg):
    shift = round((1 - ease(u / 0.43)) * 50)
    put(d, 75, 288 + shift, a, 75, fg, "heavy")
    put(d, 75, 376 + shift, b, 75, fg, "heavy")


def orbit(d, cx, cy, r, t, col):
    for k in range(3):
        start = 270 + k * 120 + t * 17
        d.arc(
            (cx - r, cy - r, cx + r, cy + r),
            start=start,
            end=start + 64,
            fill=col,
            width=2,
        )


def scene_gap(d, u, w):
    title(d, u, "Между прогнозом", "и целью", WHITE)
    a = ease(u / 0.8)
    x = 78 - int((1 - a) * 70)
    reveal = ease((u - w["шести"]) / 0.28)
    if reveal < 1:
        put(
            d,
            x,
            615 + int(70 * reveal),
            "279",
            195,
            tuple(int(mix(c, b, reveal)) for c, b in zip(WHITE, DARK, strict=False)),
            "heavy",
        )
        put(
            d,
            509,
            714 + int(38 * reveal),
            "млн ₽",
            66,
            tuple(int(mix(c, b, reveal)) for c, b in zip(MUTED, DARK, strict=False)),
            "heavy",
        )
    if reveal > 0:
        col = tuple(int(mix(b, c, reveal)) for c, b in zip(GOLD, DARK, strict=False))
        put(d, x + round((1 - reveal) * 57), 576, "6", 291, col, "heavy")
        put(
            d,
            310,
            716,
            "млн ₽",
            89,
            tuple(int(mix(b, c, reveal)) for c, b in zip(WHITE, DARK, strict=False)),
            "heavy",
        )
    put(d, 80, 924, "Валовая прибыль за плановый год", 31, MUTED)
    x0, x1 = 125, 844
    y = 1150
    for k in range(31):
        xx = x0 + (x1 - x0) * k / 30
        d.line((xx, y + 18, xx, y + 18 + (17 if k % 5 == 0 else 8)), fill=RULE, width=2)
    d.line((x0, y, x1, y), fill=RULE, width=5)
    end = mix(x0, x1, ease((u - 0.25) / 1.4))
    d.line((x0, y, end, y), fill=MINT, width=7)
    for xx, col in [(x0, MINT), (end, GOLD)]:
        d.ellipse((xx - 10, y - 10, xx + 10, y + 10), fill=col)
    orbit(d, end, y, 29 + 3 * math.sin(u * 3), u, MINT)
    brace = ease((u - w["шести"]) / 0.35)
    if brace:
        by = y + 82
        d.line((x0, by - 13, x0, by, mix(x0, x1, brace), by), fill=GOLD, width=3)
        if brace > 0.96:
            d.line((x1, by, x1, by - 13), fill=GOLD, width=3)
    put(d, 82, 1032, "279", 73, WHITE, "heavy")
    put(d, 877, 1032, "285", 73, GOLD, "heavy", "rt")
    put(d, 83, 1272, "прогноз", 33, MUTED)
    put(d, 877, 1272, "цель", 33, MUTED, "reg", "rt")


def scene_budget(d, u, w):
    title(d, u, "Первый расход", "на проверку", INK)
    v = round(90 * ease((u - w["девяноста"] + 0.06) / 0.50))
    put(d, 70, 567, str(v) if v else "…", 237, INK, "heavy")
    put(d, 72, 815, "тыс. ₽", 108, INK, "heavy")
    for j in range(9):
        x = 78 + j * 91
        p = ease((u - w["девяноста"] - j * 0.06) / 0.28)
        h = 138 * p
        d.rounded_rectangle(
            (x, 1174 - h, x + 65, 1175), radius=10, fill=INK if j < 8 else (0, 103, 77)
        )
        if p > 0.5:
            d.line(
                (x + 9, 1174 - h + 15, x + 54, 1174 - h + 15),
                fill=(104, 144, 123),
                width=3,
            )
    put(d, 78, 1231, "9 × 10 000 ₽", 34, (69, 90, 76), "mono")


def scene_phone(d, u, w):
    title(d, u, "Когда семье", "нужна помощь", WHITE)
    pos = int((1 - ease(u / 0.5)) * 110)
    x = 104 + pos
    y = 558
    d.rounded_rectangle((x + 16, y + 19, x + 730, y + 638), radius=68, fill=(5, 16, 18))
    d.rounded_rectangle(
        (x, y, x + 715, y + 620),
        radius=64,
        fill=(31, 59, 58),
        outline=(102, 135, 118),
        width=4,
    )
    pill(d, x + 275, y + 26, 151, 14, (11, 30, 31))
    put(d, x + 44, y + 88, "Семейный интернет", 47, WHITE, "heavy")
    put(d, x + 45, y + 174, "Остаток участника", 31, MUTED)
    q = smooth((u - w["когда"]) / max(0.1, w["интернет"] - w["когда"]))
    gig = mix(1.6, 0.2, q)
    put(d, x + 43, y + 246, f"{gig:.1f}".replace(".", ",") + " ГБ", 98, GOLD, "heavy")
    for k in range(12):
        xx = x + 45 + k * 51
        active = k < max(1, round(12 * (1 - q * 0.90)))
        d.rounded_rectangle(
            (xx, y + 395, xx + 37, y + 433),
            radius=8,
            fill=GOLD if active else (56, 83, 77),
        )
    d.line((x + 45, y + 489, x + 630, y + 489), fill=RULE, width=2)
    put(d, x + 45, y + 528, "Общий пакет доступен", 30, MUTED)
    p = ease((u - w["заканчивается"] - 0.12) / 0.4)
    if p > 0:
        xx = 178 + (1 - p) * 830
        yy = 1108
        d.rounded_rectangle((xx, yy, xx + 692, yy + 160), radius=30, fill=MINT)
        d.ellipse((xx + 28, yy + 35, xx + 114, yy + 121), fill=INK)
        d.line(
            (xx + 51, yy + 82, xx + 70, yy + 64, xx + 92, yy + 82),
            fill=MINT,
            width=5,
            joint="curve",
        )
        put(d, xx + 139, yy + 25, "Организатору семьи", 31, INK)
        put(d, xx + 139, yy + 78, "Пора поделиться", 44, INK, "heavy")
    put(d, 105, 1321, "Концепт уведомления", 24, MUTED, "mono")


def scene_vote(d, u, w):
    title(d, u, "Слепое", "сравнение", INK)
    n = 0 if u < w["двое"] else 1 if u < w["трёх"] else 2
    put(d, 70, 550, str(n), 236, INK, "heavy")
    put(d, 244, 626, "/ 3", 148, (75, 111, 90), "heavy")
    cards = [("1", "Стратег"), ("2", "Стратег"), ("3", "Обычный чат")]
    for j, (idx, name) in enumerate(cards):
        p = ease((u - 0.25 - j * 0.26) / 0.51)
        x = 78 + (1 - p) * 740
        y = 905 + j * 123
        if p <= 0:
            continue
        activation = (w["двое"], w["трёх"], w["обычному"])[j]
        active = u >= activation
        identity = u >= (w["предпочли"] if j < 2 else w["обычному"])
        lift = math.sin(math.pi * sat((u - activation) / 0.36)) * 10 if active else 0
        y -= int(lift)
        color = INK if active and j < 2 else (224, 230, 211)
        text = WHITE if active and j < 2 else INK
        d.rounded_rectangle(
            (x, y, x + 799, y + 96),
            radius=24,
            fill=color,
            outline=(177, 191, 170) if j == 2 else color,
            width=2,
        )
        put(
            d,
            x + 25,
            y + 32,
            "Рецензент " + idx,
            27,
            MUTED if active and j < 2 else (79, 99, 88),
            "mono",
        )
        put(
            d,
            x + 340,
            y + 24,
            name if identity else "Выбор сделан" if active else "…",
            38,
            text,
            "heavy",
        )
        if active and j < 2:
            d.ellipse((x + 713, y + 22, x + 765, y + 74), fill=GOLD)
            check(d, x + 739, y + 49, INK, 0.72)
    put(d, 80, 1311, "Выбор между двумя записками", 27, (69, 90, 76))


def captions(canvas, d, t, blocks, dark):
    seg = next((b for b in blocks if b["start"] - 0.02 <= t <= b["end"] + 0.065), None)
    if not seg:
        return
    tokens = seg["words"]
    font = 50
    gap = 21

    def token_widths(size):
        return [d.textlength(q["text"], font=f(size, "bold")) for q in tokens]

    widths = token_widths(font)
    while sum(widths) + gap * (len(tokens) - 1) > 798:
        font -= 1
        widths = token_widths(font)
    selected = max((i for i, q in enumerate(tokens) if t >= q["start"]), default=0)
    positions = []
    x = 88
    for width in widths:
        positions.append(x)
        x += width + gap
    cur = tokens[selected]
    speed = ease((t - cur["start"]) / 0.085)
    prev = max(0, selected - 1)
    box_x = mix(positions[prev], positions[selected], speed)
    box_w = mix(widths[prev], widths[selected], speed)
    y = 1470 + int((1 - ease((t - seg["start"] + 0.02) / 0.11)) * 24)
    base = WHITE if dark else INK
    active = INK if dark else GOLD
    d.rounded_rectangle(
        (box_x - 8, y - 13, box_x + box_w + 9, y + font + 9),
        radius=14,
        fill=GOLD if dark else INK,
    )
    # Preserve contrast even while the accent travels between words.
    left = max(0, int(box_x - 8))
    right = min(W, math.ceil(box_x + box_w + 9))
    overlay = Image.new("RGBA", (right - left, font + 10))
    mask_text = ImageDraw.Draw(overlay)
    for j, q in enumerate(tokens):
        put(d, positions[j], y, q["text"], font, base, "bold")
        put(mask_text, positions[j] - left, 0, q["text"], font, active, "bold")
    canvas.paste(overlay, (left, y), overlay)


def render_frame(t, timing):
    starts = timing["scene_starts"]
    scene = max(i for i, v in enumerate(starts) if v <= t)
    u = t - starts[scene]
    dark = scene in (0, 2)
    im = Image.new("RGB", (W, H), DARK if dark else PAPER)
    d = ImageDraw.Draw(im)
    words = {
        word["text"].lower(): word["start"] - starts[scene]
        for phrase in timing["phrases"]
        if phrase["scene"] == scene
        for word in phrase["words"]
    }
    [scene_gap, scene_budget, scene_phone, scene_vote][scene](d, u, words)
    if scene == 3:
        strength = smooth((u - words["предпочли"]) / 0.67)
        focus = 1 + 0.035 * strength
        if strength:
            ax, ay = 510, 965
            im = im.transform(
                (W, H),
                Image.Transform.AFFINE,
                (
                    1 / focus,
                    0,
                    ax * (1 - 1 / focus),
                    0,
                    1 / focus,
                    ay * (1 - 1 / focus),
                ),
                resample=Image.Resampling.BILINEAR,
            )
            d = ImageDraw.Draw(im)
    header(d, dark)
    captions(im, d, t, timing["phrases"], dark)
    if scene > 0 and u < 0.19:
        end = 1081 * (1 - ease(u / 0.19))
        d.polygon([(0, 0), (end, 0), (max(0, end - 120), H), (0, H)], fill=GOLD)
    return im


def main():
    work = Path(sys.argv[1])
    out = Path(sys.argv[2])
    timing = json.loads((work / "timing.json").read_text())
    frames = math.ceil(timing["duration"] * FPS)
    command = [
        "ffmpeg",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "rawvideo",
        "-pixel_format",
        "rgb24",
        "-video_size",
        f"{W}x{H}",
        "-framerate",
        str(FPS),
        "-i",
        "pipe:0",
        "-i",
        str(work / "mix.wav"),
        "-map",
        "0:v",
        "-map",
        "1:a",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "18",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-movflags",
        "+faststart",
        str(out),
    ]
    proc = subprocess.Popen(command, stdin=subprocess.PIPE)
    for frame in range(frames):
        proc.stdin.write(render_frame(frame / FPS, timing).tobytes())
    proc.stdin.close()
    if proc.wait():
        raise RuntimeError("ffmpeg failed")


if __name__ == "__main__":
    main()
