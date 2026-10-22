// junrei 的标志：长着猫耳的定位针，中间是镂空圆环。坐标系 100×100。
// 页面里的标志（LogoMark.vue）和 PWA 图标、分享图（scripts/gen-icons.ts）都从这里生成。

/** 定位针外形（含两只猫耳），左右对称 */
const PIN =
  "M50 18.75C47 18.75 44.6 19.2 43.5 19.75C38 13.5 31 11 23.5 10.8C22 10.8 21.3 11.7 21.2 13" +
  "C20.5 22 22 31 25.6 38.2C25.3 40 25.2 42 25.4 44C26.5 57 38 70 47.8 81.8C48.9 83.2 51.1 83.2 52.2 81.8" +
  "C62 70 73.5 57 74.6 44C74.8 42 74.7 40 74.4 38.2C78 31 79.5 22 78.8 13C78.7 11.7 78 10.8 76.5 10.8" +
  "C69 11 62 13.5 56.5 19.75C55.4 19.2 53 18.75 50 18.75Z";

/** 左耳的内耳：顺着耳朵轮廓、从耳尖延伸到耳根的一块圆润形状；右耳用镜像 */
const INNER_EAR =
  "M27.2 17.4C30.6 19 33.2 21.1 34.9 23.6C32.6 25 30.6 26.9 29.1 29.2C27.7 25.6 27.1 21.5 27.2 17.4Z";

export interface LogoOptions {
  /** 底色（也是镂空部分的颜色） */
  tile: string;
  /** 针的颜色 */
  mark: string;
  /** true：铺满底色、针缩进安全区（Android 可遮罩图标）；false：圆角方形 */
  bleed?: boolean;
}

/** 标志内部的 SVG 片段（不含外层 <svg>），坐标系 100×100 */
export function logoShapes({ tile, mark, bleed = false }: LogoOptions): string {
  const mirror = "translate(100 0) scale(-1 1)";
  const art = [
    `<path d="${PIN}" fill="${mark}"/>`,
    `<path d="${INNER_EAR}" fill="${tile}"/>`,
    `<path d="${INNER_EAR}" fill="${tile}" transform="${mirror}"/>`,
    `<circle cx="50" cy="43.75" r="15.25" fill="${tile}"/>`,
    `<circle cx="50" cy="43.75" r="8.6" fill="${mark}"/>`,
  ].join("");
  return bleed
    ? `<rect width="100" height="100" fill="${tile}"/><g transform="translate(50 50) scale(0.78) translate(-50 -47)">${art}</g>`
    : `<rect width="100" height="100" rx="16" fill="${tile}"/>${art}`;
}

export const logoSvg = (o: LogoOptions & { size?: number }) =>
  `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" width="${o.size ?? 100}" height="${o.size ?? 100}">${logoShapes(o)}</svg>`;
