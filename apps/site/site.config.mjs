// The one place the site's name, domain and contact targets live (decisions D-16, D-17).
// Values starting with PLACEHOLDER are reported at build time in dist/placeholders.json.
export default {
  brandName: "Dekernai",
  category: "agentic payment controls",
  // Primary domain (B-01, registered 2026-11-26). www.dekernai.com and dekernai.co.uk redirect here in Vercel.
  siteUrl: "https://dekernai.com",
  // Pre-launch: pages carry noindex and robots.txt blocks crawlers. Set true at launch (founder decision).
  indexable: false,
  bookingUrl: "PLACEHOLDER:booking-url",
  accessFormAction: "PLACEHOLDER:access-endpoint",
  salesInbox: "PLACEHOLDER:sales-inbox",
};
