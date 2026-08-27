# Why the Writer's rules are what they are

**No agent reads this file.** It exists so the rules in `writer_agent.md` can be
short without becoming arbitrary — every constraint there was bought with a
defect, and a rule whose reason has been forgotten is a rule the next refactor
deletes. That has already happened twice: the section-length ceiling was dropped
while fixing length, and the Flesch target in the prompt drifted three months
behind the code.

Keep this in step with the prompt. When you change a rule, change the entry.

---

## Section length: 250–350 words of prose

The floor was there from the start. The ceiling was dropped in #73 while that PR
was fixing length, leaving "at least 250 words" with nothing bounding it above.

Three drafts then kept to their outlines — 6, 9 and 8 sections against outlines
offering 7, 9 and 8 — and still came in at 4,341, 3,797 and 4,177 words against
a 2,787-word ceiling. They wrote sections of 723, 421 and 522 words. A floor
alone only ever pushes one way.

Restored in #80.

## The section count comes from the LENGTH TARGET block

It used to say "divide the word target by roughly 350". A model that cannot
count its own words will not hold that quotient either. The same move that fixed
the word target fixed this: compute the number and hand it over.

The three claimants — outline, requirements, the Writer's own judgement — spend
from one allowance. Nothing said so before, and a section the requirements asked
for read as an extra rather than one of the ones already allowed.

## Length follows the ranking articles

The prompt used to carry "an article runs about 3000 words across 10–14 H2
sections", written before the SERP agent could measure anything. A run whose
competitors measured 1,835 words produced 5,340: a hard-coded number beats a
field in a JSON payload every time.

Going longer stays allowed — a thin top five is a real opportunity — but
`length_justification` has to name the gap the extra words close. The Writer is
not asked to notice its own overshoot, because it never learns its word count;
the pipeline measures the finished draft and asks for a revision if it landed
long with the field empty.

## Headings capped by density

A measured draft ran 25 headings, one every 147 words. Every heading is a full
stop the argument cannot cross. The cap scales with the target rather than
assuming 3,000 words, which is what it did before #73.

## No sentence past 35 words, fewer than one in ten past 30

Drafts break this invisibly: one measured at 18.5 words on average with a
63-word sentence inside it and 16% of sentences past thirty. Averages hide their
own tails, which is why the checker measures the tail separately and why the
prompt asks for a count rather than a feel.

## Plain words, and the two dials

Flesch is one number over two independent things — sentence length and word
difficulty — so a draft can buy length with vocabulary. It did: lengthening
sentences from 14.6 to 20.1 words took syllables per word from 1.39 to 1.53 and
difficult words from 9.6% to 13.3%, because nothing watched the second
dimension. Hence two separate ceilings, and hence the instruction not to shorten
sentences when the vocabulary is flagged.

Plainness was one bullet and one example until #81. Drafts kept failing the
vocabulary ceilings: 1.487/13%, 1.514/14% twice, against 1.45/11%.

The three worked pairs in the prompt are quoted verbatim from real drafts so
they stay greppable against `outputs/` rather than drifting into invention.

## Never let prose run more than 350 words unbroken

The failure has shipped in both directions. One draft came back a third bullets,
sentences averaging thirteen words — formally prose, rhythmically a checklist.
The next over-corrected into unbroken columns with a comparison buried in the
middle of one, which is worse: the reader who came to compare now has to build
the table themselves.

Headings do not break a run. A section running a thousand words of paragraphs
under one heading is still a wall, and the heading only tells the reader the
wall has a name.

The prose floor and this ceiling meet head-on, and the ceiling wins. Two
sections at the floor, back to back with nothing between them, are a 500-word
wall with a subtitle in the middle.

## Every claim has one home

The anti-repetition rule listed four product claims and nothing about the
article's own arguments. So a draft argued twice that published arcade figures
were measured in a different kind of room — once in its opening section, once
five sections later, closing both with the same flourish ("the step most payback
guides skip entirely", then "the step every ranking guide skips"). Its two
headings ended with the same nine words. Six of ten sections explained the
machine price; five explained the base case.

Duplicates form at a seam: one section from the outline, one from the
requirements, both saying one thing.

## Genre rules live in profiles, not here

"You are writing for a bar owner, not a committee" was being read by every
article, including guides for people buying a machine for a basement. Anything
true of one article belongs in `prompts/profiles/`, and a guard test keeps that
vocabulary out of the shared prompt — it caught "coin drop" in the first draft
of the plain-language rule.
