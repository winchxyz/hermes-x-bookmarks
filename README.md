# hermes-x-bookmarks (work in progress)

A Hermes Agent plugin that reads your X bookmarks, including long posts, threads and X Articles,
sorts them with your own Hermes model and keeps them where you work: a Notion board, a Google Doc
or a document on your Desktop. Every week it tells you what you saved and turns the good ones into
tasks, notes or Hermes skills.

Status: design done, code starts next. See:

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): components, X API use, Articles, exports, Hermes surfaces
- [docs/PLAN.md](docs/PLAN.md): build phases with gates
- [docs/DECISIONS.md](docs/DECISIONS.md): open and settled decisions
- [docs/SETUP.md](docs/SETUP.md): X app, Notion and Google setup for the owner
- [docs/research/](docs/research/): sourced research on the X API, the export targets and the Hermes platform

Uses the official X API only. No scraping, no browser automation.

## License

MIT
