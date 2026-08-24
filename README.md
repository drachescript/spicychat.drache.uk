# spicychat.drache.uk

Static GitHub Pages site for Dragon's SpicyChat bot collection and project links.

- `/` — landing page / project hub
- `/chatbots/` — public chatbot collection
- `/chatbots/stats/` — unlinked/noindex creator stats page (not private on a static site)
- `/.well-known/discord` — Discord domain verification

## Public data

- `assets/data/bots.json` — curated/manual bot data: blurbs, category, tags, favorites, origin and hidden-image settings
- `assets/data/bot-stats.json` — latest extracted SpicyChat snapshot
- `assets/data/bot-history.json` — saved message/status/token snapshots
- `assets/data/bot-events.json` — derived timeline events such as milestones, visibility changes and new bots

Bot cards are rendered generically; bot entries are not hardcoded in JavaScript.

Personal favorite order is controlled by `favoriteOrder`. Current order: Yui Kimura, Raptor Pack, Nova, Rhea Mercer.

`knownSince` means the earliest creation-context/saved-page evidence currently available, not a guaranteed exact creation timestamp. Requested/personal origin stays `unknown` unless prior creation context supports the classification.

## Local updater

`/tools/` stays inside the working project but is gitignored. See `tools/README.md` locally for the HTML importer/history workflow.
