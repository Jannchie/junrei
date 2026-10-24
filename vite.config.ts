import { createHash } from "node:crypto";
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { defineConfig, type Plugin } from "vite";
import { voidPlugin } from "void";
import { voidVue } from "@void/vue/plugin";

/**
 * 往构建出来的 sw.js 里写构建号（替换 __BUILD__）：按打包产物的文件名（都带内容哈希）算，
 * 代码变了才变，只更新 public/data 的数据同步部署不会让用户看到更新提示
 */
function swBuildStamp(): Plugin {
  return {
    name: "junrei:sw-build-stamp",
    apply: "build",
    writeBundle(options, bundle) {
      const file = join(options.dir ?? "", "sw.js");
      if (!existsSync(file)) return; // 服务端那一份构建里没有 sw.js
      const build = createHash("sha256").update(Object.keys(bundle).sort().join("\n")).digest("hex").slice(0, 12);
      writeFileSync(file, readFileSync(file, "utf8").replace("__BUILD__", build));
    },
  };
}

export default defineConfig({
  plugins: [voidPlugin(), voidVue(), swBuildStamp()],
});
