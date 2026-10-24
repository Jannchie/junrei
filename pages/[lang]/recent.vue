<script setup lang="ts">
import JunreiApp from "../../src/components/JunreiApp.vue";
import type { Props } from "./recent.server";

defineProps<Props>();
</script>

<template>
  <JunreiApp :lang="lang" :initial-recent="recent" />
</template>
