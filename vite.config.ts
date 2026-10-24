import { defineConfig } from "vite";
import { voidPlugin } from "void";
import { voidVue } from "@void/vue/plugin";

export default defineConfig({
  plugins: [voidPlugin(), voidVue()],
  // @mapette/* 以 link: 引用本地仓库时，会从它自己的 node_modules 解析这些依赖，页面上就有两份 vue / maplibre
  resolve: { dedupe: ["vue", "maplibre-gl", "pmtiles"] },
});
