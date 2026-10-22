// 由 src/logo.ts 生成 PWA 图标与网站小图标。改了标志设计后重跑：
//   node --experimental-strip-types scripts/gen-icons.mts && python scripts/gen_icons.py
// （后者用这里生成的 icon-512.png 合成社交分享图）
import { mkdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import sharp from "sharp";
import { logoSvg } from "../src/logo.ts";

const OUT = fileURLToPath(new URL("../public/icons/", import.meta.url));
mkdirSync(OUT, { recursive: true });

const TILE = "#7a5af8"; // 与 src/theme.css 的 --accent（亮色）一致
const MARK = "#ffffff";

async function png(name: string, size: number, bleed = false, flatten = false) {
  let img = sharp(Buffer.from(logoSvg({ tile: TILE, mark: MARK, bleed, size: 512 }))).resize(size, size);
  if (flatten) img = img.flatten({ background: TILE }); // iOS 主屏图标不支持透明
  await img.png().toFile(OUT + name);
}

await Promise.all([
  png("icon-192.png", 192),
  png("icon-512.png", 512),
  png("maskable-192.png", 192, true),
  png("maskable-512.png", 512, true),
  png("apple-touch-icon.png", 180, true, true),
  png("favicon-32.png", 32),
]);
console.log("icons ->", OUT);
