# Vera Bot — Project Plan

**Goal:** Build a merchant-AI assistant ("Vera" rebuild) that beats production Vera on the magicpin
AI Challenge. It composes WhatsApp messages (merchant-facing and customer-on-behalf-of-merchant) from
4 context layers, runs as a stateful HTTP server the judge harness drives, and handles multi-turn
conversations (auto-reply detection, intent handoff, graceful exit).

**Two faces of the same deliverable:**
1. A live HTTP server (5 endpoints) the judge calls during the 60-min test window — this is what we submit (a public URL).
2. Static submission artifacts — `bot.py` (`compose()`), `submission.jsonl` (30 test pairs), `README.md`, optional `conversation_handlers.py`.

Both wrap one shared **composer core**. Build the core once; the server and the static artifacts are thin shells over it.

---

## Status tracker

Legend: ⬜ Not started · 🟡 Running · ✅ Done · ⛔ Blocked

| Phase | Name | Status | Notes |
|---|---|---|---|
| 0 | Setup & dataset | ✅ | Done 2026-06-05. Dataset expanded, loader passes, OpenAI key verified live (gpt-4o-mini). Git initialized. |
| 1 | Composer core (the brain) | ✅ | Done 2026-06-05. 6 case-study tuples eyeballed = strong; 11 tests green; grounding backstop added. |
| 2 | HTTP server & stores | ✅ | Done 2026-06-05. 22 tests green; live curl push→tick→suppress verified. |
| 3 | Multi-turn `/v1/reply` | ✅ | Done 2026-06-05. 32 tests green; 3 replay flows eyeballed = strong. |
| 4 | Adaptive context & restraint | ✅ | Done 2026-06-05. 37 tests green; restraint + version-adaptation + grounding verified. |
| 5 | Submission artifacts | ✅ | Done 2026-06-05. 30-line submission.jsonl clean; 41 tests green. |
| 6 | Self-test & iterate | ✅ | Done 2026-06-05. Judge "all" passes; sample avg 41.1/50 (all dims ≥7.4); tick parallelized. |
| 7 | Deploy | 🟡 | Started 2026-06-05 |

> Update the Status cell as we move (⬜→🟡→✅). Keep a one-line note (e.g. blocker, key decision, date).

