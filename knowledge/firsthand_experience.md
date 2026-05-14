# Firsthand experience anchors

## Purpose

Real-world experience signals for E-E-A-T (Experience, Expertise, Authoritativeness, Trust). Writer Agent pulls **one or more** anchors from this file into every article to demonstrate real-world authority. Google's helpful content system and AI search engines (Perplexity, ChatGPT Search, AI Overviews) reward content grounded in verifiable lived experience.

## CRITICAL RULES — read before writing anything

- **Never invent entries.** Every entry must trace to a real source: a real customer with consent, a real JVL employee, a real internal data point.
- **Writer Agent must only use entries where `consent_status: confirmed` AND `verified_by` is filled.** Entries in any other state are off-limits.
- **If no relevant verified anchor exists for the article topic, the Writer must write `TODO: experience anchor needed`** — not fabricate one.
- **No fake testimonials.** Fabricated customer quotes violate Canada Competition Act s. 74.01, US FTC 16 CFR Part 465, and EU UCPD — and they are explicitly forbidden by `claims_constraints.md`.
- **Operational data** about JVL's own production, history, or process does **not** require external consent but **must** be verified by the named JVL team member before use.
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

**Status: EMPTY. Awaiting input from Customer Success team.**

Suggested intake process:
1. Insert opt-in card in every shipped ECHO unit ("Share how ECHO lives in your home — bonus offer for verified reviewers").
2. Customer Success collects responses (3-month follow-up email).
3. Get explicit written consent for use in marketing content.
4. Anonymise per usage_notes.
5. Add entry below with `consent_status: confirmed` once consent is recorded.

<!-- EXAMPLE — DO NOT USE — for format reference only:

- id: example-do-not-use
  type: story
  claim: "EXAMPLE PLACEHOLDER — replace with real customer story before use"
  source: PLACEHOLDER
  date_added: 1970-01-01
  consent_status: pending
  verified_by: null
  usage_notes: This is a format example. Writer Agent must not select entries where consent_status != confirmed.
  relevant_topics: example

-->

---

## SECTION 2 — Founder and team quotes

Real quotes from JVL leadership and engineering team. Gather via a 30-minute interview with CEO, Head of Product, Chief Engineer, or veteran assembly staff. One interview can produce 10-20 usable anchors.

**Status: EMPTY. Awaiting interview with JVL leadership.**

Suggested questions to ask in the interview (one round, ~30 min):
- Why did we make ECHO a 22" touchscreen specifically?
- Why offline-only? Why no Wi-Fi?
- What's the hardest manufacturing step?
- How long does one unit take from raw frame to packaging?
- What's the story behind the swivel base?
- Who tests each unit and what do they check for?
- What's something a customer would never guess about how ECHO is built?
- What's the longest-serving piece of JVL bartop heritage that lives in ECHO?

<!-- EXAMPLE — DO NOT USE:

- id: example-founder-offline-first
  type: founder_quote
  claim: "EXAMPLE PLACEHOLDER — replace with real founder quote from verified interview"
  source: PLACEHOLDER
  date_added: 1970-01-01
  consent_status: pending
  verified_by: null
  usage_notes: This is a format example. Do not use.
  relevant_topics: example

-->

---

## SECTION 3 — Craftsmanship and process details

JVL's manufacturing process, materials, and quality control. Internal data, but still must be verified by Production/Engineering lead before publication. Use to support claims like "individually tested" or "30+ years of bartop expertise."

**Status: EMPTY. Awaiting input from Production team.**

Suggested data points to gather:
- Average labour-hours per unit (assembly + testing combined).
- Number of QC checkpoints between raw frame and packaging.
- Average years of experience of assembly line staff.
- Materials/suppliers used for the cabinet, display, speakers (where shareable).
- Burn-in test duration before shipping.
- Defect rate caught at QC (the figure itself proves the QC is real).

<!-- EXAMPLE — DO NOT USE:

- id: example-qc-checkpoints
  type: craftsmanship
  claim: "EXAMPLE PLACEHOLDER — replace with real QC data confirmed by Production lead"
  source: PLACEHOLDER
  date_added: 1970-01-01
  consent_status: pending
  verified_by: null
  usage_notes: This is a format example. Do not use.
  relevant_topics: example

-->

---

## SECTION 4 — Operational data points

Real numbers about JVL operations that the Writer can cite to demonstrate authority. `consent_status: not_required` is allowed here, but `verified_by` is still mandatory — these must be confirmed by the relevant JVL team member.

**Status: EMPTY. Awaiting input from Operations / Sales.**

Suggested data points to gather:
- Total ECHO units shipped (per year, lifetime).
- Number of countries served.
- Number of language localisations (already known: 7).
- Number of bartop models JVL has produced over the company's history.
- Number of RePlay Magazine awards (heritage claim — see claims_constraints.md for exact wording rules).
- Number of returning customers / multi-unit households.

<!-- EXAMPLE — DO NOT USE:

- id: example-units-shipped-2025
  type: data_point
  claim: "EXAMPLE PLACEHOLDER — replace with real operations figure confirmed by Ops lead"
  source: PLACEHOLDER
  date_added: 1970-01-01
  consent_status: not_required
  verified_by: null
  usage_notes: This is a format example. Do not use.
  relevant_topics: example

-->

---

## SECTION 5 — Review aggregates

Aggregated signals from real public reviews (Amazon, Trustpilot, Google reviews, retailer reviews). Individual review text is NOT pasted here — only aggregate counts, averages, and recurring themes that the Writer can reference without exposing individual reviewer identities.

**Status: EMPTY. Awaiting review audit by Marketing.**

Suggested data points to gather:
- Number of public reviews across all platforms.
- Average rating (per platform and combined).
- Most frequently mentioned positive themes (3-5 phrases).
- Most frequently mentioned objections (so we can address them honestly in content).

<!-- EXAMPLE — DO NOT USE:

- id: example-amazon-aggregate
  type: review_aggregate
  claim: "EXAMPLE PLACEHOLDER — replace with real verified review aggregate"
  source: PLACEHOLDER
  date_added: 1970-01-01
  consent_status: not_required
  verified_by: null
  usage_notes: This is a format example. Do not use.
  relevant_topics: example

-->

---

## Maintenance log

| Date       | Section | Change                | By |
|------------|---------|-----------------------|----|
| 2026-05-14 | all     | Skeleton created      | content-engine |
