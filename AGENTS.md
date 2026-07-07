# AI News Radar Agent Notes

## Scope

This repo powers the public AI News Radar static site and Scout Skill source workflow.
Use it for high-signal AI/tech news aggregation, OPML-based custom feeds,
GitHub Actions refresh jobs, and GitHub Pages publishing.

## Working Rules

- Keep changes small and reviewable.
- Search the repo before changing source fetchers or output schemas.
- Do not commit private feeds, secrets, tokens, cookies, or `.env` values.
- Do not commit `feeds/follow.opml`; use `feeds/follow.example.opml` as the public template.
- Prefer stable public RSS/Atom/OPML sources before adding custom scrapers.
- Keep the reader-facing product simple: default to a curated AI-focused view, hide noisy or advanced source details behind existing filters/docs.

## Iron Rules

- For every bug fix, start from first principles before changing code. Write down the bottom-level fact/root cause, whether an architecture/schema/API change is truly required, and the smallest reversible fix that solves the root cause.
- For acceptance or testing of any browser-visible flow, local dashboard, or UI interaction, use a browser tool for real validation before reporting back. Do not stop at unit tests, static checks, or asking the user to click first. If browser-tool validation is impossible, state the blocker and what remains unverified.

## Source Strategy

Read `docs/SOURCE_COVERAGE.md` before adding or removing sources.

Default source priority:

1. Official RSS/Atom feeds and OPML collections.
2. Stable public JSON APIs or static pages with timestamps.
3. Curated newsletters or changelogs with public feeds.
4. Manual/custom adapters only when the source is high-signal and stable.

Avoid account-bound timelines, broad personal social feeds, login-gated pages,
and fragile bridges unless the user explicitly accepts the maintenance cost.

## Common Commands

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
python -m py_compile scripts/update_news.py
python -m pytest -q
python scripts/update_news.py --output-dir data --window-hours 24 --rss-opml feeds/follow.opml
python -m http.server 8080
```

For agent workflows, read `skills/ai-news-radar/SKILL.md`.
