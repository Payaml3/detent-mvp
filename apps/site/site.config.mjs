// The one place the site's name, domain and contact targets live (decisions D-16, D-17).
// Values starting with PLACEHOLDER are reported at build time in dist/placeholders.json.
export default {
  brandName: "Dekernai",
  category: "agentic payment controls",
  siteUrl: "https://example.invalid",
  // Pre-launch: pages carry noindex and robots.txt blocks crawlers. Set true at launch (founder decision).
  indexable: false,
  bookingUrl: "PLACEHOLDER:booking-url",
  accessFormAction: "PLACEHOLDER:access-endpoint",
  salesInbox: "PLACEHOLDER:sales-inbox",
};
