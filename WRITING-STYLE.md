# Writing Style

A running record of how I want my writing to sound, built from
actual edits I've made to AI-drafted copy. Every rule below comes from a
real correction, with the before and after kept so the reasoning is clear.

**If you are Claude and you are about to write or edit audience-facing
copy in this repo, read this file first.**

This file is mirrored from the `portfolio` repo, which holds the canonical
copy. If you change it here, mirror the change there and vice versa.

## Scope in this repo

Not everything here is audience-facing, and applying the plain-English
rules to internal engineering docs would make them worse.

| Applies fully | Applies partly | Does not apply |
|---|---|---|
| Anything published for readers: the root README intro, public write-ups, and any text that becomes a portfolio article | `tournament-analyses/`, the working notes behind articles. Keep the precise terminology and the traceable numbers. Rules 1 and 5 still apply. | `docs/` architecture, technical due diligence, runbooks, code comments, commit messages |

In `docs/` and in code, precise technical vocabulary is correct and
required. Write calibration, isotonic regression, and confidence
intervals when that is what you mean. Rule 6 exists to protect readers
who are not engineers, not to make engineering docs vague.

---

## The short version

Write like a competent college grad explaining their own work to a smart
person who is not in the field. Direct, specific, informative. No
performance.

Keep the analytical detail and structure. That part is not the problem.
The problem is ornamental prose layered on top of it. When in doubt, cut
the sentence that is doing rhetoric and keep the sentence that is doing
information.

---

## Rules

### 1. No em-dashes or en-dashes

Use a comma, a colon, or a new sentence. This includes ranges: write
"Aug 2024 - Present" and "10-15 stakeholders" with plain hyphens.

Check before shipping: `grep -rn '—\|–' src/`

### 2. No "not X, it's Y" constructions

This is the single most recognizable AI tell. If a sentence sets up a
contrast just to knock it down, rewrite it as a plain statement.

> ❌ "The model is not telling me the chalk is overpriced. It is telling me the chalk is underpriced."
> ✅ "That is the unusual part. Models are normally lower than the market on big favorites. Here it is higher."

> ❌ "He is a fit play, not a form play."
> ✅ "The edge here comes from fit rather than form."

The "nothing to do with X and everything to do with Y" template is the
same device wearing a different coat.

> ❌ "a bump that has nothing to do with recent form and everything to do with the shots this course asks for"
> ✅ "a bump for how their games match the shots this course asks for, regardless of how they have been playing lately"

Matched-pair sentences are the third variant. If two consecutive
sentences have identical shape with one word swapped, collapse them.

> ❌ "The market is pricing reputation. The model is pricing a longer stretch of ball striking."
> ✅ "These four are priced on reputation or one strong recent week. The model weighs a longer stretch of ball striking and lands lower on all of them."

One exception: a short factual distinction like "These are
probabilities, not predictions" is fine. It is doing real work, not
rhetoric.

### 3. No metaphors or color

Say the literal thing.

> ❌ "close to a coin flip dressed up as expertise"
> ✅ "mostly luck"

> ❌ "a bargain against a field he towers over"
> ✅ "still good value against this field"

> ❌ "the fit play nobody is talking about"
> ✅ "the course-fit play"

> ❌ "one loud recent week"
> ✅ "one strong recent week"

### 4. No self-referential framing

Do not announce what the writing is about to do, and do not narrate the
significance of a point. Make the point and move on.

> ❌ "That is what a genuine field mismatch looks like."
> ✅ (cut, the following sentence already makes the point)

> ❌ "A note on where I actually look for value. When I test the model..."
> ✅ "When I test the model..."

> ❌ "The biggest disagreement on the board, and it is not close."
> ✅ "The biggest disagreement on the board."

> ❌ "My model has him at 23.7%. That is the unusual part. Models are normally lower..."
> ✅ "My model has him at 23.7%. Models are normally lower..."

> ❌ "Course history is usually a weak signal, so it is worth noting when it is this clear."
> ✅ "Course history is usually a weak signal, but his is strong enough to move the number."

Watch for "it is worth noting," "that is the unusual part," and any
sentence whose only job is to tell the reader that the next fact matters.

### 5. No claiming superiority over others, no self-congratulation

State what I did and what the result was. Let the reader draw the
comparison. Anything that reads as "unlike everyone else, I am honest"
comes out.

> ❌ "That last result is the one most models bury."
> ✅ (cut entirely)

> ❌ "no edge on picking outright winners, and I say so"
> ✅ "no edge on picking outright winners"

Stating an unflattering result plainly is the point. Congratulating
myself for stating it undoes it.

### 6. No modeling jargon in audience-facing copy

Never use calibration, isotonic regression, confidence intervals, model
architecture, or anything about the serving layer (wrapper classes,
caching providers) in writing aimed at recruiters, golf fans, or
bettors. Translate to what it means for a golfer.

> ❌ "The model compresses probabilities."
> ✅ "The model is more conservative than the market on outright winners."

> ❌ "statistically indistinguishable from zero"
> ✅ "close to zero"

Some technical vocabulary is fine and expected: strokes gained, backtest,
field average, implied odds. The test is whether a golf fan who has never
read a stats paper follows it.

### 7. No decorative tech tags

Do not put rows of framework/library pills under project cards
(FastAPI, scikit-learn, React, and so on). The stack belongs in the
resume skills section, not as decoration on written work.

---

## What not to over-correct

These edits are about prose, not substance. Do not respond to this
document by making the writing vaguer or shorter on facts. Specifically,
keep:

- Every number, player name, and comparison. Detail is the value.
- The section structure of reports (Biggest Takeaway, Best Value Plays,
  Players I'm Lower On, an insight section, A Few Caveats, Final
  Thoughts).
- Caveats and honest negative results, stated plainly.
- Leading with the single most interesting finding instead of summarizing
  the field.

---

## Log

Append new entries here as they come up. Date, what I flagged, what the
rule is.

**2026-07-22** Asked to strip AI-sounding jargon and all em-dashes from
the live site. Established rules 1 and 6.

**2026-07-22** Flagged the key-findings note ("most models bury", "coin
flip dressed up as expertise", "I point the useful part of the model at")
and the weekly reports blurb ("what it found that the narrative missed",
"Published before the first tee shot, never edited after"). Asked for
plain, direct, informative, "like a college grad wrote it." Established
rules 3, 4, and 5. Also removed the tech tag pills, rule 7.

**2026-07-22** Second pass on the same report caught three things the
first pass missed: "That is the unusual part" and "it is worth noting
when it is this clear" (rule 4), the "nothing to do with X and
everything to do with Y" template and a matched-pair market/model
sentence (both rule 2), and "in the market I trust most" tacked onto a
player note as emphasis. Also cut "the model's job is" as light
personification. Lesson: these read as harmless individually and only
show up as a pattern on a reread, so always do a second pass.

**2026-07-22** On the first full tournament report: liked the detail and
the structure of the analysis, but said there were too many extra lines
that were too creative and sounded like AI or a genius wrote them.
Established rule 2 and reinforced 3 and 4. This is the clearest statement
of the overall preference: the analysis is right, the ornamentation is
the problem.
