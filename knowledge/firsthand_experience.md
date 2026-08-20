# Firsthand experience anchors

## Purpose

Real-world experience signals for E-E-A-T (Experience, Expertise, Authoritativeness, Trust). Writer Agent pulls **one or more** anchors from this file into every article to demonstrate real-world authority. Google's helpful content system and AI search engines (Perplexity, ChatGPT Search, AI Overviews) reward content grounded in verifiable lived experience.

## CRITICAL RULES — read before writing anything

- **Never invent entries.** Every entry must trace to a real source: a real customer with consent, a real JVL employee, a real internal data point.
- **Writer Agent may use any entry whose `verified_by` is filled.** For customer-side material `consent_status: confirmed` is required on top of that. Entries with `verified_by: null` are off-limits.
- **If no relevant verified anchor exists for the article topic, the Writer must write `TODO: experience anchor needed`** — not fabricate one.
- **No fake testimonials.** Fabricated customer quotes violate Canada Competition Act s. 74.01, US FTC 16 CFR Part 465, and EU UCPD — and they are explicitly forbidden by `claims_constraints.md`.
- **Operational data** about JVL's own production, history, or process needs no external consent. The business confirms it directly — a questionnaire answered by JVL counts as verification, and `verified_by` records which one. A named individual is needed only when the entry is presented as that person's words.
- **Citations.** When the Writer uses an anchor, it must paraphrase or quote faithfully and may reference a generic source ("our production team", "a JVL service technician") without exposing internal IDs or private customer info.

## Entry schema

Every entry is a YAML-style block:

```
- id: <short slug, e.g. ceo-quote-offline-first>
  type: <story | quote | data_point | craftsmanship | founder_quote | review_aggregate>
  claim: <the text the Writer may paraphrase or quote>
  source: <where it came from — interview date, ticket #, review URL, production log>
  date_added: <YYYY-MM-DD>
  consent_status: <pending | confirmed | not_required>
  verified_by: <name + role of JVL team member who confirmed accuracy>
  usage_notes: <restrictions on how to cite, anonymisation requirements, anything off-limits>
  relevant_topics: <comma-separated keywords / topics this anchor fits>
```

`consent_status: not_required` applies ONLY to JVL's own operational/historical/process data — never to anything customer-side.

---

## SECTION 1 — Customer stories

Real customer experiences with the ECHO. Requires written/recorded consent from the customer (email, support ticket, signed release). Anonymisation is allowed and preferred — use first name + region, not full identity.

**Status: EMPTY.** Confirmed 2026-08-19: no customer has yet given written consent. Nothing may be written here until one does — a paraphrased "typical customer" is a fabricated testimonial, not a summary.

Intake process, when it starts:
1. Opt-in card in every shipped ECHO unit.
2. Customer Success collects responses at the 3-month follow-up.
3. Explicit written consent recorded before any use in content.
4. Anonymise per usage_notes.
5. Entry added here with `consent_status: confirmed`.

---

## SECTION 2 — Product and design rationale

Why the ECHO is built the way it is. Gathered 2026-08-19 through the business
intake questionnaire rather than a recorded interview, so these are **not
quotable as attributed statements** — the Writer may use the reasoning, not put
it in someone's mouth. Attaching a name requires an actual interview.

**Status: USABLE — reasoning confirmed by the business. No attributable speaker, so paraphrase only.**

- id: why-22-inch-touchscreen
  type: quote
  claim: "22\" is the sweet spot between playability and footprint. It provides enough screen space for comfortable gameplay while keeping ECHO compact enough for a bar top, counter, or table. Touchscreen controls also eliminate the space required for joysticks and button panels, reduce reliance on heavily used mechanical controls, and make the machine immediately understandable to first-time players."
  source: business intake questionnaire, 2026-08-19
  date_added: 2026-08-19
  consent_status: not_required
  verified_by: JVL business intake questionnaire, 2026-08-19
  usage_notes: Paraphrase as product reasoning. Do not attribute to a named person or present as a quote until an interview is on record. Keep the durability point relative — "reduces reliance on heavily used mechanical controls", never "cannot fail" or "never breaks". A touchscreen can fail too, and one reader who has seen one fail discards the whole article; the hedged version is also the stronger argument, because it survives that reader.
  relevant_topics: touchscreen vs joystick, choosing a home arcade, maintenance, countertop fit, durability

- id: why-offline-by-design
  type: quote
  claim: "Running fully offline is a design decision, not a limitation. All 149 games, the leaderboards and the tournaments run locally, so there is no account, no Wi-Fi setup, no download, no subscription and no waiting. For a home owner that is simplicity; for a venue it is one less thing that can take the machine out of service."
  source: business intake questionnaire, 2026-08-19
  date_added: 2026-08-19
  consent_status: not_required
  verified_by: JVL business intake questionnaire, 2026-08-19
  usage_notes: Paraphrase only, no named attribution. The offline claim itself is already a confirmed product fact in claims_constraints.md.
  relevant_topics: offline play, plug-and-play, reliability, venue uptime

