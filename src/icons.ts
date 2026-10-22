// 界面图标的集中映射：语义名 → @jannchie/icons 的图标对象，模板里用 <JIcon :icon="ICONS.search" />。
// 组件不直接 import IconXxx，以后换图标只改这一个文件。
import type { Icon } from "@jannchie/icons";
import {
  IconArrowLeft,
  IconBuilding,
  IconCamera,
  IconClock,
  IconLoadingGlobe,
  IconGithub,
  IconInfo,
  IconLanguages,
  IconLocate,
  IconMapPin,
  IconMoon,
  IconTheme,
  IconSun,
  IconMinus,
  IconPlus,
  IconSearch,
  IconSearchX,
  IconTorii,
  IconTv,
  IconX,
} from "@jannchie/icons";

export const ICONS = {
  logo: IconTorii,
  search: IconSearch,
  clear: IconX,
  noResult: IconSearchX,
  loading: IconLoadingGlobe,
  back: IconArrowLeft,
  bangumi: IconTv,
  point: IconMapPin,
  city: IconBuilding,
  episode: IconTv,
  time: IconClock,
  credit: IconCamera,
  zoomIn: IconPlus,
  zoomOut: IconMinus,
  locate: IconLocate,
  language: IconLanguages,
  info: IconInfo,
  github: IconGithub,
  themeAuto: IconTheme, // 专门表示「跟随系统」：太阳与月亮各占一半
  themeLight: IconSun,
  themeDark: IconMoon,
} satisfies Record<string, Icon>;
