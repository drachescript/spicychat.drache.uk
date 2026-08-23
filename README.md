# spicychat.drache.uk

Static GitHub Pages site for Dragon's SpicyChat bot collection and project links.

- `/` — landing page / project hub
- `/chatbots/` — public chatbot collection
- `/chatbots/stats/` — unlinked/noindex stats page (not private on a static site)
- `/.well-known/discord` — Discord domain verification

## Data split

- `assets/bots.json` — curated/manual data: blurbs, category, tags, favorites, requested/origin, hidden images
- `assets/bot-stats.json` — latest values extracted from SpicyChat: visibility, messages, tokens, current title/image/order data
- `assets/bot-history.json` — snapshot history used for growth comparisons

Bot cards are rendered generically; bot entries are not hardcoded in JavaScript.

Personal favorite order is controlled by `favoriteOrder`. Current order: Yui Kimura, Raptor Pack, Nova, Rhea Mercer.

## Updating from SpicyChat

See `tools/README.md`. Save the My Creations → Chatbots page and run `tools/update-chatbots.bat`; the importer preserves curated fields and creates review stubs for newly detected bots.
