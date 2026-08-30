# 个人订阅聚合器 Agent Notes

## Scope

This repo powers the owner's personal subscription aggregator static site
（页面标题「我的订阅」）and Scout Skill source workflow.
Use it for OPML/custom feeds, GitHub Actions refresh jobs, and GitHub Pages publishing.
It is independently maintained; it started from LearnPrompt/ai-news-radar.

## Working Rules

- Keep changes small and reviewable.
- Search the repo before changing source fetchers or output schemas.
- Do not commit private feeds, secrets, tokens, cookies, or `.env` values.
- Do not commit `feeds/follow.opml`; use `feeds/follow.example.opml` as the public template.
- Prefer stable public RSS/Atom/OPML sources before adding custom scrapers.
- Keep the reader-facing product simple. Since 2026-07-11 the default view is the owner's own
  subscription feed, **not** a curated AI selection: AI relevance is no longer a filter
  (`AI_RELEVANCE_THRESHOLD` is set to `0` in production). Do not optimize for "filling the AI
  feed" and do not suggest adding AI news sources to raise AI content share unless asked.
  See the "产品方向" section in `CLAUDE.md`.
- YouTube 订阅成员当前只有「小岛大浪吹-非正经政经频道」和「脑总MrBrain」。OpenAI / Hugging Face / Simon Willison / Google AI / DeepMind / Microsoft AI Blog 等公开博客 RSS 以及 HighLevelz 默认停用，不要当订阅成员重新打开，除非用户明确要求。
- 「已阅」只按工作台链接键计数，不要用标题或 ID 把已阅扩散到其它条目。
- 改 `assets/js/**` 后必须同步提高 `index.html` 里对应脚本的 `?v=`；工作台嵌套页的 `wb=` 也要换，否则浏览器或 iframe 会继续用旧脚本。

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
