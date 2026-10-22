<script setup lang="ts">
import JunreiApp from "../src/components/JunreiApp.vue";
import type { Props } from "./index.server";

defineProps<Props>();
</script>

<template>
  <JunreiApp :popular="popular" />
</template>
