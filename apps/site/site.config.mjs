// The one place the site's name, palette, domain and contact targets live (D-16, D-17, B-01).
// Values starting with PLACEHOLDER are reported at build time in dist/placeholders.json.
export default {
  brandName: "DekernAI",
  // Colour palette: one of the keys in src/styles/palettes.mjs. The founder chose B, Parchment and seal (B-02).
  palette: "b",
  category: "agentic payment controls",
  siteUrl: "https://example.invalid",
  // Pre-launch: pages carry noindex and robots.txt blocks crawlers. Set true at launch (founder decision).
  indexable: false,
  bookingUrl: "PLACEHOLDER:booking-url",
  accessFormAction: "PLACEHOLDER:access-endpoint",
  salesInbox: "PLACEHOLDER:sales-inbox",
};
