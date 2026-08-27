# spicychat.drache.uk

Static GitHub Pages site for Dragon's SpicyChat bot collection.

## Main pages

- `/` — home
- `/chatbots/` — bot collection
- `/requests/` — 18+ character request page + custom request form
- `/chatbots/stats/` — compact stats overview
- `/chatbots/stats/trending/` — recent growth / popularity
- `/chatbots/stats/history/` — saved stats update history
- `/chatbots/stats/activity/` — milestones and collection activity
- `/chatbots/stats/quiet/` — low-movement bots
- `/chatbots/stats/bot/?bot=<slug>` — reusable detailed page for one bot
- `/changelog/` — site changelog

Bot/content data stays under `assets/data/`. Local import tools stay under `tools/` and are gitignored.

## Collection badges

- `New` lasts 7 days. Public bots count from their public date; unlisted bots count from their made date.
- `Hot` is based on the strongest visible 24-hour message growth from saved stats history.

## Requests

- Request status, Discord link, Worker endpoint and public preference lists live in `assets/data/requests.json`.
- The 18+ gate is remembered per browser using the configured gate version.
- Website submissions post to the Cloudflare Worker; the Discord webhook itself never lives in this repo.
- The form also has a copy-for-Discord fallback.
