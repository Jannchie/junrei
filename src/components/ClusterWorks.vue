<script setup lang="ts">
// 气泡弹出卡片的内容（ClusterPopover 的插槽）：气泡里的地标按系列分组（和首页卡片一样，同一系列的各季合成一项），
// 列出系列名、在这里的地标数和一张截图。点一项打开整个系列；「放大查看」由用户主动点，地图不自动缩放。
import type { Feature } from "geojson";
import { computed, shallowRef, watch } from "vue";
import { fetchDetail } from "../detail";
import { imageUrl } from "../format";
import { useI18n, workNames } from "../i18n";
import { groupOf } from "../series";

const props = defineProps<{ features: Feature[]; count: number }>();
const emit = defineEmits<{ pick: [bangumiId: number]; zoomIn: [] }>();

const { t, pickName } = useI18n();

/** 作品 id → 这个气泡里属于它的地标 id（取出的地标有上限，数量按取出的算） */
const byWork = computed(() => {
  const m = new Map<number, string[]>();
  for (const f of props.features) {
    const b = Number(f.properties?.b);
    m.set(b, [...(m.get(b) ?? []), String(f.properties?.p)]);
  }
  return m;
});

/** 系列（key 是系列代表作的 id，单独的作品就是它自己）：名称、地标数、一张截图 */
const works = shallowRef<{ id: number; name: string; image: string | null; n: number }[]>([]);
watch(byWork, async (m) => {
  const details = await Promise.all([...m.keys()].map((id) => fetchDetail(id).catch(() => null)));
  if (m !== byWork.value) return;
  const series = new Map<number, { id: number; name: string; image: string | null; n: number }>();
  for (const d of details) {
    if (!d) continue;
    const points = m.get(d.id) ?? [];
    const g = groupOf(d);
    const cur = series.get(g.key);
    const image = d.points.find((p) => points.includes(p.id) && p.image)?.image ?? null;
    if (cur) {
      cur.n += points.length;
      cur.image ??= image ? imageUrl(image) : null;
    } else {
      const rep = g.works.find((w) => w.id === g.key) ?? d;
      series.set(g.key, { id: g.key, name: pickName(workNames(rep)), image: image ? imageUrl(image) : null, n: points.length });
    }
  }
  works.value = [...series.values()].sort((a, b) => b.n - a.n).slice(0, 8);
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
