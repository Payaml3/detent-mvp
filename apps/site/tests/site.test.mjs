// Checks over the built site (dist/). Run `npm run build` first.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, existsSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import config from "../site.config.mjs";

const DIST = new URL("../dist/", import.meta.url).pathname;
const PAGES = {
  home: "index.html",
  product: "product/index.html",
  security: "security/index.html",
  partners: "design-partners/index.html",
  access: "access/index.html",
  privacy: "privacy/index.html",
  terms: "terms/index.html",
  cookies: "cookies/index.html",
};
const read = (p) => readFileSync(join(DIST, p), "utf8");
const text = (html) => html.replace(/<script[\s\S]*?<\/script>|<style[\s\S]*?<\/style>/g, " ").replace(/<[^>]+>/g, " ").replace(/\s+/g, " ");
const allHtml = () => Object.values(PAGES).map((p) => [p, read(p)]);

test("every page is built", () => {
  for (const p of Object.values(PAGES)) assert.ok(existsSync(join(DIST, p)), `missing ${p}`);
});

test("honesty: no banned claims or phrases on any page (spec/00, spec/08, product-definition)", () => {
  const banned = [
    /payments? company/i, /payment provider/i, /trust layer/i, /guardrails/i, /\blicensed\b/i, /\bregulated\b/i,
    /testimonial/i, /trusted by/i, /\bour (customers|clients)\b/i, /\bcertified\b/i, /as seen (in|on)/i,
  ];
  for (const [p, html] of allHtml()) {
    const t = text(html);
    for (const rx of banned) assert.ok(!rx.test(t), `${p} contains ${rx}`);
  }
});

test("honesty: certifications appear only as roadmap items", () => {
  for (const [p, html] of allHtml()) {
    for (const m of text(html).matchAll(/(SOC 2|ISO 27001|pen(etration)? test)[^.]{0,60}/gi)) {
      assert.match(m[0], /planned|roadmap/i, `${p}: "${m[0]}" must be labelled roadmap`);
    }
  }
});

test("home: category wording, Book a demo as the main action, Request access beside it (B-04)", () => {
  const html = read(PAGES.home);
  assert.match(text(html), /agentic payment controls/i);
  const hero = html.split('data-section="hero"')[1].split("data-section=")[0];
  const buttons = [...hero.matchAll(/<a[^>]*class="([^"]*\bbutton\b[^"]*)"[^>]*>\s*([^<]+)/g)].map((m) => [m[1], m[2].trim()]);
  assert.deepEqual(buttons[0], ["button", "Book a demo"], "the first hero button is Book a demo");
  assert.ok(buttons.some(([cls, label]) => /secondary/.test(cls) && label === "Request access"), "Request access is the secondary button");
  assert.match(hero, /href="\/access\/"[^>]*>\s*Request access/, "Request access leads to the onboarding intake");
});

test("home: the sections of docs/design/landing-page-ux.md, in order", () => {
  const order = ["hero", "problem", "spine", "use-cases", "rules", "irreversible", "roles", "onboarding", "faq", "close", "footer"];
  const found = [...read(PAGES.home).matchAll(/data-section="([a-z-]+)"/g)].map((m) => m[1]);
  assert.deepEqual(found.filter((s) => order.includes(s)), order);
});

test("home: the rules decide, said once, and never the AI", () => {
  const t = text(read(PAGES.home));
  assert.match(t, /Agents prepare\. Your rules decide\./);
  assert.ok(!/\b(AI|agent)s? (decides?|approves?)\b/i.test(t.replace(/Does the AI approve payments\?/, "")), "no copy says the AI decides or approves");
});

test("home: the demonstration's scenarios are readable without JavaScript", () => {
  const t = text(read(PAGES.home));
  for (const s of ["timeout", "screening", "reverted", "approve"]) assert.match(read(PAGES.home), new RegExp(`data-scenario="${s}"`));
  assert.match(t, /UNKNOWN/);
  assert.match(t, /A failure can retry\. A rejection can.t\. No retry ever becomes a second payment\./);
});

test("results: left off the home page, with no figures, while there is no results file", () => {
  const html = read(PAGES.home);
  assert.ok(!html.includes('data-section="results"'), "no empty results section");
  assert.ok(!/data-figure=/.test(html));
});

test("developers: one request in eight languages, with the sandbox, in the engineering panel", () => {
  const html = read(PAGES.home);
  const section = html.split('id="panel-engineering"')[1].split("data-section=")[0];
  for (const lang of ["cURL", "Python", "TypeScript", "Go", "Java", "C#", "PHP", "Ruby"]) assert.ok(section.includes(`>${lang}<`), lang);
  assert.match(text(section), /sandbox/i);
  assert.match(section, /<pre[\s\S]*payment_intents/);
});

test("onboarding: the seven phases of the client journey, plans 'Talk to us', no prices (B-04)", () => {
  const html = read(PAGES.home);
  const section = text(html.split('data-section="onboarding"')[1].split("data-section=")[0]);
  for (const phase of ["Discovery", "Contract and due diligence", "Sandbox integration", "Policy setup", "Shadow on live traffic", "Go-live", "Scale"]) assert.match(section, new RegExp(phase));
  for (const plan of ["Pilot", "Growth", "Scale"]) assert.match(section, new RegExp(plan));
  assert.match(section, /Talk to us/);
  assert.ok(!/(free|Pilot|Growth|Scale)[^.]{0,40}[$£€]\s?\d/i.test(section), "no prices next to a plan");
});

