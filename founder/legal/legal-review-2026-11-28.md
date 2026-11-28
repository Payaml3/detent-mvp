# Legal review of the website, policies and onboarding copy (28 Nov 2026)

**Not legal advice.** This is a structured first pass by Claude against UK law and the CAP Code, so that a
solicitor's review is shorter and cheaper. Everything under "Needs professional sign-off" must go to a
UK solicitor (and a regulatory specialist for the perimeter question) before the site goes public.

Scope: every page of `apps/site` (home, product, security, onboarding, access, status, privacy, terms,
cookies, 404), the dashboard's sign-in, invite and access-request pages (`apps/api/src/detent/dashboard`),
and the data the access form and dashboard collect. Docs (Mintlify) were not reviewed in depth; they are
not live yet.

Drafts for the solicitor sit beside this file: `privacy-notice-draft.md`, `terms-of-use-draft.md`,
`cookie-notice-draft.md`.

## Priority 1: fix before the site is public

| # | Issue | Law | Status |
|---|---|---|---|
| 1 | **No privacy notice, but the access form is live.** The form posts name, work email, job title, company and free text to `app.dekernai.com`, and `/privacy/` is a placeholder. Data must be described at the point of collection: who the controller is, purpose, lawful basis, retention, recipients, transfers, rights, the right to complain to the ICO. | UK GDPR Art 13; DPA 2018 | Partly fixed in PR: the form now says how the data is used and links `/privacy/`; the privacy page states the facts about the form today. The full notice is drafted for the solicitor. **Founder: decide whether to pause the form until the full notice is live.** |
| 2 | **No legal entity on the site.** The site never says who operates DekernAI. A UK company must show its registered name, number, place of registration and registered office on its website; any business must show its name, geographic address and email; a sole trader using "DekernAI" as a trading name must show their own name and an address. The privacy notice also needs the controller's identity. | Companies Act 2006 s82 and Part 41; Company, LLP and Business (Names and Trading Disclosures) Regs 2015; Electronic Commerce (EC Directive) Regs 2002 reg 6 | **Founder input needed:** is there a company yet? Its name, number and registered office. Then add a footer line and fill the drafts. The "© 2026 DekernAI" line should name the legal owner too. |
| 3 | **ICO data protection fee.** Any controller processing personal data (lead and sandbox user data here) must pay the fee unless exempt; marketing and customer-admin processing is not exempt. | Data Protection (Charges and Information) Regs 2018 | **Founder:** register and pay tier 1 on ico.org.uk once the entity exists. |
| 4 | **The site describes a pre-launch product in the present tense.** Visitors read "sends exactly once", "Hosted in a UK or EU cloud region", ten platform use cases on rails the product does not have yet (CHAPS, Bacs, RTP, ACH, SWIFT, Solana, card, mobile wallets), with no statement that nothing is live. Omitting that is material information for a buyer. | CAP Code 3.1, 3.3, 3.7, 3.9; Business Protection from Misleading Marketing Regs 2008 (B2B) | Fixed in PR: footer on every page says "Pre-launch. The sandbox moves no real money; live payments start only after onboarding and your sign-off." The use-case caption says these are designs and names what the sandbox covers today. Wording avoids "test" and "prototype" (founder rule of 27 Nov). |
| 5 | **Claims of regulated functions the product does not perform.** Use cases said "Safeguarded funds reconciled every day" (neobanks/EMIs), "Client money: daily check of client balances against the bank" (brokers) and "A record ready for your regulator" (iGaming). Nothing in the spec builds safeguarding or client-money reconciliation, which are regulatory duties of the client (FCA safeguarding rules for payment and e-money firms in force from May 2026; CASS for investment firms). These read as compliance claims. | CAP Code 3.1, 3.7; BPRs 2008; `founder/gates.json` legal gate | Fixed in PR: replaced with what the product does (exceptions case, bank confirmation matched to the ledger, who decided under which rule version). A test now blocks these phrases. |
| 6 | **Regulatory perimeter not confirmed.** The site says DekernAI "routes", "sends" and "fails over" payments and "tells [rails] what to do". Whether software that instructs a client's rails, without holding funds or keys, is outside payment-institution, e-money, FSMA and cryptoasset rules depends on the facts and the contracts. `founder/business-context.md` already lists this as open. | PSRs 2017 (incl. Sch 1 Pt 2 para 2(j) technical service providers); EMRs 2011; FSMA 2000 s19; MLRs 2017; the new UK cryptoasset regime; EU PSD2/PSD3, MiCA | **Solicitor (regulatory).** Ask for a written perimeter opinion, including whether "sends" should become "instructs your rail to send". |

