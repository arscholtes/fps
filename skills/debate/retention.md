# Transcript store and expiry

## Where

The **global** database, alongside lessons — not a per-repo tenant.

A debate about jobhunt's matcher is still thinking, and thinking outlives the
repository it happened to be about. Sharding debates per repo would fragment the
one thing that makes an archive worth keeping: being able to search all of it.
Same reasoning that kept the learning queue global when notices and open loops
were sharded.

## Schema

```
debates
  id            integer primary key
  subject       text      what was debated, one line
  kind          text      proposal | design | code | decision | disagreement
  seats         text      json: which seats sat, and why any were added
  transcript    text      the full argument, rounds and all
  concessions   text      json: who conceded what, and to whom
  outcome       text      what was decided
  unresolved    text      what stayed in tension — a legitimate, valuable outcome
  created_at    text
  touched_at    text      the clock that matters
```

## The expiry rule

**Ninety days from `touched_at`, not from `created_at`.**

Reading it, citing it, or editing it sets `touched_at` to now and restarts the
clock. A debate that stays useful stays. One nobody returns to expires.

**Touch is any access through the tool** — showing it, searching and opening it,
quoting it into another debate. Not a listing: appearing in a list is not use, and
counting it would mean nothing ever expires, which defeats the design.

**No warning before expiry, and no nag.** The touch mechanism *is* the warning: if
it mattered, it would have been touched. A "3 debates expire this week" line is a
guilt mechanic in a costume, and the standing rule against those holds here.
Log the deletion; do not chase it.

## Sweeping

Ride the existing daily job rather than adding a schedule. Lazy deletion on read
is wrong here: a transcript nobody reads is exactly the one that should expire,
and lazy deletion would keep it forever precisely because it is never read.

## What this buys

Debates accumulate into a record of how decisions were actually reached — not the
conclusion, which the code already shows, but the argument, the concession, and
what stayed unresolved. That is the part nobody writes down and everybody wishes
they had six months later.

The 90-day sweep keeps that from silting up with debates that turned out not to
matter, without requiring anyone to curate.