- id: hardest-production-step
  type: craftsmanship
  claim: "The hardest step is final integration and QC — display, touchscreen, computer, audio, power, cabinet and the swivel mechanism all have to behave as one system. Assembling the individual components is comparatively straightforward; guaranteeing that the finished unit runs stably and looks flawless is not."
  source: business intake questionnaire, 2026-08-19
  date_added: 2026-08-19
  consent_status: not_required
  verified_by: JVL business intake questionnaire, 2026-08-19
  usage_notes: Strong build-quality anchor. Paraphrase; no named attribution.
  relevant_topics: build quality, manufacturing, QC, premium positioning

- id: why-swivel-base
  type: quote
  claim: "The 360-degree base comes straight out of how a countertop machine actually gets used. The ECHO sits in the middle of a bar or a table with several people around it, so instead of moving a heavy machine or swapping seats, you turn the screen to the next player."
  source: business intake questionnaire, 2026-08-19
  date_added: 2026-08-19
  consent_status: not_required
  verified_by: JVL business intake questionnaire, 2026-08-19
  usage_notes: Paraphrase only. The 360-degree base and head-to-head play are already confirmed product facts.
  relevant_topics: two-player, social play, swivel base, bar placement

- id: industrial-not-consumer
  type: craftsmanship
  claim: "Inside, the ECHO is closer to a piece of purpose-built commercial equipment than to a home computer or a tablet in a case. What the owner sees is a simple touchscreen appliance; behind it sit a dedicated frame, power system, audio, controllers and cooling designed for years of continuous use. All 149 games live on 4 GB of onboard storage, and access to the system settings is protected by a physical key."
  source: business intake questionnaire, 2026-08-19
  date_added: 2026-08-19
  consent_status: not_required
  verified_by: JVL business intake questionnaire, 2026-08-19
  usage_notes: The 4 GB storage figure is new to the knowledge base and is not yet in claims_constraints.md — do not state it as a spec until it is added there.
  relevant_topics: build quality, durability, what is inside, commercial-grade

- id: bartop-heritage-continuity
  type: quote
  claim: "What carries over from the JVL bartops of thirty years ago is the format itself: a compact machine, a touchscreen as the main interface, a large library in one unit, and people playing around a single screen. The display, the electronics and the design have all changed; the shape of the product has not."
  source: business intake questionnaire, 2026-08-19
  date_added: 2026-08-19
  consent_status: not_required
  verified_by: JVL business intake questionnaire, 2026-08-19
  usage_notes: Heritage framing only. The RePlay Magazine award wording in claims_constraints.md still applies and must not be attached to the ECHO directly.
  relevant_topics: heritage, JVL history, bartop arcade, brand trust

---

## SECTION 3 — Craftsmanship and process details

JVL's manufacturing process and quality control. Internal data — no external
consent needed, and confirmed by the business through the intake questionnaire.

**Status: USABLE — process confirmed by the business.**

- id: full-cycle-seven-working-days
  type: craftsmanship
  claim: "Physical assembly of a unit takes hours once every component has passed incoming inspection. The full cycle from assembly to a unit ready to ship can run up to seven working days — configuration, manual and automated testing, burn-in, a second QC pass, and packing."
  source: business intake questionnaire, 2026-08-19
  date_added: 2026-08-19
  consent_status: not_required
  verified_by: JVL business intake questionnaire, 2026-08-19
  usage_notes: The strongest process anchor available. Always give both halves — hours of assembly against up to seven days of the full cycle — because the gap between them is the point.
  relevant_topics: build quality, individually tested, QC, lead time, premium manufacturing

- id: pre-shipment-test-coverage
  type: craftsmanship
  claim: "Every ECHO is powered on and tested individually before it leaves the factory. The pass covers at minimum system boot, the touchscreen across its whole surface, image, sound, game loading, controls, system settings, power, the swivel mechanism and the condition of the cabinet."
  source: business intake questionnaire, 2026-08-19
  date_added: 2026-08-19
  consent_status: not_required
  verified_by: JVL business intake questionnaire, 2026-08-19
  usage_notes: "Individually tested before shipping" is already a confirmed claim; this entry is what makes it concrete. Keep the "at minimum" hedge — the list was given as a floor, not an exhaustive protocol.
  relevant_topics: individually tested, QC, reliability, what you get

- id: materials-publicly-nameable
  type: craftsmanship
  claim: "Reinforced plastic case and a precision-built frame, a 22-inch LCD, 4 GB of onboard storage, and a 25-watt four-speaker audio system with a subwoofer."
  source: business intake questionnaire, 2026-08-19
  date_added: 2026-08-19
  consent_status: not_required
  verified_by: JVL business intake questionnaire, 2026-08-19
  usage_notes: Component suppliers are not public — never name them. Do not give a pixel resolution for the display; the panel is described by size and type only.
  relevant_topics: materials, build quality, specs, audio

