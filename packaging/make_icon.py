"""[PACKAGING / icon] Draw HybridAgent.ico (the face from favicon.svg) with Pillow. Run once; the .ico is committed."""
from pathlib import Path

from PIL import Image, ImageDraw

S = 1024                                           # draw big, scale down: smooth edges at every size
img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
d.rounded_rectangle((32, 32, S - 32, S - 32), radius=220, fill="#5b6ee1")
for cx in (352, 672):
    d.ellipse((cx - 80, 400, cx + 80, 560), fill="white")
d.arc((300, 470, 724, 820), start=25, end=155, fill="white", width=64)
out = Path(__file__).with_name("HybridAgent.ico")
img.save(out, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
img.resize((256, 256), Image.LANCZOS).save(out.with_suffix(".png"))
print("wrote", out)
