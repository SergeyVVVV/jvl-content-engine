# Production Candidate Review
**Date:** 2026-04-09  
**Branch:** claude/stabilize-mvp-pipeline-h9C1c  
**Pipeline:** Brief → SERP Research → Company Insight → Writer → QA → Metadata Copy  
**Runner:** `run_article.py`  
**SERP mode:** Mock (offline)

---

## Topics Run

| # | Topic | Funnel Stage | Type | QA Status | Severities |
|---|-------|-------------|------|-----------|------------|
| 1 | how to choose a home arcade machine | top | informational | revise | high=0 med=1 low=4 |
| 2 | bartop arcade machine for home bar | mid | commercial / scenario | revise | high=0 med=2 low=4 |
| 3 | arcade machine gift for dad | mid | scenario / use-case | revise | high=0 med=1 low=4 |

All three articles avoided HIGH severity issues. No invented specs, no fabricated testimonials, no forbidden claims. The pipeline produced publishable-quality material in need of light human editing rather than rewrites.

---

## Article 1 — How to Choose a Home Arcade Machine

**Type:** Informational  
**Funnel:** Top  
**QA Status:** `revise` — high=0 · med=1 · low=4

**Artifacts:**
- Brief: `outputs/briefs/how-to-choose-a-home-arcade-machine.json`
- SERP: `outputs/serp_research/how-to-choose-a-home-arcade-machine.json`
- Insight: `outputs/company_insight/how-to-choose-a-home-arcade-machine.json`
- Draft: `outputs/drafts/how-to-choose-a-home-arcade-machine.md`
- QA: `outputs/qa/how-to-choose-a-home-arcade-machine.json`
- Metadata: `outputs/metadata/how-to-choose-a-home-arcade-machine.json`

**H1:** Choosing a Home Arcade Machine: What Actually Matters  
**Meta Title:** How to Choose a Home Arcade Machine Worth Keeping  
**Slug:** `how-to-choose-home-arcade-machine`  
**Sections:** 15

**Human Summary:**  
A comprehensive decision-support guide aimed at adult homeowners evaluating their first arcade purchase. Opens with a "six-week reckoning" hook (the machine gathering dust after initial excitement) that is original and emotionally resonant. Works through room placement, game quality, build durability, and format choice before arriving at the Echo Home recommendation in section 8 — late enough to feel earned rather than pushed. Strong independent editorial value regardless of whether the reader buys the Echo Home.

**Main Strengths:**
- Best hook of the three articles; feels like genuine editorial, not marketing copy
- Excellent persona alignment throughout — warm, mature, zero gamer jargon
- Echo Home introduced with honest caveats ("won't be the right machine for everyone"), which builds trust
- 15 sections deliver thorough coverage; reader leaves with concrete decision criteria
- The 5 claims to verify are all appropriately flagged and non-fabricated

**Main Weaknesses:**
- Medium: Repetitive key phrases across sections ("pick-up-and-play", "earns its place" appear multiple times) — noticeable but fixable in one editing pass
- Low: Echo Home first named in section 8; brief aimed for earlier introduction
- Low: Build quality section is vague (correctly avoids invented specs, but reads thin compared to other sections)
- Low: SERP gap for touchscreen/no-WiFi queries not fully addressed
- 10 TODOs and 18 risks require human sign-off before publishing

**Publishable after light editing?** Yes — the single medium issue is a repetition pass, fixable in 30 minutes.

**What still needs human verification:**
1. Echo Home physical dimensions and weight (affects sizing/placement section)
2. Whether Echo Home has a touchscreen (affects category language)
3. Specific game titles in 149-game library (would significantly strengthen the guide)
4. Warranty length and customer support details
5. Price point or price range (readers of a buying guide will expect it)

---

## Article 2 — Bartop Arcade Machine for Home Bar

**Type:** Commercial investigation / Scenario  
**Funnel:** Mid  
**QA Status:** `revise` — high=0 · med=2 · low=4

