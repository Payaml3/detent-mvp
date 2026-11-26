# Feature Specification: Marketing website (landing page and sub-pages)

**Feature Branch**: `web/002-marketing-site`

**Created**: 2026-11-18

**Status**: Draft

**Input**: User description: "Can we build first the website landing and its internal pages?"

**Parent**: [001-detent-mvp](../001-detent-mvp/spec.md), requirement FR-111 and stories WEB-01 to WEB-08 (slice P4),
built early by founder decision D-14. Founder decisions D-15 to D-18 set pricing, contact placeholders, naming and
brand ([decisions.md](../001-detent-mvp/decisions.md#decision-log)).

## Clarifications

### Session 2026-11-18

- Q: Show prices? → A: No. Name the free shadow report, Pilot, Growth and Scale; every plan says "Talk to us" (D-15).
- Q: Where do "Book a demo" and "Request sandbox access" go before the booking page and access inbox exist? → A: Clearly marked placeholders in one config value each; nothing is sent (D-16).
- Q: Name? → A: The name "DekernAI" (B-01, replacing the working name Detent) from one setting; domain stays a placeholder (D-17).
- Q: Look? → A: The spec/07 brand tokens (D-18), in a cinematic dark-blue style with an original WebGL watch-escapement scene, built in-house after reviewing GetLayers references; glows and gradients allowed (D-19).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - A head of payments understands the product and books a demo (Priority: P1)

A buyer from a platform that holds user balances lands on the home page and, within the first screen, learns what
DekernAI is ("agentic payment controls") and what to do (book a demo). Scrolling, they see how it works, the three
layers, why it suits irreversible rails, security, use cases and how pricing works.

**Why this priority**: the site's job is demos (spec/11: the signal is a "yes" to the shadow report).

**Independent Test**: build the site, open the home page, and run the honesty and structure checks.

**Acceptance Scenarios**:

1. **Given** the home page, **When** it loads, **Then** it shows the eleven sections of spec/08 in order, the category line, a "Book a demo" button and a "Request sandbox access" link.
2. **Given** any page, **When** checked, **Then** it contains no logos, testimonials, customer counts, volume figures, certification badges, "licensed" or "regulated" claims, "payments company" or "payment provider", and no competitor's wording.
3. **Given** the "What goes wrong?" demonstration, **When** the visitor picks a scenario, **Then** the same payment ID moves through the real states for that scenario and the transfer count never exceeds one; without script, the scenarios are readable as text.

### User Story 2 - A buyer checks security, product depth and the design-partner offer (Priority: P1)

**Acceptance Scenarios**:

1. **Given** the Security page, **When** read, **Then** it covers non-custodial design, audit and replay, the kill switch and EU hosting, and every roadmap item is labelled roadmap (for example "SOC 2: planned").
2. **Given** the Design partners page, **When** read, **Then** it explains the free shadow report and how the data is handled.
3. **Given** the Product page, **When** read, **Then** it explains the decision, orchestration and operations layers.

### User Story 3 - Results, code and legal pages are honest before they exist (Priority: P2)

**Acceptance Scenarios**:

1. **Given** no results file, **When** the site builds, **Then** the measured-results section states that results are not yet published and shows no figures; **Given** a results file, **Then** every figure is labelled "test-network evaluation, [date]".
2. **Given** the developer section, **When** read, **Then** the code is labelled pre-launch until the tested snippets of DOC-04 replace it.
3. **Given** the privacy, terms and cookie pages, **When** read, **Then** each is marked "draft for legal review".

### Edge Cases

- Booking URL or sales inbox unset: the buttons render with the placeholder target and the build check lists them, so a placeholder can't ship silently.
- Name changes: one config value changes every title, heading and footer.
- No JavaScript: every section, including the demonstration's scenarios, is readable.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-201**: The home page MUST present spec/08's eleven sections in order with primary CTA "Book a demo" and secondary "Request sandbox access" (WEB-01).
- **FR-202**: All pages MUST use "agentic payment controls" (or "payment controls") and MUST NOT contain the banned claims and phrases listed in User Story 1, scenario 2 (WEB-01, spec/00, spec/product-definition).
- **FR-203**: The Product, Security and Design partners pages MUST exist with the content in User Story 2 (WEB-02).
- **FR-204**: The results section MUST read a results file at build time and show either labelled figures or the not-yet-published state (WEB-03).
- **FR-205**: The developer section MUST show one payment-intent request in eight languages, labelled pre-launch (WEB-04, partial until DOC-04).
- **FR-206**: Privacy, terms and cookie pages MUST exist, marked "draft for legal review"; analytics MUST be off unless configured and cookie-less (WEB-05).
- **FR-207**: Booking and access targets MUST come from one config file, and the build MUST report any placeholder still in use (WEB-06 partial, D-16).
- **FR-208**: Every title MUST pair the name with "payment controls"; the build MUST emit sitemap.xml, Open Graph images and schema.org Organization and SoftwareApplication markup (WEB-08).
- **FR-209**: The brand name MUST come from one setting (D-17).
- **FR-210**: Pricing MUST list the free shadow report, Pilot, Growth and Scale with "Talk to us" and no prices (D-15).

Out of scope now: the status page (WEB-07, needs the deployed services), deployment and the domain.

## Success Criteria *(mandatory)*

- **SC-201**: A stranger reading the first screen for five seconds can say what the product is and what to do.
- **SC-202**: The honesty and structure checks pass on every built page, with zero banned phrases.
- **SC-203**: The design inspector reports 0 FAIL at 1440, 768 and 390 pixels.
- **SC-204**: Every page is usable without JavaScript and from the keyboard.

## Assumptions

- Plan descriptions beyond what the sources say (what Pilot, Growth and Scale include) are sample content for the founder to confirm.
- The demonstration's scenarios and the hero's payment are the fictional fixtures (Bluefin Components Ltd, INV-2026-0142), labelled as an example.
