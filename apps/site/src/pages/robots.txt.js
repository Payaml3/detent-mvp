import config from "../../site.config.mjs";
export const GET = () =>
  new Response(`User-agent: *\nAllow: /\nSitemap: ${new URL("/sitemap-index.xml", config.siteUrl).href}\n`, {
    headers: { "Content-Type": "text/plain" },
  });
