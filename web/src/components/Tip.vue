<script setup lang="ts">
// Info-bulle commune, placée près du pointeur sans sortir de l'écran.
import { nextTick, ref, watch } from "vue";
import { tip } from "@/lib/tip";

const el = ref<HTMLElement | null>(null);
const pos = ref({ left: 0, top: 0 });

watch(
  () => [tip.show, tip.x, tip.y, tip.lines] as const,
  async () => {
    if (!tip.show) return;
    await nextTick();
    const w = el.value?.offsetWidth ?? 0,
      h = el.value?.offsetHeight ?? 0;
    let x = tip.x + 14,
      y = tip.y + 14;
    if (x + w > innerWidth - 8) x = tip.x - w - 14;
    if (y + h > innerHeight - 8) y = tip.y - h - 14;
    pos.value = { left: Math.max(8, x), top: Math.max(8, y) };
  },
);
</script>

<template>
  <div v-show="tip.show" ref="el" class="tip" role="tooltip" :style="{ left: pos.left + 'px', top: pos.top + 'px' }">
    <template v-for="(line, i) in tip.lines" :key="i">
      <br v-if="i" />
      <template v-for="(p, k) in line" :key="k">
        <template v-if="typeof p === 'string'">{{ p }}</template>
        <b v-else-if="'b' in p">{{ p.b }}</b>
        <span v-else class="m">{{ p.m }}</span>
      </template>
    </template>
  </div>
</template>
