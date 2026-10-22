"""生成 PWA 图标与社交分享图（鸟居标志）。改了设计后重跑：python scripts/gen_icons.py"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent.parent / "public" / "icons"
ACCENT = (240, 70, 45)
WHITE = (255, 255, 255)
LAND = (242, 244, 246)
INK = (29, 29, 31)
S = 1024  # 先画大图再缩小，边缘更平滑


def torii(draw: ImageDraw.ImageDraw, cx: float, cy: float, size: float, color):
    """以 (cx, cy) 为中心、宽 size 的鸟居：笠木（略上翘）、贯、两根柱子"""
    w = size
    u = w / 20
    top = cy - w * 0.42
    # 笠木：两端上翘的梯形
    draw.polygon([(cx - w / 2, top), (cx + w / 2, top), (cx + w * 0.44, top + 2.2 * u), (cx - w * 0.44, top + 2.2 * u)], fill=color)
    draw.rectangle([cx - w * 0.38, top + 2.2 * u, cx + w * 0.38, top + 3.2 * u], fill=color)
    # 贯
    draw.rectangle([cx - w * 0.42, top + 6 * u, cx + w * 0.42, top + 7.6 * u], fill=color)
    # 额束
    draw.rectangle([cx - 0.8 * u, top + 3.2 * u, cx + 0.8 * u, top + 6 * u], fill=color)
    # 柱子：略向外倾
    for side in (-1, 1):
        x_top, x_bot = cx + side * w * 0.27, cx + side * w * 0.31
        draw.polygon([(x_top - 1.1 * u, top + 3.2 * u), (x_top + 1.1 * u, top + 3.2 * u), (x_bot + 1.2 * u, cy + w * 0.42), (x_bot - 1.2 * u, cy + w * 0.42)], fill=color)


def icon(bleed: bool) -> Image.Image:
    """bleed=True 为可遮罩图标：铺满底色，图形缩进安全区（中心 80%）"""
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if bleed:
        d.rectangle([0, 0, S, S], fill=ACCENT)
        torii(d, S / 2, S / 2 + S * 0.02, S * 0.5, WHITE)
    else:
        d.rounded_rectangle([0, 0, S - 1, S - 1], radius=S * 0.225, fill=ACCENT)
        torii(d, S / 2, S / 2 + S * 0.02, S * 0.62, WHITE)
    return img


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    plain, maskable = icon(False), icon(True)
    for size in (192, 512):
        plain.resize((size, size), Image.Resampling.LANCZOS).save(OUT / f"icon-{size}.png")
        maskable.resize((size, size), Image.Resampling.LANCZOS).save(OUT / f"maskable-{size}.png")
    # iOS 主屏图标不支持透明，用铺满版
    maskable.resize((180, 180), Image.Resampling.LANCZOS).convert("RGB").save(OUT / "apple-touch-icon.png")
    plain.resize((32, 32), Image.Resampling.LANCZOS).save(OUT / "favicon-32.png")

    og = Image.new("RGB", (1200, 630), LAND)
    d = ImageDraw.Draw(og)
    og.paste(plain.resize((220, 220), Image.Resampling.LANCZOS), (150, 205), plain.resize((220, 220), Image.Resampling.LANCZOS))
    try:
        title = ImageFont.truetype("C:/Windows/Fonts/msyhbd.ttc", 92)
        sub = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 36)
        small = ImageFont.truetype("C:/Windows/Fonts/segoeui.ttf", 28)
    except OSError:
        title = sub = small = ImageFont.load_default()
    d.text((420, 222), "圣地巡礼地图", font=title, fill=INK)
    d.text((424, 348), "聖地巡礼マップ · Anime Pilgrimage Map", font=sub, fill=(110, 110, 115))
    d.text((1150, 580), "junrei.jannchie.com", font=small, fill=(150, 150, 155), anchor="rs")
    og.save(OUT / "og.png", optimize=True)
    print("icons ->", OUT)


if __name__ == "__main__":
    main()
