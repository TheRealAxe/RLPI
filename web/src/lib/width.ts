// Largeur d'un élément, suivie avec ResizeObserver : les graphiques SVG sont dessinés à la largeur réelle.
import { onBeforeUnmount, onMounted, ref, type Ref } from "vue";

export function useWidth(el: Ref<HTMLElement | null>, min = 60): Ref<number> {
  const w = ref(min);
  let ro: ResizeObserver | null = null;
  onMounted(() => {
    if (!el.value) return;
    const measure = () => {
      const v = Math.max(min, Math.round(el.value?.getBoundingClientRect().width ?? min));
      if (Math.abs(v - w.value) >= 1) w.value = v;
    };
    measure();
    if (typeof ResizeObserver !== "undefined") {
      ro = new ResizeObserver(measure);
      ro.observe(el.value);
    }
  });
  onBeforeUnmount(() => ro?.disconnect());
  return w;
}
