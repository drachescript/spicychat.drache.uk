# Changelog

## v0.6.3 — August 24, 2026

- added automatic bot stat checks through GitHub Actions
- testing schedule runs every 2 hours for now
- the public creator page is checked first, then direct bot pages for anything missing there
- public and unlisted bot message counts can update without needing a My Creations export
- NSFW bots that are hidden from the logged-out creator page can still update through their direct bot page
- private or unavailable bots are left alone instead of breaking the whole update
- message counts, tokens, history, milestones and confirmed public visibility can update automatically
- categories, origins, blurbs, favorites and other hand-edited bot info are never overwritten
- new public bots are noted for review instead of being added to the collection automatically
- added the changelog page

## v0.6.2 — August 24, 2026

- cleaned up the stats page wording
- changed Latest snapshot to Latest update
- changed Recently known to Recently made
- changed Data health to Data check
- added bot age and average messages per day
- bot age now uses the bot's made date instead of the latest saved HTML date
- moved short-term message changes into their own Since last update section
- removed the old requested field and kept origin as the only source for Requested / Made for Myself
- finished filling in origins for all current bots
- updated the local My Creations importer for the newer stats format

## v6 — August 24, 2026

- moved the public JSON files into assets/data
- added message history, milestones, rank movement and category/origin stats
- added the stats page
- added safer local My Creations importing with backups and stale-export checks
- kept local imports, archives, backups and reports under tools/storage

## v5 — August 23, 2026

- updated the collection to 40 bots
- added message counts and visibility badges to bot cards
- added bot-stats.json and bot-history.json
- added the first local My Creations updater
- kept Doe's avatar hidden from the site data

## v4

- expanded the collection data and categories
- kept the compact desktop card layout
- fixed card sizing so the Open on SpicyChat button stays visible

## v3.1

- fixed the chatbot card Open button layout

## v3

- moved the chatbot collection to JSON-driven cards
- added favorites, category browsing and search

## v2

- expanded the first site layout and bot collection

## First version

- added the main site, chatbot page and QoL links
