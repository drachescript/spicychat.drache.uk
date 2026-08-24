# spicychat.drache.uk

GitHub Pages site for Dragon's SpicyChat bot collection and project links.

- `/` — landing page / project hub
- `/chatbots/` — chatbot collection
- `/chatbots/stats/` — noindex bot stats page
- `/.well-known/discord` — Discord domain verification

## Site data

- `assets/data/bots.json` — curated bot data: blurbs, category, tags, favorites, origin, made date and hidden-image settings
- `assets/data/bot-stats.json` — latest SpicyChat stats update
- `assets/data/bot-history.json` — saved message/status/token history
- `assets/data/bot-events.json` — timeline events such as milestones, visibility changes and new bots

Bot cards are rendered generically; bot entries are not hardcoded in JavaScript.

Personal favorite order is controlled by `favoriteOrder`. Current order: Yui Kimura, Raptor Pack, Nova, Rhea Mercer.

`origin` is the single source of truth for Requested vs Made for Myself. `createdAt` is used for bot age and messages/day; older bots use the best creation evidence currently available when an exact date was not recorded.

## Local updater

`/tools/` stays inside the working project but is gitignored. See `tools/README.md` locally for the HTML importer/history workflow.
