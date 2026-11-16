import { mount } from "@vue/test-utils";
import { h } from "vue";
import { describe, expect, it } from "vitest";
import Rich from "./Rich.vue";

const render = (text: string) => mount({ render: () => h("p", h(Rich, { text })) });

describe("Rich", () => {
  it("met en gras **…** et <b>…</b>", () => {
    const w = render("a **b** c <b>d</b> e");
    expect(w.findAll("b").map((b) => b.text())).toEqual(["b", "d"]);
    expect(w.element.textContent).toBe("a b c d e");
  });
  it("laisse toute autre balise en texte", () => {
    const w = render("</script><img src=x onerror=alert(1)>");
    expect(w.find("img").exists()).toBe(false);
    expect(w.element.textContent).toBe("</script><img src=x onerror=alert(1)>");
  });
});
