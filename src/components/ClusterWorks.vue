<script setup lang="ts">
// 气泡弹出菜单的内容（ClusterPopover 的插槽）：气泡里的全部地标按系列分组（和首页卡片一样，同一系列的各季合成一项），
// 列出系列封面、名称和在这里的地标数。名称与系列来自页面已经加载的作品索引（index.worker），不发网络请求。
// 点一项打开整个系列；地图不会因为点了气泡而缩放。
import type { Feature } from "geojson";
import { computed, shallowRef, watch } from "vue";
import { showAdult } from "../adult";
import { groupBangumi } from "../bangumi-index";
import { imageUrl } from "../format";
import { useI18n, workNames } from "../i18n";

const props = defineProps<{ features: Feature[]; count: number }>();
const emit = defineEmits<{ pick: [bangumiId: number] }>();

const { pickName } = useI18n();

/** 每部作品在这个气泡里的地标数 */
const counts = computed(() => {
  const m = new Map<number, number>();
  for (const f of props.features) {
    const b = Number(f.properties?.b);
    m.set(b, (m.get(b) ?? 0) + 1);
  }
  return [...m.entries()];
});

const works = shallowRef<{ id: number; name: string; cover: string | null; n: number }[]>([]);
watch([counts, showAdult], async ([c, adult]) => {
  const cards = await groupBangumi(c, adult);
  if (c !== counts.value) return;
  works.value = cards.map((x) => ({ id: x.id, name: pickName(workNames(x)), cover: x.cover ? imageUrl(x.cover) : null, n: x.inView }));
}, { immediate: true });
</script>

<template>
  <div class="cluster-works">
    <div class="head stat">{{ count.toLocaleString() }}</div>
    <button v-for="w in works" :key="w.id" type="button" class="work" @click="emit('pick', w.id)">
      <img v-if="w.cover" :src="w.cover" alt="" loading="lazy" referrerpolicy="no-referrer" />
      <span v-else class="ph" />
      <span class="name">{{ w.name }}</span>
      <span class="n stat">{{ w.n }}</span>
    </button>

  </div>
</template>

<style scoped>
.cluster-works {
  width: 260px;
  font-size: 13px;
}
.head {
  padding: 10px 40px 6px 12px;
  font-weight: 600;
}
.stat {
  font-variant-numeric: tabular-nums;
}
.work {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 5px 10px;
  font: inherit;
  text-align: left;
  color: inherit;
  background: none;
  border: 0;
  cursor: pointer;
}
.work:hover {
  background: var(--hover);
}
.work img,
.ph {
  flex: none;
  width: 27px;
  height: 36px;
  object-fit: cover;
  border-radius: 4px;
  background: var(--hover);
}
.name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.n {
  color: var(--muted);
  font-size: 12px;
}
</style>
