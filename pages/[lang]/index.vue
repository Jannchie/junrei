<script setup lang="ts">
import JunreiApp from "../../src/components/JunreiApp.vue";
import type { Props } from "./index.server";

defineProps<Props>();
</script>

<template>
  <JunreiApp :lang="lang" :popular="popular" />
</template>
