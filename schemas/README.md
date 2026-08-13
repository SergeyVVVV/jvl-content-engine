# Schemas

Every file here is loaded and enforced at runtime. If you add one, wire it into
the agent that produces it — an unread schema drifts from the code within weeks
and then actively misleads whoever reads it next.

| file | loaded by |
| --- | --- |
| `brief_schema.json` | `src/agents.py` (Brief Agent) |
| `serp_research_schema.json` | `src/serp_research_agent.py` |
| `company_insight_schema.json` | `src/company_insight_agent.py` |
| `seo_schema.json` | `src/seo_structure_agent.py` |
| `article_draft_schema.json` | `src/writer_agent.py` |
| `faq_schema.json` | `src/faq_agent.py` |
| `qa_report_schema.json` | `src/qa_agent.py` |
| `visual_schema.json` | `src/visual_agent.py` prompt |

## Not here: the Metadata Copy Agent

It validates against `EXPECTED_KEYS` in `src/metadata_copy_agent.py`. Note that
it emits `meta_title`, not `title`.

## Not here: the publish contract

What jvl.ca accepts at `POST /api/content/draft` is **not** described by any
file in this directory. It is defined by `validateDraftPayload` in the site
repo (`src/lib/content-publish.ts`) and mirrored in `src/studio_export.py`
(`to_studio_payload` builds it, `validate_payload` checks it), which is covered
by `tests/test_studio_export.py`.

There used to be `metadata_schema.json` and `article_schema.json` here. They
were written on day one, never loaded by anything, and never updated as the
pipeline grew — but they looked authoritative, so the site's endpoint was built
against them. That mismatch (`title` vs `meta_title`, and a `sections[]` array
the engine has never produced) is why the first real POST would have failed.
They were deleted rather than fixed: a corrected file nothing reads would drift
again.