**Per-phase loop:** set status 🟡 → build the checklist → run the phase's **Validate** steps → set status ✅ → commit with the phase's **Commit** line.
*(This folder is not yet a git repo — run `git init` before the first commit, or I'll prompt you when we reach Phase 0.)*

---

## Source-of-truth documents (in `../`)
- `challenge-brief.md` — what to build: 4-context framework, `compose()` contract, 5-dimension rubric, compulsion levers, anti-patterns.
- `challenge-testing-brief.md` — how it's tested: 5 HTTP endpoints, judge lifecycle, rate limits, FastAPI skeleton.
- `examples/api-call-examples.md` — exact request/response shapes for every endpoint + failure modes.
- `examples/case-studies.md` — 10 worked "good output" examples with per-dimension scores (our north star, do **not** copy verbatim).
- `dataset/` — seeds + `generate_dataset.py` (expands to 50 merchants / 200 customers / 100 triggers / 30 test pairs).
- `judge_simulator.py` — local LLM judge for self-testing.

---

## Scoring model we are optimizing for
Per message, 5 dimensions × 0–10 = **50**. Plus: adaptation bonus (+5/dim), replay test (top 10, +30), operational penalties (−20).

| Dimension | How we win it |
|---|---|
| **Specificity** | Anchor on a verifiable number/date/headline/source from the contexts. Never "X% off". Cite sources for research/compliance. |
| **Category fit** | Use `category.voice` (tone, allowed vocab, taboos). Dentist = clinical-peer; restaurant = operator-to-operator; etc. Service+price not discount. |
| **Merchant fit** | Use this merchant's real numbers/offers/history. Owner first name. Honor `identity.languages`. |
| **Trigger relevance** | State *why now* explicitly. Tie message to the specific trigger event. |
| **Engagement compulsion** | One binary/low-friction CTA in the last sentence. Use levers: specificity, loss aversion, social proof, effort externalization, curiosity, reciprocity, asking-the-merchant. |

**Hard floors (capped/penalized regardless of quality):** no fabricated data, no URLs in body, no repetition, no multi-CTA, no promo tone in clinical categories, no re-introducing after first message, honor language pref.

---

## Architecture (target)

```
                ┌──────────────────────────────────────────┐
  HTTP server   │  FastAPI app (server.py)                  │
  (live judge)  │   /v1/context  /v1/tick  /v1/reply        │
                │   /v1/healthz  /v1/metadata  /v1/teardown │
                └───────────────┬──────────────────────────┘
                                │ uses
        ┌───────────────────────┼────────────────────────┐
        │ ContextStore          │ ConversationManager     │
        │ (versioned, idempotent│ (per-conv state,        │
        │  by context_id)       │  turn history, suppress)│
        └───────────────────────┼────────────────────────┘
                                │ calls
                    ┌───────────▼───────────┐
                    │  Composer core         │   ← the brain, shared by everything
                    │  compose(cat,mx,trg,cx)│
                    │   - kind dispatch      │
                    │   - prompt build       │
                    │   - LLM call (OpenAI,  │
                    │     temperature=0)     │
                    │   - validate + repair  │
                    └───────────┬───────────┘
                                │ also used by
                    ┌───────────▼───────────┐
                    │  bot.py / build_jsonl  │  ← static submission artifacts
                    └────────────────────────┘
```

**Model:** OpenAI. Default `gpt-4o` (or `gpt-4.1`) for quality on the static `submission.jsonl`;
consider `gpt-4o-mini` (or `gpt-4.1-mini`) for the latency-bound live endpoints (10s tick / 30s reply).
`temperature=0` + a fixed `seed` for determinism.
**Dependency to resolve:** `OPENAI_API_KEY` must be set in the run environment.
**Provider abstraction:** wrap the LLM call behind a single `llm.complete(messages)` function so the
provider/model is swappable from one place (and the judge simulator can be pointed at the same key).

---

## Phases

### Phase 0 — Setup & dataset (foundation)
- [x] Project skeleton: `app/` (`composer/`, `store/`, `config.py`, `dataset.py`), `tests/`, `requirements.txt`, `.env.example`, `.gitignore`.
- [x] `requirements.txt`: fastapi, uvicorn, openai, pydantic, httpx, python-dotenv.
- [x] Run generator → 50 merchants, 200 customers, 100 triggers, `test_pairs.json` (30 pairs).
- [x] Inspect `test_pairs.json` — 30 pairs span all kinds; 9 are customer-facing (T03/04/07/08/13/14/15/28/29).
- [x] Confirm `OPENAI_API_KEY` available; wire `.env` loading. *(Key supplied in `.env`, gitignored, verified live against gpt-4o-mini.)*
**Done when:** dataset expanded on disk and we can load any (category, merchant, trigger, customer) tuple in Python.
**Validate:**
- `ls data/expanded/merchants | wc -l` → 50; customers → 200; triggers → 100; `test_pairs.json` exists with 30 entries.
- One-liner load test: a Python snippet loads a category + merchant + trigger by id without error.
- `pip check` passes; `python -c "import fastapi, uvicorn, openai"` succeeds.
**Commit:** `chore: scaffold vera-bot project and expand challenge dataset`

### Phase 1 — Composer core (the brain) ★ highest leverage
- [x] `compose(category, merchant, trigger, customer=None) -> dict` returning `body, cta, send_as, suppression_key, rationale, template_name, template_params`. → [app/composer/core.py](app/composer/core.py)
- [x] System prompt encoding: role, 5-dimension rubric, compulsion levers, anti-patterns, **no-fabrication rule**, language-mix rules. → [app/composer/prompts.py](app/composer/prompts.py)
- [x] Resolve `trigger.payload` digest references (`top_item_id`/`digest_item_id`/`alert_id`) → full digest item injected.
- [x] Dispatch by `trigger.kind` → 28 per-kind framing hints (merchant + customer scopes).
- [x] `send_as` logic: `vera` when no customer; `merchant_on_behalf` when customer scope.
- [x] CTA enum chosen by model: open_ended / binary_yes_no / binary_confirm_cancel / multi_choice_slot / none.
- [x] Post-LLM **validator** + one repair pass: URLs, CTA shape, send_as, empty body, stacked-CTA, **percentage + named-source grounding** against the contexts. → [app/composer/validate.py](app/composer/validate.py)
- ⚠️ Known limitation: grounding is heuristic — coincidental digits pass, and cross-item source mis-attribution isn't caught. Revisit in Phase 4.
**Done when:** composing for the 10 case-study tuples produces output of comparable shape/quality (eyeball vs `case-studies.md`), deterministic across runs.
**Validate:**
- Run composer on the Dr. Meera research-digest tuple → output has source citation, her cohort, open-ended CTA; compare to Case Study 1.
- Run twice with same input → byte-identical output (determinism).
- Feed a tuple with no customer → `send_as: "vera"`; with customer → `send_as: "merchant_on_behalf"`.
- Inject a URL / multi-CTA in a forced bad generation → validator catches and repairs.
**Commit:** `feat: composer core — LLM message composition with kind dispatch and validator`

### Phase 2 — HTTP server & stores
- [x] `ContextStore`: idempotent by `(scope, context_id)`, version replaces atomically, stale rejected, invalid scope rejected. `contexts_loaded` counts for healthz. → [app/store/context_store.py](app/store/context_store.py)
- [x] `/v1/context`, `/v1/healthz`, `/v1/metadata` per `api-call-examples.md` schemas. → [app/server.py](app/server.py)
- [x] `/v1/tick`: suppression/expiry/active-conv dedup, urgency-sorted, compose-budget cap (5 new/tick) + 20 action cap, unique `conversation_id` per (merchant, trigger), `[]` when nothing worthwhile.
- [x] `/v1/teardown`: wipe state.
- Note: `/v1/reply` is a stub here (ends conversation) — fleshed out in Phase 3.
**Done when:** all examples in `api-call-examples.md` pass via curl; warmup (255 contexts) reflects correct counts.
**Validate:**
- Push all 255 base contexts → `GET /v1/healthz` shows `{category:5, merchant:50, customer:200, trigger:0}`.
- Re-push same `(context_id, version)` → 409 stale; push higher version → 200 and new data used.
- Malformed scope → 400. `/v1/tick` with no worthwhile triggers → `{"actions": []}` within budget.
- `/v1/metadata` returns the exact required keys.
**Commit:** `feat: FastAPI server with versioned context store and /v1/tick composition`

### Phase 3 — Multi-turn conversation handling (`/v1/reply`)
- [x] `ConversationManager`: per-`conversation_id` turn log + state machine. → [app/store/conversation.py](app/store/conversation.py)
- [x] **Auto-reply detection:** canned-phrase + verbatim-repeat → flag once (`send`) → `wait` 24h → `end`. → [app/composer/reply.py](app/composer/reply.py)
- [x] **Intent transition:** explicit accept → directive switches the LLM from qualify to execute (delivers ready artifact).
- [x] **Graceful exit:** opt-out/hostile → deterministic `end` + suppress the originating trigger.
- [x] **Off-topic curveball:** LLM declines out-of-scope + redirects to the thread (verified on GST curveball).
- [x] **Anti-repetition guard:** `Conversation.has_said()` + one re-prompt if the model would resend a body.
- [x] `wait` with sensible `wait_seconds` backoff (auto-reply 24h; LLM-chosen otherwise).
- Hybrid design: deterministic control on opt-out/auto-reply (reliable flow score), LLM for accept/engaged/off-topic.
**Done when:** the 3 replay scenarios (auto-reply hell, intent transition, hostile/off-topic) in `api-call-examples.md` behave correctly.
**Validate:**
- Auto-reply hell: same canned reply ×4 → `send`(flag) → `wait` → `end` (no infinite engagement).
- Intent transition: "ok let's do it" after qualification → `send` with concrete action step, not another question.
- Hostile/opt-out: → `end` with suppression; off-topic GST ask → polite decline + redirect (`send`).
- Resend guard: never emit a `body` already sent in the same `conversation_id`.
**Commit:** `feat: multi-turn /v1/reply — auto-reply detection, intent handoff, graceful exit`

### Phase 4 — Adaptive context & restraint
- [x] Always compose from the **latest** context version — store returns latest; tick & reply re-fetch each call, so mid-test digest/perf/customer injections flow into the next send. Verified by `test_changed_context_changes_composition` + `test_latest_version_replaces_via_http`.
- [x] No hallucination — prompt + grounding validator; `test_output_is_grounded` confirms clean output.
- [x] Suppression honored across ticks (Phase 2) + new restraint: far-off festivals skipped (`FESTIVAL_HORIZON_DAYS=21`) and ≤1 outbound per merchant per tick. → [app/server.py](app/server.py)
**Done when:** re-composing after a version bump visibly uses the new data; suppressed triggers don't re-fire.
**Validate:**
- Push category v2 with a new digest item → next compose references the new item, not the stale one.
- Push updated perf (a dip) → message reflects the new number.
- Same `suppression_key` already acted on → not re-sent on the next tick.
- Prompt the bot with a trigger referencing absent data → it does **not** invent it.
**Commit:** `feat: adaptive context handling and suppression-aware restraint`

### Phase 5 — Submission artifacts
- [x] `bot.py` exposing `compose(category, merchant, trigger, customer)` (thin wrapper on the core). → [bot.py](bot.py)
- [x] `scripts/build_submission.py` → `submission.jsonl` (30 lines, quality model). → [submission.jsonl](submission.jsonl)
- [x] `conversation_handlers.py` with `respond(state, merchant_message)` — shares `handle_turn` with the server. → [conversation_handlers.py](conversation_handlers.py)
- [x] `README.md` (1 page): approach, tradeoffs, what extra context would have helped. → [README.md](README.md)
- [x] `/v1/metadata` filled (set in Phase 2).
- Refactor: reply routing centralized in `reply.handle_turn`, used by both server and handlers.
**Done when:** `submission.jsonl` has 30 valid lines; artifacts self-consistent with the live server.
**Validate:**
- `wc -l submission.jsonl` → 30; each line parses as JSON with keys `test_id, body, cta, send_as, suppression_key, rationale`.
- No line contains a URL; no two lines are byte-identical bodies.
- `bot.py`'s `compose()` output for a sample pair matches the server's output for the same tuple.
- `README.md` ≤ 1 page.
**Commit:** `feat: submission artifacts — bot.py, submission.jsonl, handlers, README`

### Phase 6 — Self-test & iterate
- [x] Curl smoke tests against all 5 endpoints (Phase 2 + here).
- [x] Judge simulator `all` scenario passes (warmup/auto-reply/intent/hostile) → [scripts/run_judge.py](scripts/run_judge.py). Fixed lazy-open of cold-start reply conversations.
- [x] Per-dimension scores via official `LLMScorer` on 9 representative pairs → [scripts/score_samples.py](scripts/score_samples.py): **avg 41.1/50 (82%)**; specificity 8.3, category 9.0, merchant 8.6, decision 7.8, engagement 7.4.
- [x] Fix pass on weakest dim (engagement): sharpened closing-CTA guidance → 7.2→7.4, no message below 7; rebuilt submission.jsonl.
- [x] Latency: tick 3.8s (1 cold) / 6.0s (3 cold, parallelized); reply 2.6s; healthz 1.6ms — all under budget. Tick now composes concurrently (ThreadPoolExecutor).
- [x] No penalties: submission re-validated (no URLs, no dupes, correct send_as, valid CTAs).
**Done when:** judge simulator returns strong non-zero scores across all 5 dimensions on representative pairs.
**Validate:**
- `python ../judge_simulator.py` (provider=openai) runs end-to-end; record per-dimension scores.
- All 5 dimensions ≥ 7 on the representative pairs; note the weakest dimension for a fix pass.
- Time each `/v1/tick` < 10s and `/v1/reply` < 30s in the logs.
- Zero operational penalties in the run (no timeouts, malformed, repetition, URL flags).
**Commit:** `test: judge-simulator pass and latency tuning`

### Phase 7 — Deploy
- [ ] Expose public URL (ngrok for testing; cloud for submission).
- [ ] Confirm reachable `https://<host>/v1/*`, healthz green, metadata correct.
- [ ] Load/quota check so the bot survives the full 60-min window at ≤10 req/s.
**Done when:** public URL passes warmup from an external caller.
**Validate:**
- From a different network, `curl https://<host>/v1/healthz` → 200; `/v1/metadata` correct.
- Push the 255-context warmup from the public URL → counts match.
- Sustained 10 req/s burst for ~60s → no 5xx, latency within budget.
- Submitted URL recorded in `README.md` / submission portal.
**Commit:** `chore: deploy vera-bot to public URL and verify warmup`

---

## Key design decisions & risks
- **Determinism:** `temperature=0` + fixed `seed`; cache LLM responses by input hash so re-pushes/replays are stable and fast.
- **Latency vs quality:** `gpt-4o`/`gpt-4.1` for the static `submission.jsonl` (no time pressure); consider `gpt-4o-mini`/`gpt-4.1-mini` for live `/v1/tick` & `/v1/reply` to stay in budget. Pre-warm nothing the harness doesn't ask for.
- **Provider-swappable:** all LLM access goes through one `llm.complete()` wrapper, so moving OpenAI→another provider later is a one-file change.
- **No-fabrication enforcement:** validator must trace every number/source/competitor name in the body back to the provided context, or repair.
- **Suppression/anti-repetition:** centralize in the stores so both tick and reply paths respect them.
- **API key / cost:** need `OPENAI_API_KEY`; budget for ~30 compositions + replay turns + dev iterations.

## Immediate next step
Phase 0: scaffold the project and run the dataset generator, then inspect `test_pairs.json`.
