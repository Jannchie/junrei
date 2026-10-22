<script setup lang="ts">
import { markShapes } from "../logo";

defineProps<{ size?: number }>();

// 只有针的图形，颜色取 currentColor（样式里设为主题色）；镂空部分透明
const shapes = markShapes("currentColor");
</script>

<template>
  <!-- 针在 100×100 里只占中间一段，裁掉两侧空白，和文字并排时不显得小 -->
  <svg class="logo-mark" viewBox="18 8 64 78" :width="size ?? 24" :height="size ?? 24" aria-hidden="true" v-html="shapes" />
</template>

<style scoped>
.logo-mark {
  flex: none;
  color: var(--accent);
}
</style>
