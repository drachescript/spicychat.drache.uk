# spicychat.drache.uk

Static site for my SpicyChat bot collection.

## Main pages

- `/` — home
- `/chatbots/` — full bot collection
- `/chatbots/stats/` — bot stats
- `/changelog/` — site changelog

## Bot data

Public site data lives in `assets/data/`.

- `bots.json` — the hand-edited bot list, categories, origins, favorites and made dates
- `bot-stats.json` — latest usage stats
- `bot-history.json` — saved stat history
- `bot-events.json` — milestones and other tracked changes
- `bot-discoveries.json` — new public bots noticed by the automatic updater but not added to the collection yet

## Automatic stats

`.github/workflows/update-bot-stats.yml` checks the public creator page and direct bot profile pages. During testing it runs every 2 hours. The normal schedule can be changed to every 6 hours later.

The automatic updater only changes usage/stat data. It does not rewrite hand-edited bot info such as categories, origins, blurbs or favorites.

The local My Creations updater stays under `/tools/` and is ignored by git.
