# PGT Site Assistant

The grounded chat assistant for **precisionguessworktech.com**. It answers
questions about PGT strictly from a small, curated services corpus, refuses to
invent anything it can't ground, draws out a prospect's problem, and hands the
qualified ones off to the founder's email with the problem already summarized.

PGT sells AI reliability. This assistant *is* that claim, running: a visitor
frustrated by AI that drifts and hallucinates meets one that doesn't — on the
homepage, before they ever contact the founder.

**The moat rail:** every substantive answer is grounded in the corpus. When the
corpus doesn't cover something — a price it doesn't state, an unrelated fact, an
invented capability — it says so plainly and offers the founder handoff. It
never fills a gap with a guess. That behavior is not a feature here; it's the
product, and it ships correct or it doesn't ship.

---

## How it works

- **Grounding is corpus-in-context, not embeddings.** The corpus is small,
  curated, and *is* PGT's entire public services story, so the whole thing is
  handed to the model as its only source every turn, with a hard instruction to
  answer from it alone and flag when it can't. For a corpus this size that's
  simpler and *more* reliable than retrieval (nothing to miss), and it boots
  instantly (no vector store, no model download).
- **Structured, testable contract.** The model returns
  `{reply, in_corpus, handoff_ready, problem_summary}`. `in_corpus` drives the
  visible "Grounded in PGT's services" marker; `handoff_ready` + `problem_summary`
  drive the pre-filled email handoff (the problem only — never an invented
  commitment).
- **Two-tier architecture.** A small FastAPI service holds the API key and does
  the grounded answering; a single self-contained `widget.js` drops onto the
  static site with one `<script>` tag and calls the service.

```
Visitor ──> widget.js (on the PGT site) ──HTTPS──> FastAPI /chat ──> Claude Messages API
                                                        │
                                                   corpus/*.md  (the only source of truth)
```

## Project layout

```
app/
  config.py       env-driven config (key, model, founder email, CORS origins)
  corpus.py       loads corpus/*.md into one grounding block
  assistant.py    the rails: system prompt, Claude call, JSON parse, errors  <- load-bearing
  main.py         FastAPI: /chat, /health, /widget.js, CORS
corpus/           the editable services knowledge base (PUBLIC-facing only)
static/
  widget.js       the embeddable widget (single file, no build, themeable)
  index.html      standalone demo page (what the API's / serves)
scripts/          live smoke tests, one per brick group
render.yaml       Render.com blueprint (deploy)
```

## Editing the services corpus

The corpus is `corpus/*.md` — plain Markdown, loaded in filename order. **This is
how you keep the assistant current: edit these files, redeploy, done.** No code
change needed. Each file is one topic (overview, services, products/proof,
approach, how-we-work/contact).

**IP rail — non-negotiable:** the corpus is PGT's *public-facing* services story
only. No Kernel internals, no proprietary substrate architecture, no private
canon. Shop window, not workshop. If the assistant shouldn't say it to a stranger
on the internet, it doesn't go in the corpus.

If you add a price, a timeline, or a guarantee to the corpus, the assistant will
state it. If you don't, it will correctly say Les scopes each engagement and hand
off. That's the design — the corpus is the single source of what it's allowed to
claim.

## Local setup

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows;  source .venv/bin/activate on *nix
pip install -r requirements.txt
copy .env.example .env             # then put your real ANTHROPIC_API_KEY in .env
uvicorn app.main:app --reload --port 8000
```

Open http://localhost:8000 for the demo page with the widget on it.

### Environment variables

| Var                 | Required | Default                                   | Purpose                                  |
|---------------------|----------|-------------------------------------------|------------------------------------------|
| `ANTHROPIC_API_KEY` | yes      | —                                         | Claude API key. Never commit it.         |
| `ANTHROPIC_MODEL`   | no       | `claude-sonnet-4-5`                       | Model used for answering.                |
| `FOUNDER_EMAIL`     | no       | `lesfleming@precisionguessworktech.com`   | The single handoff target.               |
| `ALLOWED_ORIGINS`   | no       | live site + localhost                     | Comma-separated CORS allowlist.          |
| `MAX_HISTORY_TURNS` | no       | `24`                                      | Conversation turns sent to the model.    |

The real `.env` is gitignored. In production, set these in the deploy platform's
dashboard.

## Proving it (red before green)

Each smoke test hits the real rails, live. Run them with the venv active:

```bash
python -m scripts.smoke_brick0      # grounding spine on a 2-line test corpus
python -m scripts.smoke_grounding   # real corpus: grounded answers + FORCED refusals (the moat rail)
python -m scripts.smoke_handoff     # a mock prospect chat -> usable summary + email handoff, no commitments
python -m scripts.smoke_errors      # forced failures -> clean message + email fallback, never a fabrication
```

"It works" here means the moat rail was *forced* — asked for a price it doesn't
have, an invented capability, an unrelated fact — and watched declining to
fabricate every time. Green by inference is not green.

## Deploy (Render)

1. Push this repo to GitHub.
2. Render → **New + → Blueprint**, point at the repo (`render.yaml` is included).
3. Set `ANTHROPIC_API_KEY` in the Render dashboard (it's `sync:false`, so it
   stays out of the repo).
4. Deploy. The service boots fast — no build-time model download.
5. Health check: `GET /health` returns the loaded corpus sections.

## Embed on the PGT site

Add one line where the widget should appear (e.g. before `</body>` in
`index.html`), pointing `data-api` at the deployed service:

```html
<script src="https://pgt-site-assistant.onrender.com/widget.js"
        data-api="https://pgt-site-assistant.onrender.com" defer></script>
```

The widget injects its own scoped styles (all classes prefixed `pgtw-`, so it
won't collide with the site), matches the site's dark/red theme out of the box,
and is fully responsive. Optional overrides via a global before the script:

```html
<script>
  window.PGT_ASSISTANT = {
    api: "https://pgt-site-assistant.onrender.com",
    title: "Ask PGT",
    greeting: "Hi — I'm PGT's assistant. …",
    // theme: { red: "#ff4b3e", amber: "#e0a020", ... }
  };
</script>
```

Make sure the site's origin is in `ALLOWED_ORIGINS` on the service (the default
already includes `precisionguessworktech.com`).

## What this is NOT

No scheduling backend. No answering about PGT from general knowledge — only from
the corpus. No invented prices, timelines, guarantees, or clients. No pretending
to be human. No Kernel IP anywhere in the corpus or code. If a change tempts past
that fence, it doesn't belong here.
