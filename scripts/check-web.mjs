import { readdir } from "node:fs/promises";
import { join } from "node:path";
import { spawnSync } from "node:child_process";
async function check(directory) {
  for (const item of await readdir(directory, { withFileTypes: true })) {
    if (item.name === "vendor") continue;
    const path = join(directory, item.name);
    if (item.isDirectory()) await check(path);
    else if (item.name.endsWith(".js")) {
      const result = spawnSync(process.execPath, ["--check", path], {
        stdio: "inherit",
      });
      if (result.status !== 0) process.exit(result.status || 1);
    }
  }
}
await check("web");
await check("frontend");
