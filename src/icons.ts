// 界面图标的集中映射：语义名 → @jannchie/icons 的图标对象，模板里用 <JIcon :icon="ICONS.search" />。
// 组件不直接 import IconXxx，以后换图标只改这一个文件。
import type { Icon } from "@jannchie/icons";
import {
  IconArrowLeft,
  IconBuilding,
  IconCalendar,
  IconCamera,
  IconClock,
  IconDots,
  IconDownload,
  IconExternalLink,
  IconEyeOff,
  IconFlag,
  IconLoadingGlobe,
  IconGithub,
  IconInfo,
  IconKeyboard,
  IconLanguages,
  IconLayers,
  IconLocate,
  IconMapPin,
  IconMoon,
  IconNavigation,
  IconTheme,
  IconSun,
  IconMinus,
  IconPlus,
  IconSearch,
  IconSearchX,
  IconTv,
  IconUndo,
  IconX,
} from "@jannchie/icons";

export const ICONS = {
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
  undo: IconUndo,
  updated: IconCalendar, // 地标最近一次新增或改动的日期
  credit: IconCamera,
  zoomIn: IconPlus,
  zoomOut: IconMinus,
  locate: IconLocate,
  language: IconLanguages,
  series: IconLayers, // 系列：叠在一起的几部作品
  info: IconInfo,
  keyboard: IconKeyboard,
  github: IconGithub,
  navigate: IconNavigation,
  download: IconDownload,
  more: IconDots, // 收起来的次要操作（作品的外部链接、KML）
  external: IconExternalLink, // 跳到站外原文
  report: IconFlag, // 报告地标问题
  adult: IconEyeOff, // 成人向作品默认隐藏
  themeAuto: IconTheme, // 专门表示「跟随系统」：太阳与月亮各占一半
  themeLight: IconSun,
  themeDark: IconMoon,
} satisfies Record<string, Icon>;
