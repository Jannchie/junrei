// 成人向作品（Bangumi 标为 nsfw 的成人游戏、动画等）照常收录，但默认隐藏：搜索、概览、地图、系列列表里都不出现，
// 在「数据来源」浮层里打开开关后才显示。选择存在浏览器里；服务端渲染一律按隐藏处理，挂载后再读取。
import { ref } from "vue";

const STORAGE_KEY = "junrei:adult";

export const showAdult = ref(false);

export function initAdult() {
  try {
    showAdult.value = localStorage.getItem(STORAGE_KEY) === "1";
  } catch {}
}

export function setShowAdult(on: boolean) {
  showAdult.value = on;
  try {
    if (on) localStorage.setItem(STORAGE_KEY, "1");
    else localStorage.removeItem(STORAGE_KEY);
  } catch {}
}