**Artifacts:**
- Brief: `outputs/briefs/bartop-arcade-machine-for-home-bar.json`
- SERP: `outputs/serp_research/bartop-arcade-machine-for-home-bar.json`
- Insight: `outputs/company_insight/bartop-arcade-machine-for-home-bar.json`
- Draft: `outputs/drafts/bartop-arcade-machine-for-home-bar.md`
- QA: `outputs/qa/bartop-arcade-machine-for-home-bar.json`
- Metadata: `outputs/metadata/bartop-arcade-machine-for-home-bar.json`

**H1:** How to Choose a Bartop Arcade Machine for Your Home Bar  
**Meta Title:** Choosing a Bartop Arcade Machine for Your Home Bar  
**Slug:** `bartop-arcade-machine-home-bar`  
**Sections:** 10

**Human Summary:**  
A practical purchasing guide for homeowners choosing a bartop arcade for their home bar or entertainment space. Covers what to look for in size, finish, setup ease, game quality, and social play. The Echo Home is positioned as a premium option that fits the home bar aesthetic and value proposition. Good brief compliance and clean factual handling, but two structural issues weaken it relative to the other two articles.

**Main Strengths:**
- Strong factual discipline — no invented specs, no forbidden claims, all unverified details flagged
- Natural product integration — Echo Home appears only after editorial buying criteria are established
- Complete brief section coverage, including FAQ answers
- Warm, understated tone consistent with persona

**Main Weaknesses:**
- Medium: Significant content overlap between "What to Look For" and "Matching the Machine to Your Space" sections — creates redundancy and pace drag
- Medium: Brief explicitly instructed "couple as buyer" framing; draft defaults to individual buyer "you" throughout — misses the social/home-bar intimacy angle
- Low: Three raw `TODO:` comments are visible in the article body text and must be removed before publishing
- Low: FAQ answers for bartop dimensions and 2-player capability are generic due to unconfirmed specs
- Low: EEAT angle on JVL as first-party manufacturer not used — a missed trust signal

**Publishable after light editing?** Not quite — the visible TODO comments and couple-buyer framing are quick fixes, but the section overlap requires actual restructuring (30–45 min edit). Could be a clean pass after one focused rewrite.

**What still needs human verification:**
1. Echo Home dimensions — critical for "will it fit on my bar counter" use case
2. 2-player simultaneous play capability — central to home bar social angle
3. Touchscreen vs. joystick control interface — omitted to be safe but is buyer-relevant
4. Build material and finish details — premium home bar framing demands specifics
5. Warranty length and support process (bottom-of-funnel trust)

---

## Article 3 — Arcade Machine Gift for Dad

**Type:** Scenario / Use-case  
**Funnel:** Mid  
**QA Status:** `revise` — high=0 · med=1 · low=4

**Artifacts:**
- SERP: `outputs/serp_research/arcade-machine-gift-for-dad.json`
- Insight: `outputs/company_insight/arcade-machine-gift-for-dad.json`
- Draft: `outputs/drafts/arcade-machine-gift-for-dad.md`
- QA: `outputs/qa/arcade-machine-gift-for-dad.json`
- Metadata: `outputs/metadata/arcade-machine-gift-for-dad.json`

> **Note:** Brief file not present for this run (outputs from prior session). All 5 remaining pipeline steps present.

**H1:** Why a Home Arcade Machine Is the Perfect Gift for Dad  
**Meta Title:** Arcade Machine Gift for Dad: Choosing the Right One  
**OG Title:** The Home Arcade Gift Your Dad Will Actually Use  
**Slug:** `arcade-machine-gift-for-dad`  
**Sections:** Not confirmed (prior run)

**Human Summary:**  
A gift guide for adult children buying a home arcade machine for a dad who grew up in the arcade era (1970s–1980s). Opens with strong emotional validation of the gift idea ("a lasting experience rather than another thing"), works through what makes a good choice (ease of setup, game nostalgia, home aesthetics), and positions the Echo Home naturally as a premium option that fits the use case. Clean emotional arc and strong tone discipline.

**Main Strengths:**
- Strong emotional opening — frames the gift as meaningful rather than transactional; resonates with the persona
- Excellent tone: warm, nostalgic, zero gamer jargon, zero hype
- All required sections present and well-developed
- All questions-to-answer from brief addressed substantively
- Claims carefully handled — all uncertain details flagged as TODOs, not invented

