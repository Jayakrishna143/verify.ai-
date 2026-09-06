# tools

Steps 4 + 5. The deterministic math core.

- **Step 4** is `metrics.yaml`: one entry per metric (name, definition, formula,
  US-GAAP input tags).
- **Step 5** is one function per formula, exposed to Claude as a forced tool call.

Keep `metrics.yaml` next to the functions. The formula and the function that
runs it must stay in sync.

See `docs/research/step-4-domain-ontology.md` and
`docs/research/step-5-deterministic-calculation-tools.md`.
