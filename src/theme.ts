// 外观：跟随系统 / 浅色 / 深色。配色在 theme.css 里用 light-dark() 定义，这里只切 <html data-theme>。
// 首次绘制前由 void.config.ts 里的内联脚本先应用保存的选择，避免刷新时闪一下。
import { computed, ref } from "vue";

export type ThemePref = "auto" | "light" | "dark";
const STORAGE_KEY = "junrei:theme";
const ORDER: ThemePref[] = ["auto", "light", "dark"];

export const themePref = ref<ThemePref>("auto");

const media = typeof matchMedia === "undefined" ? null : matchMedia("(prefers-color-scheme: dark)");
const systemDark = ref(media?.matches ?? false);
media?.addEventListener("change", (e) => (systemDark.value = e.matches));

/** 实际生效的是否为深色（地图据此重读配色） */
export const isDark = computed(() => (themePref.value === "auto" ? systemDark.value : themePref.value === "dark"));

function apply(pref: ThemePref) {
  // 切换瞬间完成：临时关掉页面上所有 CSS 过渡，下一帧再恢复
  const style = document.createElement("style");
  style.textContent = "*,*::before,*::after{transition:none!important}";
  document.head.appendChild(style);
  // 先改属性再改状态：依赖 isDark 的监听（地图重读配色）触发时，新配色已经生效
  if (pref === "auto") delete document.documentElement.dataset.theme;
  else document.documentElement.dataset.theme = pref;
  themePref.value = pref;
  getComputedStyle(document.documentElement).color; // 强制按新配色算一次样式，再撤掉禁用
  requestAnimationFrame(() => style.remove());
}

export function initTheme() {
  let saved: string | null = null;
  try {
    saved = localStorage.getItem(STORAGE_KEY);
  } catch {}
  apply(ORDER.includes(saved as ThemePref) ? (saved as ThemePref) : "auto");
}

export function cycleTheme() {
  const next = ORDER[(ORDER.indexOf(themePref.value) + 1) % ORDER.length];
  apply(next);
  try {
    localStorage.setItem(STORAGE_KEY, next);
  } catch {}
}
