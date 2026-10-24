<script setup lang="ts">
// 气泡弹出卡片的内容（ClusterPopover 的插槽）：气泡里的地标按作品分组，列出作品名、在这里的地标数和一张截图。
// 点作品打开它（选中作品）；「放大查看」由用户主动点，地图不自动缩放。
import type { Feature } from "geojson";
import { computed, shallowRef, watch } from "vue";
import { fetchDetail } from "../detail";
import { imageUrl } from "../format";
import { useI18n, workNames } from "../i18n";

const props = defineProps<{ features: Feature[]; count: number }>();
const emit = defineEmits<{ pick: [bangumiId: number]; zoomIn: [] }>();

const { t, pickName } = useI18n();

/** 作品 id → 这个气泡里属于它的地标 id（取出的地标有上限，数量按取出的算） */
const groups = computed(() => {
  const m = new Map<number, string[]>();
  for (const f of props.features) {
    const b = Number(f.properties?.b);
    m.set(b, [...(m.get(b) ?? []), String(f.properties?.p)]);
  }
  return [...m.entries()].sort((a, b) => b[1].length - a[1].length).slice(0, 8);
});

const works = shallowRef<{ id: number; name: string; image: string | null; n: number }[]>([]);
watch(groups, async (gs) => {
  const out = await Promise.all(gs.map(async ([id, points]) => {
    const d = await fetchDetail(id).catch(() => null);
    const image = d?.points.find((p) => points.includes(p.id) && p.image)?.image ?? null;
    return { id, name: d ? pickName(workNames(d)) : `#${id}`, image: image ? imageUrl(image) : null, n: points.length };
  }));
  if (gs === groups.value) works.value = out;
}, { immediate: true });
</script>

<template>
  <div class="cluster-works">
    <div class="head stat">{{ count.toLocaleString() }}</div>
    <button v-for="w in works" :key="w.id" type="button" class="work" @click="emit('pick', w.id)">
      <img v-if="w.image" :src="w.image" alt="" referrerpolicy="no-referrer" />
      <span v-else class="ph" />
      <span class="name">{{ w.name }}</span>
      <span class="n stat">{{ w.n }}</span>
    </button>
    <div class="foot">
      <button type="button" @click="emit('zoomIn')">{{ t("zoomIn") }}</button>
    </div>
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
  width: 48px;
  height: 27px;
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
.foot {
  display: flex;
  justify-content: flex-end;
  padding: 6px 8px 8px;
  border-top: 1px solid var(--line);
}
.foot button {
  padding: 4px 10px;
  font: inherit;
  font-size: 12px;
  color: var(--fg);
  background: var(--hover);
  border: 0;
  border-radius: 999px;
  cursor: pointer;
}
</style>
