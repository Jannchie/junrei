"""生成社交分享图（og.png）。标志与 PWA 图标由 scripts/gen-icons.mts 从 src/logo.ts 生成，先跑那个：
  node --experimental-strip-types scripts/gen-icons.mts && python scripts/gen_icons.py
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent.parent / "public" / "icons"
LAND = (242, 244, 246)
INK = (29, 29, 31)


def main():
    icon = Image.open(OUT / "icon-512.png").convert("RGBA").resize((220, 220), Image.Resampling.LANCZOS)
    og = Image.new("RGB", (1200, 630), LAND)
    og.paste(icon, (150, 205), icon)
    d = ImageDraw.Draw(og)
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
    print("og ->", OUT / "og.png")


if __name__ == "__main__":
    main()