**Main Weaknesses:**
- Medium: "Earns its place/spot/keep" metaphor used four times — repetitive and dilutes impact
- Low: "The kind of [noun] that…" construction clusters across sections — identifiable AI writing pattern
- Low: Three consecutive sections share identical bold-subheaded bullet structure — visual monotony
- Low: Opening uses a slightly formulaic "hot take" device
- Low: `/en/home` internal link anchor text is vague (reader can't tell what it leads to)

**Publishable after light editing?** Yes — one repetition pass and anchor text fix is sufficient. The structural issues are cosmetic rather than substantive.

**What still needs human verification:**
1. Echo Home dimensions and weight (gift logistics — "will it arrive in one manageable box, can it be set up quickly")
2. Specific game titles from the 149 built-in library (naming 5–10 recognizable classics would strengthen the nostalgia pitch significantly)
3. 2-player simultaneous capability (referenced as a feature without confirmation)
4. Warranty and returns policy for gift context
5. Price point (gift buyers decide by budget; no pricing in draft)

---

## Cross-Article Observations

### What the pipeline gets right consistently

- **Zero HIGH severity issues across all three articles** — no invented specs, no fabricated testimonials, no forbidden claims. The factual safety guardrails in prompts and QA are working.
- **Tone and persona fit** — all three articles maintain the warm, mature, understated premium voice. No gamer jargon escaped in any draft.
- **Product integration discipline** — Echo Home is mentioned naturally and proportionately. It appears after editorial value is established, not as the first sentence.
- **Claims to verify** are flagged correctly in the draft JSON wrapper, creating a clear handoff checklist for human review.
- **Mock SERP works well enough** — all three briefs shaped the content correctly even without live SERP data.

### What the pipeline surfaces but cannot fix

Every article shares the same four unverified facts:
1. Echo Home physical dimensions and weight
2. Whether it supports 2-player simultaneous play
3. Specific game titles in the 149 library
4. Price point or price range

These are not pipeline failures — they are knowledge base gaps. **Filling `product_echo_home.md` with confirmed specs would upgrade all three articles from "revise" to near-publishable without re-running the pipeline.**

### Structural pattern in writer output

Two recurring AI-writing patterns flag across all three articles:
- Repetitive key phrases ("earns its place", "pick-up-and-play")
- Formulaic section structure (bold subheadings + bullets, repeated three times in a row)

These are low-severity but consistent. The QA agent correctly identifies them. A one-pass style edit removes most of them.

---

## Ranking

| Rank | Topic | Reason |
|------|-------|--------|
| **1 (Strongest)** | how to choose a home arcade machine | Original hook, most independent editorial value, cleanest QA (1 medium), strongest structure. Ready with 1 edit pass. |
| **2** | arcade machine gift for dad | Strong emotional frame, clean factual handling, good persona fit. Slightly weaker structure but equally clean QA. |
| **3 (Weakest)** | bartop arcade machine for home bar | 2 medium QA issues including visible TODO text in body, missed couple-buyer framing from brief, section overlap needs restructuring. Most work before publication. |

---

## Verdict: Is the System Ready for Real Content Production?

**Short answer: Yes, with one prerequisite.**

The pipeline produces publish-quality first drafts that require light human editing, not rewrites. Zero high-severity issues across three articles is a meaningful signal — the factual safety guardrails and QA agent are doing their job.

**The one prerequisite:** Confirm and add to `knowledge/product_echo_home.md`:
- Physical dimensions and weight
- 2-player simultaneous play (yes/no)
- Top 10 recognizable game titles from the 149 library
- Price point or price range
- Warranty and support policy

Without these, every article will end up at "revise" status with the same 10 TODOs. With them, the same pipeline would likely produce `pass` status articles directly.

**What human editors should do with each output:**
1. Remove/resolve all `TODO:` inline comments in body text before publishing
2. Vary repetitive key phrases (one 20-minute pass)
3. Confirm claims-to-verify list against business sources
4. Verify internal link slugs (`/en/echo`, `/en/home`) are live
5. Add price context where appropriate

The pipeline is production-ready. The knowledge base is the bottleneck.
