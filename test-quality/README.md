# test-quality

Each subfolder is one review snapshot named `<date>_v<n>/`, where `v<n>` is the state of the service under review, not the review's edition (`v2` = REQ-001 phase 1 + REQ-002 technical-assistant profile, 2026-09-09).
A snapshot holds an independent `expert-opinion.md` (design judgement), a test set in two identical renderings (`test-questions.md` for humans, `test-questions.yaml` for the judge agent), and a `results/` folder the judge fills with `<run-date>-<model>.md` plus raw JSON.
Inputs sent to the model are German unless a case is marked `language: en|mixed` as a deliberate robustness probe; deliverables are English.
A later snapshot (`<date>_v3/` …) copies and extends the previous set rather than editing it, so results stay comparable across service states.
Nothing in here is executed by CI; the judge runs the `run` section of the YAML by hand against the live stack.
