# Claude Code Notes

Before changing this project, read:

- `skills/ai-news-radar/SKILL.md`
- `docs/SOURCE_COVERAGE.md`
- `README.md`

Do not commit private OPML files, API keys, cookies, browser exports, or `.env`
values. Keep the public repo usable without secrets.

Project iron rules:

- For every bug fix, start from first principles before changing code. Write down the bottom-level fact/root cause, whether an architecture/schema/API change is truly required, and the smallest reversible fix that solves the root cause.
- For acceptance or testing of any browser-visible flow, local dashboard, or UI interaction, use a browser tool for real validation before reporting back. Do not stop at unit tests, static checks, or asking the user to click first. If browser-tool validation is impossible, state the blocker and what remains unverified.

The product direction is a two-layer AI news tool:

- Default layer: curated AI-focused view for ordinary AI enthusiasts.
- Advanced layer: custom OPML/source configuration and source health details for maintainers.

When adding sources, prefer official RSS/Atom feeds or OPML first. Add custom
fetchers only for stable, public, high-signal sources.
