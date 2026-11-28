// The one place the site's name, palette, domain and contact targets live (D-16, D-17, B-01).
// Values starting with PLACEHOLDER are reported at build time in dist/placeholders.json.
export default {
  brandName: "DekernAI",
  // Colour palette: one of the keys in src/styles/palettes.mjs. The founder chose Graphite and safety orange (B-02).
  palette: "graphite",
  category: "agentic payment controls",
  // Hero art: "agent" (an AI agent streams payments into the settled D), "mark" (the D alone) or "layers".
  heroArt: "agent",
  // Primary domain (B-01, registered 2026-11-26). www.dekernai.com and dekernai.co.uk redirect here in Vercel.
  siteUrl: "https://dekernai.com",
  // Pre-launch: pages carry noindex and robots.txt blocks crawlers. Set true at launch (founder decision).
  indexable: false,
  // WEB-06: the access form posts to the dashboard's DSH-10 endpoint on the live deploy (FND-07).
  accessFormAction: "https://app.dekernai.com/access-requests",
  // WEB-07: the status page reads the deploy's public health summary from the visitor's browser.
  statusUrl: "https://app.dekernai.com/status.json",
  // Sign in for clients and DekernAI admins: one page; the app sends each to their dashboard or the admin.
  signInUrl: "https://app.dekernai.com/dashboard/login",
  salesInbox: "sales@dekernai.com",
  // Developer docs on Mintlify, published from docs/ on every merge to main (founder, 2026-11-28).
  docsUrl: "https://dekern-ai.mintlify.site",
};
