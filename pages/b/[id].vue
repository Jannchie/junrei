<script setup lang="ts">
import JunreiApp from "../../src/components/JunreiApp.vue";
import type { Props } from "./[id].server";

defineProps<Props>();
</script>

<template>
  <JunreiApp :initial-detail="detail" />
</template>
