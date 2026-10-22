// 界面图标的集中映射：语义名 → @jannchie/icons 的图标对象，模板里用 <JIcon :icon="ICONS.search" />。
// 组件不直接 import IconXxx，以后换图标只改这一个文件。
import type { Icon } from "@jannchie/icons";
import {
  IconArrowLeft,
  IconBuilding,
  IconCalendar,
  IconCamera,
  IconClock,
  IconLoadingGlobe,
  IconLocate,
  IconMapPin,
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
  updated: IconCalendar,
  credit: IconCamera,
  zoomIn: IconPlus,
  zoomOut: IconMinus,
  locate: IconLocate,
} satisfies Record<string, Icon>;