test("no free shadow report: shadow is a phase after the contract, never a free offer (B-04)", () => {
  for (const p of Object.values(PAGES)) {
    const t = text(read(p));
    assert.ok(!/free shadow|shadow report/i.test(t), `${p} offers a shadow report`);
  }
});

test("sub-pages carry their required content", () => {
  const sec = text(read(PAGES.security));
  for (const w of [/non-custodial/i, /audit/i, /replay/i, /kill switch/i, /EU/]) assert.match(sec, w);
  assert.match(sec, /SOC 2[^.]{0,40}planned/i);
  const dp = text(read(PAGES.partners));
  assert.match(dp, /seven phases/i);
  assert.match(dp, /data processing agreement/i);
  const acc = text(read(PAGES.access));
  for (const w of [/discovery/i, /KYB/, /registration email/i]) assert.match(acc, w);
  assert.ok(!/simulated rails|\.13|\.42|What would you like to test/i.test(acc), "access is the onboarding intake, not a sandbox sign-up");
  const prod = text(read(PAGES.product));
  for (const w of [/decision/i, /orchestration/i, /operations/i]) assert.match(prod, w);
});

test("legal pages are marked draft for legal review", () => {
  for (const p of [PAGES.privacy, PAGES.terms, PAGES.cookies]) assert.match(text(read(p)), /draft for legal review/i);
});

test("SEO: titles pair the name with 'payment controls'; sitemap, robots, OG image, schema.org", () => {
  for (const [p, html] of allHtml()) {
    const title = html.match(/<title>([^<]*)<\/title>/)?.[1] ?? "";
    assert.ok(title.includes(config.brandName) && /payment controls/i.test(title), `${p}: ${title}`);
    assert.match(html, /<meta property="og:image" content="[^"]+"/);
  }
  assert.ok(existsSync(join(DIST, "sitemap.xml")) || existsSync(join(DIST, "sitemap-index.xml")));
  assert.ok(existsSync(join(DIST, "robots.txt")));
  assert.ok(existsSync(join(DIST, "og.jpg")), "the og:image file exists");
  const home = read(PAGES.home);
  assert.match(home, /"@type":"Organization"/);
  assert.match(home, /"@type":"WebSite"/);
  assert.match(home, /"@type":"SoftwareApplication"/);
  assert.match(home, /"logo":"https:[^"]+"/, "the organisation has a logo");
  for (const [p, html] of allHtml()) {
    for (const m of ["og:site_name", "og:locale", "og:image:alt"]) assert.match(html, new RegExp(`property="${m}"`), `${p}: ${m}`);
    for (const m of ["twitter:title", "twitter:description", "twitter:image"]) assert.match(html, new RegExp(`name="${m}"`), `${p}: ${m}`);
  }
  assert.match(home.match(/<title>([^<]*)<\/title>/)[1], /stablecoin/i, "the home title names the rails");
});

test("404: a real not-found page with navigation, never indexed", () => {
  const html = read("404.html");
  assert.match(html, /<meta name="robots" content="noindex, nofollow"/);
  assert.match(html, /href="\/product\/"/);
});

test("launch: opening the site to search also removes the noindex header in vercel.json", () => {
  const vercel = JSON.parse(readFileSync(new URL("../vercel.json", import.meta.url), "utf8"));
  const noindexHeader = JSON.stringify(vercel.headers ?? []).includes("noindex");
  assert.equal(noindexHeader, !config.indexable, "X-Robots-Tag noindex must be sent exactly while config.indexable is false");
});

test("the name comes from one setting: no page source hard-codes it", () => {
  const walk = (d) => readdirSync(d).flatMap((f) => (statSync(join(d, f)).isDirectory() ? walk(join(d, f)) : [join(d, f)]));
  const src = new URL("../src/", import.meta.url).pathname;
  for (const f of walk(src)) {
    if (!/\.(astro|mjs|js|ts|css)$/.test(f)) continue;
    assert.ok(!readFileSync(f, "utf8").includes(config.brandName), `${f} hard-codes the brand name`);
  }
});

test("placeholders are reported, never silently shipped", () => {
  const report = JSON.parse(read("placeholders.json"));
  const expected = Object.entries(config).filter(([, v]) => typeof v === "string" && v.startsWith("PLACEHOLDER")).map(([k]) => k);
  assert.deepEqual(report.placeholders.map((p) => p.key).sort(), expected.sort());
});

test("no third-party requests: scripts, styles and fonts are served locally", () => {
  for (const [p, html] of allHtml()) {
    for (const m of html.matchAll(/<(script|link)[^>]+(src|href)="(https?:)?\/\/[^"]+"/g)) {
      if (/rel="(canonical|alternate)"/.test(m[0])) continue;
      assert.fail(`${p} loads a third-party resource: ${m[0].slice(0, 120)}`);
    }
  }
});

test("pre-launch: every page is no-index and robots.txt blocks crawlers until config.indexable is true", () => {
  if (config.indexable) return;
  for (const [p, html] of allHtml()) assert.match(html, /<meta name="robots" content="noindex, nofollow"/, p);
  assert.match(read("robots.txt"), /Disallow: \//);
});
