<script setup lang="ts">
// Bouton « ▶ Revoir » d'une touche : ouvre la fenêtre du lecteur 3D (ActionReplay.vue). Absent si la touche ne
// peut pas se retrouver dans le replay (partie ou indice d'image inconnus) ou sans joueur connecté.
import { computed } from "vue";
import { REVOIR, replayLabel } from "@/copy";
import { canReplay, openReplay, type ReplayReq } from "@/lib/replay";
import { store } from "@/lib/store";

const props = defineProps<{
  match: string | null | undefined;
  i: number | null | undefined;
  action: string;
  clock?: number | null;
  vb?: number | null;
  va?: number | null;
  date?: string | null;
}>();

const shown = computed(() => !!store.moi && canReplay(props.match, props.i));

function open(e: MouseEvent) {
  const req: ReplayReq = { match: props.match!, i: props.i!, action: props.action, clock: props.clock, vb: props.vb, va: props.va, date: props.date };
  openReplay(req, e.currentTarget);
}
</script>

<template>
  <button v-if="shown" type="button" class="rv pl-tag" :aria-label="replayLabel({ action, clock })" aria-haspopup="dialog" @click.stop="open">{{ REVOIR.button }}</button>
</template>
