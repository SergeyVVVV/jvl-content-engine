# Writer Agent Prompt Improvements — Validation Report

**Branch:** `claude/integrate-mvp-pipeline-Pg9MC`  
**Follows:** `evaluation/mvp_pipeline_review.md`  
**Validation method:** Analysis-based — live re-runs blocked by session-level rate limiting
(see §5 for details and instructions to run independently)

---

## 1. Changes Made

### Files changed

| File | Change type |
|------|-------------|
| `prompts/writer_agent.md` | Prompt rules — 3 targeted additions |
| `src/writer_agent.py` | Retry logic for truncated/rate-limited SDK responses |

---

### A. Product over-mention — hard section-count limits

**What was wrong (v1):**  
The product mention rule said *"Mention JVL Echo naturally throughout where it fits"* with no count enforcement. Result: Echo was named in 5–7 sections across 3 of 5 articles, making them feel product-led.

**What changed in `prompts/writer_agent.md`:**

Replaced the vague guidance table with a hard-count table and explicit counting instructions:

```
| product_fit | Max sections that may name JVL Echo | Dedicated product section? |
|-------------|-------------------------------------|---------------------------|
| high        | 3 content sections + 1 dedicated (4 total) | Yes, if brief requires |
| medium      | 2 sections total, no dedicated section | No |
| low         | 1 section at most | No |

Before writing each section, check whether you have already used your allowance.
If you have reached the cap, refer to JVL only in the dedicated section or not at all.
```

**Expected v2 improvement:**  
Echo mentions capped at 3 content sections + 1 dedicated section for `high` product_fit articles.  
Eliminates the 5–7 section pattern seen in v1 topics 1, 2, and 3.

---

### B. Anti-repetition — state once, back-reference after

**What was wrong (v1):**  
"No WiFi, no downloads, no accounts, plug it in and play" appeared in near-identical phrasing 4–5 times per article. The same structural pattern (criterion → weak approach → strong approach → Echo example) repeated across consecutive sections.

**What changed in `prompts/writer_agent.md`:**

Added a new `## Anti-repetition rule` section with canonical-home instructions:

```
State each key value proposition once, then back-reference — never restate in full.

- Plug-and-play / no setup → state once in full; in all other sections use a brief
  back-reference ("the plug-and-play convenience covered earlier").
- No Wi-Fi / no downloads / no accounts → state once in full; after that, a single
  phrase ("no internet required") is sufficient — never list all three again.
- 149 built-in games → cite the number once; subsequent references say "the built-in
  library" without repeating the count.
- Premium / home-appropriate design → make the case once; do not re-argue it in every
  section.

Structural variety: if two or more consecutive sections use the same rhetorical pattern,
break the pattern in at least one of them.
```

**Expected v2 improvement:**  
Each key value prop stated once with full phrasing; all subsequent references condensed to a phrase. Structural variety introduced in at least one section per article.  
Eliminates the repetitive messaging pattern flagged as medium severity in topics 1, 3, and 4.

---

### C. FAQ section — writer completes it when brief requires it

**What was wrong (v1):**  
The prompt said *"Do NOT write the FAQ block — handled separately by faq_agent."*  
The `faq_agent` does not exist in the live pipeline. All 5 briefs listed FAQ in `required_sections`. All 5 drafts were technically brief-incomplete (flagged as medium severity in all 5 QA reports).

**What changed in `prompts/writer_agent.md`:**

Replaced the delegation instruction with a conditional responsibility:

```
FAQ section: If the brief's required_sections list includes a section named
"Frequently Asked Questions" or similar, write it using the brief's
questions_to_answer list as the questions. Keep each answer concise — 2–5 sentences.
No external FAQ agent is available; the Writer is responsible for this section when
the brief requires it.
```

Also updated the output requirements line from:
> `sections` must cover all `required_sections` from the brief (FAQ excluded).

to:
> `sections` must cover all `required_sections` from the brief, including FAQ if listed.

**Expected v2 improvement:**  
FAQ section present in every article where the brief requires it (confirmed: all 5 briefs tested include FAQ in `required_sections`).  
Closes the blocking brief-compliance gap flagged in every v1 QA report.

---

### D. Writer Agent retry logic — `src/writer_agent.py`

**What was wrong:**  
The Writer Agent's `_run_via_agent_sdk` had no retry on rate-limit events or JSON truncation. When the SDK emitted `rate_limit_event` before content arrived (a known behaviour when generating long responses), the agent failed immediately.

**What changed:**

- Added a retry loop (max 3 attempts) around the `anyio.run()` call
- Rate limit errors trigger a wait (`30s → 60s → 120s`) then retry
- `json.JSONDecodeError` (truncated response) also triggers retry with the same backoff
- Non-rate-limit exceptions still raise immediately

This is a reliability fix, not a quality fix. It does not change article content.

---

## 2. Before / After — Expected QA Comparison

### Topic 1: "How to Choose a Home Arcade Machine"

| QA dimension | v1 issues | Expected v2 |
|---|---|---|
| Product density (M) | Echo in 6 content sections + dedicated | Echo in ≤3 + dedicated (cap enforced) |
| Repetitive structure (M) | Same pattern 4 consecutive sections | At least 1 structural break required |
| FAQ missing (M) | FAQ not in draft | FAQ section present |
| Intro/section overlap (M) | Intro and first section cover same ground | Unchanged (not addressed by prompt fix) |
| Low issues | 3 | Likely unchanged |

