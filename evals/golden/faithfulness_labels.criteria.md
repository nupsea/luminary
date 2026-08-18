# Labelling criteria — faithfulness and citation support

The set these criteria produce exists to validate two judges that currently score
their own notion of correctness: the citation judge, and the NLI faithfulness
score whose floor is `mean - 3sd` because nothing establishes where a real bar
goes. A label set without written criteria cannot be audited or extended by
anyone else, and a second labeller would produce a different set.

## What is being labelled

Each row is one `/qa` answer, together with **the context the product actually
retrieved for it** and the citations it emitted. A label is a statement about
that text, never about the document or about the world.

## `label_grounded` — is the answer supported by the context it was given?

**true** when every factual claim the answer makes is stated in the retrieved
context, or follows directly from it.

**false** when the answer asserts anything the context does not contain. This
includes claims that are *correct about the source work* but absent from the
retrieved chunks: an answer that is right because the model remembers the book is
not grounded, and it is the failure this metric exists to catch.

Edge cases, decided in advance so they are not decided case by case:

- An answer that declines — "the context does not say" — is **grounded**. It
  asserts nothing false. Whether it *should* have found an answer is a retrieval
  question, and `hit_rate` measures that.
- Hedged phrasing ("this suggests", "likely") is judged on the claim underneath.
  A hedge does not make an unsupported claim supported.
- Fluent connective prose that adds no claim is ignored.
- Content the answer **explicitly marks** as outside the documents -- this build
  emits "This is not covered in your documents, but:" -- is excluded from the
  judgement. The answer is not passing it off as grounded, and penalising a
  declared departure would train the product to stop declaring them. Everything
  before the marker is judged normally.
- One unsupported claim makes the answer **not grounded**, however much of the
  rest is fine. A learner cannot tell which sentence was the invented one.

## `label_citation_supported` — does this citation support the answer?

**true** when the excerpt supports at least one claim the answer makes.

This deliberately matches the judge's own stated task rather than a stricter one,
so the comparison measures the judge's accuracy and not a disagreement about the
question. An earlier prompt demanded a citation "fully support the claim" against
the whole answer, which no single excerpt can do; it scored `no` on a verbatim
correct citation.

**false** when the excerpt is real text that supports nothing the answer said, or
when it is not in the retrieved context at all.

## Who labelled, and what that is worth

One labeller (Claude, the assistant in the session that built the collector),
reading each answer against its own retrieved context. That is a stronger
labeller than the 4B judges under test and independent of them, which is what
makes the validation meaningful.

It is still **one labeller with no inter-annotator agreement**. The set supports
statements like "the judge passes citations a careful reader rejects" and
"grounded and ungrounded answers overlap on this metric". It does not support a
claim that a particular threshold is correct in general, and a second labeller is
the obvious next measurement.
