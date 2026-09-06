# pipeline

Steps 6 + 7. The request handler, run per question.

- **Step 6** drives Claude: write a plan first, stop and ask on an ambiguous
  term, then force a tool call.
- **Step 7** formats the final answer and attaches a citation trace (doc id,
  page, line item) to every number.

Uses `retrieval/` to find chunks and `tools/` to compute numbers.

See `docs/research/step-6-planning-and-escalation.md` and
`docs/research/step-7-provenance-and-citations.md`.
