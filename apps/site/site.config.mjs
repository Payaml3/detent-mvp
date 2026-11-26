// The one place the site's name, palette, domain and contact targets live (D-16, D-17, B-01).
// Values starting with PLACEHOLDER are reported at build time in dist/placeholders.json.
export default {
  brandName: "DekernAI",
  // Colour palette: one of the keys in src/styles/palettes.mjs. The founder chose Graphite and safety orange (B-02).
  palette: "graphite",
  category: "agentic payment controls",
  // Hero art: "mark" (the settled D in particles, follows the pointer) or "layers" (the three glass rules).
  heroArt: "mark",
  // Primary domain (B-01, registered 2026-11-26). www.dekernai.com and dekernai.co.uk redirect here in Vercel.
  siteUrl: "https://dekernai.com",
  // Pre-launch: pages carry noindex and robots.txt blocks crawlers. Set true at launch (founder decision).
  indexable: false,
  bookingUrl: "PLACEHOLDER:booking-url",
  accessFormAction: "PLACEHOLDER:access-endpoint",
  salesInbox: "PLACEHOLDER:sales-inbox",
};