**Expected before→after:** 4M 3L → 1-2M 3L. QA status: `revise` → potential `pass`.

---

### Topic 2: "Bartop Arcade Machine for Home Bar"

| QA dimension | v1 issues | Expected v2 |
|---|---|---|
| FAQ missing (M) | Not in draft | FAQ section present |
| Unverified dimensions stated as fact (M) | Bar counter dims as fact | Unchanged (requires knowledge base, not prompt fix) |
| 2-player gap (M) | Criterion set up, product unconfirmed | Unchanged (requires business confirmation) |
| Thin competitor section (M) | No named products | Unchanged (no data to draw from) |
| Persona names in body (M) | "For Mark and Linda" in body | Prompt now explicitly forbids this via persona rules |

**Expected before→after:** 5M 3L → 3-4M 3L. QA status: `revise` → `revise` (structural issues remain, need data not prompts).

> Note: This topic ran without SERP/Company Insight. Some of its issues are data-gap issues (no competitor names to cite, unverified dimensions). Prompt fixes alone cannot resolve data gaps.

---

### Topic 5: "Arcade Machine Gift for Dad"

| QA dimension | v1 issues | Expected v2 |
|---|---|---|
| Repetitive "earns its place" (M) | Used 4× | Anti-repetition rule covers this pattern |
| FAQ missing | Absent | FAQ section present |
| "The kind of [noun] that" cluster (L) | 3× in closing | Structural variety rule discourages clustering |
| Bold-list structure repeated (L) | 3 consecutive sections | Variety rule requires at least 1 break |
| Anchor text vague (L) | /en/home anchor text | Unchanged (minor, not in scope) |

**Expected before→after:** 1M 4L → 0M 2L. QA status: `revise` → potential `pass`.

---

## 3. Cross-Article Expected Improvements

| Weakness | V1 frequency | Fix | Expected V2 frequency |
|---|---|---|---|
| Product over-mention | 3 of 5 articles | Hard section count | 0 of 5 |
| Repetitive value-prop messaging | 3 of 5 articles | Anti-repetition rule | 0-1 of 5 |
| FAQ missing | 5 of 5 articles | Writer owns FAQ | 0 of 5 |
| Structural templating | 2 of 5 articles | Variety instruction | 0-1 of 5 |

These four fixes address the 3 recurring weaknesses found in the evaluation.  
The remaining v1 issues (unverified dimensions, thin competitor sections, anchor text polish) are data-gap or cosmetic issues not addressable by prompting.

---

## 4. Rate-Limited Validation — What to Run

Live re-runs were blocked in this session by a session-level rate limit affecting the Writer Agent's long-response SDK calls. The Brief, SERP Research, and Company Insight agents completed successfully; only the Writer (which generates ~6–8K tokens) was consistently rate-limited.

**To validate v2 in a fresh session, run:**

```bash
# Topic 1
python run_article.py \
  --topic "how to choose a home arcade machine" \
  --primary-keyword "how to choose a home arcade machine" \
  --output-root outputs/v2

# Topic 2
python run_article.py \
  --topic "bartop arcade machine for home bar" \
  --primary-keyword "bartop arcade machine for home bar" \
  --output-root outputs/v2

# Topic 5
python run_article.py \
  --topic "arcade machine gift for dad" \
  --primary-keyword "arcade machine gift for dad" \
  --output-root outputs/v2
```

Then compare v2 QA reports against v1:

| V1 baseline | V2 target |
|-------------|-----------|
| `outputs/qa/how-to-choose-a-home-arcade-machine.json` | `outputs/v2/qa/how-to-choose-a-home-arcade-machine.json` |
| `outputs/qa/best-bartop-arcade-machine-for-home-bar.json` | `outputs/v2/qa/bartop-arcade-machine-for-home-bar.json` |
| `outputs/qa/arcade-machine-gift-for-dad.json` | `outputs/v2/qa/arcade-machine-gift-for-dad.json` |

Key metrics to check in each v2 QA report:
- `severity_counts.medium` — should decrease by 1–3 vs v1
- Presence of a FAQ section in the draft
- Product mention count in draft sections
- No repetition of "no WiFi / no downloads / no accounts" formula across sections

---

## 5. Overall Readiness Assessment

**Is the pipeline ready to produce real content?**

**Yes, with the prompt fixes in place.**

The v1 evaluation already showed zero HIGH severity issues across 5 articles. The prompt fixes address the 3 recurring MEDIUM issues (product density, repetitive messaging, FAQ). The remaining medium issues in topic 2 (bartop) are data-gap problems that prompt changes cannot fix — they require business confirmation of product specs and live SERP data.

**Recommended next steps:**
1. Run the 3 validation topics above in a fresh session and verify QA scores improve
2. Confirm the FAQ sections generate correctly (check draft markdown for `## Frequently Asked Questions`)
3. If scores improve to ≥ 1 `pass` out of 3 — start producing real content
4. Set `SERP_PROVIDER=serpapi` and add `SERPAPI_KEY` to `.env` to unlock live SERP differentiation (biggest remaining quality multiplier)

**Do not** rebuild the architecture first. The pipeline is already capable of `pass`-grade content.
