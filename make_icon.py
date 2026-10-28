# -*- coding: utf-8 -*-
"""生成 CodePin 应用图标（多尺寸 .ico + png）。

用法： python make_icon.py
输出： assets/icon.ico  assets/icon.png  assets/icon32.png
"""
import os

from PIL import Image, ImageDraw

SS = 1024  # 超采样尺寸
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")

TOP = (0x32, 0x35, 0x3C)     # 顶部 #32353C
BOT = (0x17, 0x17, 0x19)     # 底部 #171719
ACCENT = (0x4F, 0xC1, 0xFF)  # VSCode 蓝 #4FC1FF
WHITE = (0xE6, 0xE6, 0xE6)


def gradient(size, top, bot):
    img = Image.new("RGB", (1, size))
    px = img.load()
    for y in range(size):
        t = y / (size - 1)
        px[0, y] = tuple(int(top[i] + (bot[i] - top[i]) * t) for i in range(3))
    return img.resize((size, size))


def round_line(d, pts, width, color):
    """带圆头的折线：逐段画线 + 端点补圆。"""
    d.line(pts, fill=color, width=width, joint="curve")
    r = width // 2
    for x, y in (pts[0], pts[-1]):
        d.ellipse([x - r, y - r, x + r, y + r], fill=color)


def build():
    base = Image.new("RGBA", (SS, SS), (0, 0, 0, 0))
    mask = Image.new("L", (SS, SS), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, SS - 1, SS - 1], radius=int(SS * 0.225), fill=255)

    bg = gradient(SS, TOP, BOT).convert("RGBA")
    base.paste(bg, (0, 0), mask)

    d = ImageDraw.Draw(base, "RGBA")
    # 内描边：微弱高光，让图标在深色任务栏上有轮廓
    d.rounded_rectangle([5, 5, SS - 6, SS - 6], radius=int(SS * 0.215), outline=(255, 255, 255, 30), width=5)

    w = int(SS * 0.086)
    # 左右尖括号 < >
    round_line(d, [(SS * 0.398, SS * 0.315), (SS * 0.252, SS * 0.5), (SS * 0.398, SS * 0.685)], w, ACCENT)
    round_line(d, [(SS * 0.602, SS * 0.315), (SS * 0.748, SS * 0.5), (SS * 0.602, SS * 0.685)], w, ACCENT)
    # 中间斜杠
    round_line(d, [(SS * 0.556, SS * 0.268), (SS * 0.444, SS * 0.732)], int(w * 0.86), WHITE)

    os.makedirs(OUT, exist_ok=True)
    png = base.resize((256, 256), Image.LANCZOS)
    png.save(os.path.join(OUT, "icon.png"))
    base.resize((32, 32), Image.LANCZOS).save(os.path.join(OUT, "icon32.png"))
    png.save(
        os.path.join(OUT, "icon.ico"),
        format="ICO",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    print("icon written:", OUT)


if __name__ == "__main__":
    build()
