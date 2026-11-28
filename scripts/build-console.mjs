import { build } from "esbuild";
import { copyFile, mkdir } from "node:fs/promises";
await mkdir("web/vendor/console", { recursive: true });
await build({
  entryPoints: ["frontend/charts.js"],
  outfile: "web/vendor/console/charts.js",
  bundle: true,
  format: "esm",
  minify: true,
  target: "es2020",
  legalComments: "eof",
});
for (const [from, to] of [
  ["logo.png", "web/assets/logo.png"],
  [
    "node_modules/geist/dist/fonts/geist-sans/Geist-Variable.woff2",
    "web/assets/fonts/geist-sans.woff2",
  ],
  [
    "node_modules/geist/dist/fonts/geist-mono/GeistMono-Variable.woff2",
    "web/assets/fonts/geist-mono.woff2",
  ],
  ["node_modules/geist/LICENSE.txt", "web/assets/fonts/geist-LICENSE.txt"],
  ["node_modules/echarts/LICENSE", "web/vendor/console/ECHARTS-LICENSE"],
  ["node_modules/echarts/NOTICE", "web/vendor/console/ECHARTS-NOTICE"],
])
  await copyFile(from, to);
