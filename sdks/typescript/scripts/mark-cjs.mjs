// The package is ESM ("type": "module"), so the CommonJS build says it is CommonJS in its own folder.
import { writeFileSync } from "node:fs";
writeFileSync(new URL("../dist/cjs/package.json", import.meta.url), JSON.stringify({ type: "commonjs" }) + "\n");