## Priority 2: fix before the first pilot contract

| # | Issue | Law | Recommendation |
|---|---|---|---|
| 7 | **Absolute claims.** "Held until it's right. Sent exactly once." (closing tagline), "sends exactly once" (product, spine), "No path executes unchecked", "takes effect before the next payment". The engineering backs them (partial unique indexes, the lock), but in a B2B sale a website statement can become a pre-contract representation, and "exactly once" depends on the rail too. | CAP 3.7 (hold evidence); Misrepresentation Act 1967; UCTA 1977 | Keep a short substantiation file (the invariant tests) and make sure the master agreement has an entire-agreement clause. Consider "at most one confirmed transfer per payment" where the claim is technical. "Never paid twice" was changed to "No retry pays twice" in the PR, which matches its body text. |
| 8 | **Implied team and service levels.** "Your payments lead or our on-call engineer can engage it" (security), "Solutions lead", "Engineering support", "Founder and counsel" (onboarding). If there is no on-call rota or named roles yet, this implies a service the business cannot yet give. | CAP 3.1; BPRs 2008 | Founder: confirm. If not true yet, reword to "we" or state the support hours the pilot contract will set. Not changed in the PR because it is a business commitment. |
| 9 | **Data location.** Onboarding said "Data is processed in the UK or EU". The app and database are in Frankfurt (Render, Neon), but the AI provider and Vercel are US companies, and the security page itself makes UK/EU AI processing a precondition, not a fact. | UK GDPR Ch V (Arts 44-49) | Fixed in PR: "hosted in a UK or EU region… The agreement names every region and every subprocessor." Before client data: a subprocessor list, and the transfer basis for each US provider (UK Extension to the EU-US Data Privacy Framework, or an IDTA/UK Addendum). |
| 10 | **No terms accepted at sandbox sign-up.** The invite page sets a password with no link to terms or privacy and no acceptance step. | Contract formation; UK GDPR Art 13 | Engineering story: add "By continuing you accept the sandbox terms and have read the privacy notice" with links on `invite.html`, and record the accepted version and time in the audit log. Links in the dashboard footer too. |
| 11 | **Cookie notice misses the dashboard.** `dekernai.com` sets no cookies (checked: no third-party hosts in the built site). `app.dekernai.com` sets a signed session cookie for sign-in and CSRF, including on the access-form thank-you page. These are strictly necessary and need no consent, but must be described. | PECR reg 6 (as amended by the Data (Use and Access) Act 2025) | Draft cookie notice covers both domains. If analytics are added later, the 2025 exemption for some analytics needs clear information and an easy opt-out. |
| 12 | **Retention not set for leads.** Request logs: 30 days (G-19). Sandbox data: until the organisation expires plus 30 days. Access requests: no period. | UK GDPR Art 5(1)(e) | Proposal for the solicitor: delete declined or unanswered requests after 12 months; keep converted leads for the life of the relationship. G-19 itself is already waiting for legal review. |
| 13 | **Append-only audit log and erasure.** The audit trail is hash-chained and never edited. Where events carry names or emails (console users, approvers, website-form leads), a deletion request cannot be met by editing. | UK GDPR Arts 5, 17(3), 25 | Engineering: keep personal data out of chained payloads (reference user IDs; keep the person's details in a deletable table) and record the lawful basis for retaining audit events (legal obligation, or legitimate interests with a written assessment). Add to the records of processing. |
| 14 | **Automated decisions about end users.** In Auto mode, clients' users (players, investors, customers) get withdrawals held or released by rules without a person. The client is the controller and DekernAI the processor, but the DPA and product must let the client give the safeguards (information, human review on request). | UK GDPR Art 22 (and the DUAA 2025 changes); EU AI Act for EU clients | Solicitor: cover in the DPA and the client terms. Fraud detection is not "high risk" under the EU AI Act, but get this confirmed for EU clients. |

## Priority 3: tidy-ups

| # | Issue | Recommendation |
|---|---|---|
| 15 | **Fictional names that could be real.** Bluefin Components Ltd, Quill Studio Ltd, Harbor Logistics GmbH, Marlow Prop Traders, Fenwick Tutors, Kestrel Market, Northwind Creators appear beside "changed bank details", "possible fraud" or "far above usual". Each section is labelled sample data, which helps. | Founder: a two-minute Companies House search for each name; rename any that match a real company. Claude could not reach Companies House from here. |
| 16 | **Trade marks.** "DekernAI" clearance is an open founder item. Third-party marks (USDC, Base, Ethereum, Faster Payments, SEPA Instant, CHAPS, Confirmation of Payee) are used descriptively, which is normally fine; don't use their logos or imply partnership. | Solicitor or a trade mark attorney: clearance search in UK and EU classes 9, 36 and 42 before launch. |
| 17 | **Marketing emails later.** Replying to a form request is fine. Any newsletter or outreach needs PECR care: corporate addresses can be emailed with an opt-out; sole traders and partnerships need consent or a soft opt-in. Every email must identify the sender. | Keep "we don't add you to a mailing list" true until there is a consent checkbox. |
| 18 | **Certification roadmap.** SOC 2, ISO 27001 and a penetration test are listed as "planned", and a test enforces that. Good. Avoid dates until they are booked. | No change. |
| 19 | **Financial promotions.** The site markets B2B software, not investments or cryptoassets, so the FSMA s21 and cryptoasset promotion rules should not bite. The crypto-exchange use case shows USDC withdrawals as an example only. | Ask the regulatory solicitor to confirm in the same perimeter opinion (item 6). |
| 20 | **Status page.** Fetches `app.dekernai.com/status.json` from the visitor's browser, which shows that server the visitor's IP. Now stated on the privacy page. | No further change. |

## What already works well

- No cookies or third-party trackers on `dekernai.com`; fonts are self-hosted.
- Honest guards exist as tests: no "licensed", "regulated", "certified", "trusted by", testimonials or client
  names; certifications only as roadmap items; sample data labelled.
- Non-custodial positioning ("never holds client funds or keys") is consistent and is the strongest point for
  the perimeter analysis.
- The onboarding copy promises a DPA before any client data arrives, and KYB before an account exists.
- The site is `noindex` until launch.

## Needs professional sign-off (send to the solicitor)

1. **Regulatory perimeter opinion** (UK and EU): payment services, e-money, FSMA, MLRs, cryptoassets; and the
   wording "sends" versus "instructs" (item 6, 19).
2. **Final privacy notice, cookie notice and website and sandbox terms** (drafts beside this file).
3. **Master agreement, DPA (Art 28), SLA and liability**, including the entire-agreement clause, how website
   statements relate to the contract (item 7), automated decisions (item 14) and subprocessors and transfers
   (item 9).
4. **Retention**: G-19 and the lead period (item 12), and the audit-log lawful basis (item 13).
5. **Trade mark clearance** for DekernAI (item 16).

## Founder actions (no solicitor needed)

1. Give the legal entity details (item 2), then register with the ICO (item 3).
2. Decide whether to pause the access form until the full privacy notice is live (item 1).
3. Confirm the on-call and named-role wording, or let it be softened (item 8).
4. Check the fictional company names on Companies House (item 15).
