import config from "../../site.config.mjs";
// Pre-launch the whole site is closed to crawlers; at launch (config.indexable) it opens and lists the sitemap.
export const GET = () =>
  new Response(
    config.indexable
      ? `User-agent: *\nAllow: /\nSitemap: ${new URL("/sitemap-index.xml", config.siteUrl).href}\n`
      : "User-agent: *\nDisallow: /\n",
    { headers: { "Content-Type": "text/plain" } },
  );
