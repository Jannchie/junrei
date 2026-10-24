<script setup lang="ts">
import PrivacyPage from "../src/components/PrivacyPage.vue";
import type { Props } from "./privacy.server";

defineProps<Props>();
</script>

<template>
  <PrivacyPage :lang="lang" />
</template>
