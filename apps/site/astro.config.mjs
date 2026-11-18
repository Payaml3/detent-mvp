import { defineConfig } from "astro/config";
import sitemap from "@astrojs/sitemap";
import { writeFileSync } from "node:fs";
import config from "./site.config.mjs";

// Writes dist/placeholders.json so a placeholder can never ship unnoticed (FR-207, D-16).
const placeholderReport = {
  name: "placeholder-report",
  hooks: {
    "astro:build:done": ({ dir, logger }) => {
      const placeholders = Object.entries(config)
        .filter(([, v]) => typeof v === "string" && v.startsWith("PLACEHOLDER"))
        .map(([key, value]) => ({ key, value }));
      writeFileSync(new URL("placeholders.json", dir), JSON.stringify({ placeholders }, null, 2));
      if (placeholders.length) logger.warn(`placeholders still in use: ${placeholders.map((p) => p.key).join(", ")}`);
    },
  },
};

export default defineConfig({
  site: config.siteUrl,
  trailingSlash: "ignore",
  build: { format: "directory" },
  integrations: [sitemap(), placeholderReport],
  // three.js (the hero scene) is one lazily loaded chunk of about 520 kB; nothing else comes close.
  vite: { build: { chunkSizeWarningLimit: 600 } },
});
