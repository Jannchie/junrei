// junrei 的标志：长着猫耳的定位针，中间是镂空圆环，左上一颗小星。坐标系 100×100。
// 页面里的标志（LogoMark.vue）和 PWA 图标、分享图（scripts/gen-icons.ts）都从这里生成。

/** 定位针外形（含两只猫耳），左右对称 */
const PIN =
  "M50 18.75C47 18.75 44.6 19.2 43.5 19.75C38 13.5 31 11 23.5 10.8C22 10.8 21.3 11.7 21.2 13" +
  "C20.5 22 22 31 25.6 38.2C25.3 40 25.2 42 25.4 44C26.5 57 38 70 47.8 81.8C48.9 83.2 51.1 83.2 52.2 81.8" +
  "C62 70 73.5 57 74.6 44C74.8 42 74.7 40 74.4 38.2C78 31 79.5 22 78.8 13C78.7 11.7 78 10.8 76.5 10.8" +
  "C69 11 62 13.5 56.5 19.75C55.4 19.2 53 18.75 50 18.75Z";

/** 左耳内侧的耳毛缺口；右耳用镜像 */
const EAR_TUFT =
  "M27.6 20.9C27.6 20.3 28.1 20 28.7 20.1C30.3 20.3 31.8 20.6 33.4 21.3C31.8 23.5 30.4 26.5 29.4 30.2" +
  "C28.2 29.6 26.9 28.6 27.1 27.6C27.3 26.9 28.3 26.4 28.7 25.8C28.9 25.4 28.8 25 28.6 24.6C28.1 23.4 27.7 22.2 27.6 20.9Z";

/** 左耳内侧的弧线 */
const EAR_LINE = "M25.4 13.6C30 16.3 33.4 19.7 36.2 23.6";

const SPARKLE = "M42.1 7.2C42.4 8.6 42.8 9 44.2 9.3C42.8 9.6 42.4 10 42.1 11.4C41.8 10 41.4 9.6 40 9.3C41.4 9 41.8 8.6 42.1 7.2Z";

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
    `<path d="${EAR_TUFT}" fill="${tile}"/>`,
    `<path d="${EAR_TUFT}" fill="${tile}" transform="${mirror}"/>`,
    `<path d="${EAR_LINE}" fill="none" stroke="${tile}" stroke-width="1.3" stroke-linecap="round"/>`,
    `<path d="${EAR_LINE}" fill="none" stroke="${tile}" stroke-width="1.3" stroke-linecap="round" transform="${mirror}"/>`,
    `<circle cx="50" cy="43.75" r="15.25" fill="${tile}"/>`,
    `<circle cx="50" cy="43.75" r="8.6" fill="${mark}"/>`,
    `<path d="${SPARKLE}" fill="${mark}"/>`,
  ].join("");
  return bleed
    ? `<rect width="100" height="100" fill="${tile}"/><g transform="translate(50 50) scale(0.78) translate(-50 -47)">${art}</g>`
    : `<rect width="100" height="100" rx="16" fill="${tile}"/>${art}`;
}

export const logoSvg = (o: LogoOptions & { size?: number }) =>
  `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" width="${o.size ?? 100}" height="${o.size ?? 100}">${logoShapes(o)}</svg>`;
