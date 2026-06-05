# Vera Bot — magicpin AI Challenge submission

A merchant-AI assistant that composes WhatsApp messages from the 4-context framework and handles
multi-turn conversations. One composer core backs both the live HTTP server (the judge harness) and
the static `submission.jsonl`.

## Approach

**One composer, two surfaces.** Every message comes from `compose(category, merchant, trigger,
customer?)` ([app/composer/core.py](app/composer/core.py)). The FastAPI server
([app/server.py](app/server.py)) wraps it for `/v1/tick`; `bot.py` wraps it for the static submission.
Build the brain once, ship it twice.

**Grounded composition.** A single system prompt encodes the 5-dimension rubric, the compulsion
levers, the anti-patterns, and a hard no-fabrication rule. Per-`trigger.kind` framing hints (28 of
them) steer voice and structure without scripting the wording. Digest references in the trigger
payload (`top_item_id` / `digest_item_id` / `alert_id`) are resolved to the full item so the model
sees the verifiable headline + source, not just an id.

**Validate then repair.** Output passes a deterministic validator
([app/composer/validate.py](app/composer/validate.py)): no URLs, valid CTA shape, correct `send_as`,
single primary CTA, and a **grounding check** — every percentage and named data-source in the body
must trace back to the contexts. On failure, one repair re-prompt with the specific errors.

**Determinism + cost.** `temperature=0` + fixed seed, plus a content-addressed disk cache, so
re-pushes, replays, and the submission build are reproducible and cheap.

**Multi-turn = deterministic control + LLM flexibility**
([app/composer/reply.py](app/composer/reply.py)). High-risk flows are handled by rules for a reliable
conversation-flow score: opt-out / hostile → `end` + suppress; auto-reply (canned phrasing or
verbatim repeat) → flag once → `wait` 24h → `end`. The nuanced cases — intent transition (switch from
qualifying to executing on an explicit "yes"), off-topic redirects, and engaged questions — go to the
LLM. An anti-repetition guard never resends a body already sent in the thread.

**Restraint.** The bot returns `[]` when nothing's worthwhile: suppression keys are honored across
ticks, far-off festivals (>21 days) are held back, and at most one outbound per merchant per tick.

**Stateful + adaptive.** Contexts are stored versioned and idempotent by `(scope, context_id)`; tick
and reply re-fetch on every call, so mid-test digest/performance/customer injections flow into the
next message automatically.

## Tradeoffs

- **Fast vs quality model.** Live endpoints use `gpt-4o-mini` (latency budget); the static
  `submission.jsonl` uses `gpt-4o` (no time pressure). Swappable from one place ([app/llm.py](app/llm.py)).
- **Grounding is heuristic.** The validator catches ungrounded percentages and invented sources, but
  coincidental digits can pass and cross-item *source mis-attribution* isn't caught. The prompt does
  the heavy lifting; the validator is a backstop.
- **Per-tick compose budget.** Capped at 5 new compositions/tick to stay under 10s; cached
  compositions are effectively free. Excess triggers roll to the next tick.

## What extra context would have helped most

1. **Merchant `offers` with structured price/validity** beyond a title string — would let us anchor
   offer messaging without parsing "@ ₹299" out of text.
2. **A digest-item↔trigger source map** — to cite the *exact* source of a figure and avoid cross-item
   mis-attribution (e.g., a 12% stat is in the Swiggy-sourced item, not the magicpin-data item).
3. **Per-customer `available_slots` / consent scope on every customer** (not just seed customers) —
   richer customer-facing booking flows for the generated dataset.
4. **A "recently sent" log per merchant** — to make restraint and cadence planning sharper across the
   60-minute window.

## Run

```bash
pip install -r requirements.txt
echo "OPENAI_API_KEY=sk-..." > .env
uvicorn app.server:app --host 0.0.0.0 --port 8080   # live server
python -m scripts.build_submission                  # regenerate submission.jsonl
pytest -q                                           # 37 tests
```