**Resolved 2026-08-19 — the display is not described by resolution.** An earlier
intake answer gave a pixel figure that did not match the 16:9 panel described in
`product_echo_home.md`. The business has settled it by dropping the number: the
screen is a 22-inch 16:9 HD LCD and nothing finer than that is claimed.

---

## SECTION 4 — Operational data points

Real numbers about JVL operations. `consent_status: not_required` applies here;
the figures were confirmed by the business through the intake questionnaire.

**Status: USABLE — figures confirmed by the business.**

- id: units-shipped-1000-plus
  type: data_point
  claim: "More than 1,000 ECHO units shipped."
  source: business intake questionnaire, 2026-08-19
  date_added: 2026-08-19
  consent_status: not_required
  verified_by: JVL business intake questionnaire, 2026-08-19
  usage_notes: Use as "more than 1,000" — the figure is a floor, not a count. No per-year breakdown was given, so do not imply an annual rate.
  relevant_topics: track record, trust, scale, proof

- id: markets-us-and-canada
  type: data_point
  claim: "The ECHO is sold in the United States and Canada. The machine itself runs in seven languages."
  source: business intake questionnaire, 2026-08-19
  date_added: 2026-08-19
  consent_status: not_required
  verified_by: JVL business intake questionnaire, 2026-08-19
  usage_notes: Do not imply availability outside the US and Canada. Buyers elsewhere should be pointed at JVL directly. Seven languages is already a confirmed product fact.
  relevant_topics: availability, shipping, international, languages

- id: eleventh-generation-since-1995
  type: data_point
  claim: "JVL has been building bartop machines since 1995, and the ECHO is the eleventh generation of that line — the ECHO Evolution timeline marks 1995, 1997, 1999, 2001, 2003, 2004, 2005, 2006, 2008, 2010 and the present."
  source: business intake questionnaire, 2026-08-19
  date_added: 2026-08-19
  consent_status: not_required
  verified_by: JVL business intake questionnaire, 2026-08-19
  usage_notes: This is what makes "30+ years of bartop expertise" checkable rather than a slogan. The eleven dates are the strongest form; use them when the article has room.
  relevant_topics: heritage, JVL history, 30 years, trust, generations

- id: commercial-repeat-buyers
  type: data_point
  claim: "Commercial buyers commonly take more than one unit for different venues, and come back for repeat orders."
  source: business intake questionnaire, 2026-08-19
  date_added: 2026-08-19
  consent_status: not_required
  verified_by: JVL business intake questionnaire, 2026-08-19
  usage_notes: Qualitative only — no share, count or rate was given. Never turn this into a percentage or a "most operators" claim.
  relevant_topics: commercial, operators, repeat purchase, multi-unit

- id: replay-awards-and-mentions
  type: data_point
  claim: "JVL bartop machines have received multiple RePlay Magazine awards and mentions over the line's history."
  source: business intake questionnaire, 2026-08-19; count and years confirmed as unavailable
  date_added: 2026-08-19
  consent_status: not_required
  verified_by: JVL business intake questionnaire, 2026-08-19
  usage_notes: "Multiple awards and mentions" is the ceiling — the business confirmed no exact count or years exist to cite, so never give a number, a year, or a specific title beyond the approved framing in claims_constraints.md. The record belongs to the JVL bartop line, not to the ECHO. Logo use still needs separate approval.
  relevant_topics: heritage, awards, JVL history, trust, industry recognition

---

## SECTION 5 — Review aggregates

Aggregated signals from real public reviews. Individual review text is NOT
pasted here — only counts, averages and recurring themes.

**Status: EMPTY — and deliberately so.**

The intake reported that a total review count across platforms cannot be
compiled and that no average rating is available. What it did offer were themes
drawn from the four reviews JVL displays on its own site, with the honest note
that this "cannot yet be called an aggregate". It cannot: four testimonials
selected for a product page are marketing copy, not a sample, and treating them
as evidence of what customers generally say is exactly the failure this file
exists to prevent.

The list of common objections in the same answer was explicitly framed as the
*most likely* complaints for a product of this kind — an inference, not an
observation. Guessed objections are not review data, and an article that
answered them as if they were real would be inventing customer sentiment.

Nothing is entered until there is a real review audit. What would make this
section usable:
- review counts and average rating per platform, from the platforms themselves
- recurring positive themes across that whole set, not a curated four
- recurring objections **actually observed** in reviews and support tickets

Support tickets are the fastest honest route to the objections list — they are
first-party, they already exist, and nobody has to guess.

---

## Maintenance log

| Date       | Section | Change                | By |
|------------|---------|-----------------------|----|
| 2026-05-14 | all     | Skeleton created      | content-engine |
| 2026-08-19 | 2, 3, 4 | 13 entries added from the business intake questionnaire; all `verified_by: null` until a name is on record | content-engine |
| 2026-08-19 | 2, 3, 4 | All entries marked verified by the business intake; Writer may now use them | content-engine |
| 2026-08-19 | 5       | Left empty on purpose — the themes offered came from four reviews on JVL's own site, and the objections were inferred rather than observed | content-engine |
