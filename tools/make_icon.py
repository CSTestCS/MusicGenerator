"""Draws assets/icon.ico (a word-shaped wave). Needs Pillow; run once."""
import math
import os

from PIL import Image, ImageDraw

S = 256
img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
d.rounded_rectangle((8, 8, S - 8, S - 8), radius=48, fill=(27, 28, 35, 255))
vals = [0.85, 0.3, 0.55, 0.7, 0.45, 0.15]  # "simple"
pts = []
for i in range(200):
    x = i / 199
    pos = x * len(vals) - 0.5
    j = max(0, min(len(vals) - 2, int(math.floor(pos))))
    f = max(0.0, min(1.0, pos - j))
    f = f * f * (3 - 2 * f)
    v = vals[j] * (1 - f) + vals[j + 1] * f
    pts.append((36 + x * (S - 72), S - 50 - v * (S - 110)))
d.line(pts, fill=(127, 209, 255, 255), width=14, joint="curve")
for k, x in enumerate(range(48, S - 40, 26)):
    h = 18 + 22 * abs(math.sin(k * 1.3))
    d.rounded_rectangle((x, S - 46 - h, x + 12, S - 40), radius=4, fill=(224, 160, 80, 255))
out = os.path.join(os.path.dirname(__file__), "..", "assets", "icon.ico")
img.save(out, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
img.save(out.replace(".ico", ".png"))
