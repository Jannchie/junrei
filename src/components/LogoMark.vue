<script setup lang="ts">
import { logoShapes } from "../logo";

defineProps<{ size?: number }>();

// 底色取 currentColor（样式里设为主题色），暗色模式下跟着变
const shapes = logoShapes({ tile: "currentColor", mark: "#ffffff" });
</script>

<template>
  <svg class="logo-mark" viewBox="0 0 100 100" :width="size ?? 24" :height="size ?? 24" aria-hidden="true" v-html="shapes" />
</template>

<style scoped>
.logo-mark {
  flex: none;
  color: var(--accent);
}
</style>
