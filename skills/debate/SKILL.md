---
name: debate
description: Pressure-test anything through a structured multi-seat argument — a proposal, a design, a piece of code, a plan, a decision already made. One seat holds what was actually asked for and outranks the rest. Use when the user says "debate this", "argue this out", "pressure-test it", or wants a decision stress-tested before committing to it.
---

# Debate

An argument between fixed perspectives, run to find what a single reading misses.

The value is not the verdict. It is the **concessions** — the moments a seat says
"that is a better point than mine" and moves. A debate where nobody changes
position was theatre, and should say so in its own transcript rather than
manufacturing a consensus.

---

## First, work out what is being debated

Do not ask. Name the subject in the transcript's opening line, with its kind:

| kind | what the debate is for |
|---|---|
| a proposal or plan | should this be built, and in this shape |
| an existing design | does it hold, and where does it rot first |
| code | is this right, and is it the right code to have written |
| a decision already taken | does it survive scrutiny, or should it be reopened |
| a disagreement | which position the evidence actually supports |

If the subject is genuinely ambiguous, state the reading you chose and proceed.
A debate about the wrong thing is visible immediately; a debate delayed by a
clarifying question is just delayed.

---

## The seats

**INTENT outranks every other seat.** It holds what was actually asked for — the
request, the ticket, the stated goal — and a debate cannot close without its
sign-off. When another seat proposes something better-but-different, INTENT
decides whether that is an improvement or a different project.

**But outranking is not immunity.** INTENT must concede when it is genuinely
out-argued, and say so plainly: *"that is right, and it changes what I asked
for."* A seat that cannot lose is not a participant, it is a veto, and a debate
with a veto produces agreement rather than truth.

Minimum five seats. Seven below; drop the ones with nothing to say about this
subject rather than having them speak for form's sake.

1. **INTENT** — what was asked for. Outranks the others. Signs off or objects.
2. **CRAFT** — is this good code: readable, testable, honest about failure, the
   thing a maintainer meets at 3am.
3. **ARCHITECTURE** — does it belong here, what does it couple, what does it make
   hard later. Where does the complexity move rather than disappear.
4. **PRIOR ART** — has this already been solved, here or elsewhere. Argues from
   searches actually run, and reports the search as evidence. This seat exists
   because building a sibling of something that already exists is the most
   frequently repeated mistake in this codebase.
5. **RISK** — what breaks, how it fails, what it fails *silently*. What a hostile
   input or a 3am pager does to it.
6. **UX** — the person on the other end, whether that is a user, an operator, or
   the next reader. What does this force someone to know.
7. **COST** — is it worth it. What is not being built instead. The seat allowed
   to say "this is a fine idea and not worth the week."

Add seats when the subject demands one — SECURITY, DATA, ACCESSIBILITY,
PERFORMANCE — and say why it was added.

---

## How it runs

**Round 1 — positions.** Each seat states its read in a few sentences, from
evidence. Assertions without evidence are struck.

**Round 2 — collision.** Seats respond to each other by name. This is where the
work happens. Every seat must do one of three things with each point made against
it: rebut it with evidence, **concede it explicitly**, or narrow its own claim.
Restating the original position is not a move.

**Round 3 — INTENT rules.** INTENT responds to what survived: accepts, accepts
with amendment, or objects with the unmet point named. If INTENT conceded during
round 2, that is recorded as a change to the ask, not hidden.

**Close.** State what was decided, what was conceded and by whom, and what
remains genuinely unresolved. Unresolved is a legitimate outcome. Do not
manufacture consensus — a debate that ends "these two are still in tension and
here is the tradeoff" is more useful than a forced agreement.

---

## Converging

One transcript is a reading, not a result. A debate closes when a **re-run finds
nothing new**, so the default shape is a loop:

1. Debate. Write the transcript.
2. Send the findings to whoever builds — `fps-services notify --for forge` —
   as concrete changes with file and line, and separate "fix this" from "this
   needs a human decision".
3. When the build lands, **re-read the changed artifact** and debate the same
   subject again. Arguing against a remembered version is the failure mode here:
   a seat that has not re-read the code has no evidence and is struck.
4. Repeat until a cycle produces no new finding.

Number the cycles and say which one you are on. Each gets its own transcript —
how the argument moved is the part worth keeping.

**One subject per context, one context per cycle.** Dispatch each debate to its
own agent so it starts clean and reports back only its close. Debates run back to
back in one session bleed: the first one's conclusions are still live while the
second is argued, and the second stops being an independent read. That is the
whole value of a second pass, so protect it structurally rather than by intending
to be impartial. A cycle-2 re-run especially must not inherit cycle 1 — it exists
to check whether the build actually answered the finding, which is a question
cycle 1's reasoning cannot help with.

**Stopping.** Clean means every objection is either fixed in the artifact or
recorded as accepted-unresolved with its reason. Stop and say so when a cycle
only restates the last one; a loop that cannot terminate has stopped learning.
A decision that belongs to a human — a config choice, a product call — is not a
finding and never blocks convergence. Route it and carry on.

**The loop is not free.** Each cycle costs a build and a re-read, so it earns its
place on subjects where being wrong is expensive and cheap to miss. A settled
question does not get three cycles for symmetry.

---

## Rules

- **Argue from evidence.** File and line for code, a quotation for a document, a
  measurement for a claim about behaviour. A seat with no evidence says so.
- **Advocates argue honestly.** Championing a position does not license
  misrepresenting the alternative.
- **Concessions are the product.** Record every one, with who made it and what
  moved them. A transcript with no concessions gets a line at the top saying so.
- **Name the seat.** The reader is watching an argument, not reading a summary.
- **Never invent a fact to win a round.** A seat that cannot support a point
  withdraws it.

---

## Transcript

Every debate and every cycle of one is saved. `retention.md` holds the schema
and the expiry rule — 90 days from last touch, where citing it restarts the clock.

The `debates` table it specifies is **not yet implemented**; until it is, write
the transcript to a file and say where. A store that does not exist cannot be
the reason a transcript went unwritten.

---

## Improving this skill

Every debate is also evidence about the debate *format*. Note friction as it
happens and record it with the transcript: a seat that had nothing to say, a rule
that did not hold, a round that produced no movement, a subject the seats were
wrong for.

Observations accumulate. When enough point the same way, change the skill — and
record the change with the debate that motivated it, so every rule here can be
traced to the argument that earned it. A rule nobody can trace is a rule nobody
will defend.

**The discipline that keeps this from destroying itself: it must not only grow.**

A skill that gains a line per debate reaches five hundred lines and stops
working — instruction-following degrades as context grows, and it degrades
*uniformly*, weakening rules that used to hold. So every revision asks what can be
**cut**: a rule that has never fired, a seat that never earns its place, guidance
that turned out to restate something else. If a change adds more than it removes,
say why in the changelog.

When a rule is being ignored, the fix is almost always to cut the file rather
than to restate the rule louder.

Changes are reported in the daily digest — what changed, which debate prompted
it, and what was removed to pay for it.
