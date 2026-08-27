# Changelog

## v0.6.8 — August 27, 2026

- added the new `/requests/` character-request page and a Requests button to the main navigation
- added an 18+ Yes/No gate that remembers accepted browsers locally
- added short and detailed request-preference views, with unlisted themes explicitly not treated as automatic approval
- added the custom request form with required Discord-or-email contact, request type, idea, `{{user}}`, dynamic, content rating, kinks/themes, hard no's and flexibility
- added a Copy for Discord option so the same request can be pasted directly to `@dragongraf`
- connected website submissions to the Cloudflare request Worker so successful requests receive their saved request ID
- added the optional Discord server link without requiring server membership
- kept contact details private and added the adult-characters-only confirmation for sexual requests
- added `assets/data/requests.json` so request status, Discord link, API endpoint and preference lists are easy to edit

## v0.6.7 — August 25, 2026

- New badges now last 7 days; public bots use their public date while unlisted bots use their made date
- added a separate Hot badge for the strongest visible 24-hour growers
- Recent Changes now fills up to 5 useful entries by pulling in earlier saved updates when the latest update is sparse
- recent-change rows now show rank movement, milestone context and how recent the change was
- kept Recently Made compact at 5 entries with a link to the full New bots activity view
- bot rows across Stats are clickable and open the reusable detailed bot page
- detailed bot pages now include an at-a-glance summary, current/previous rank and best observed 7-day performance
- Data Check now stays hidden when there is nothing that needs attention
- milestone tracking continues to use 100 / 250 / 500 / 1k / 2.5k / 5k / 10k

## v0.6.6 — August 25, 2026

- split the growing stats dashboard into Overview, Trending, Update History, Activity and Low Movement pages
- kept the main Stats overview compact instead of putting every analytics tool on one page
- added one reusable detailed stats page for every bot
- bot detail pages show made date, confirmed public date, current rank, recent growth, since-public growth, launch tracking, history, bot info and milestones
- chatbot cards are now clickable and open that bot's detailed stats page
- kept the existing Open on SpicyChat button unchanged
- bot names throughout Stats now link to the reusable detailed bot page

## v0.6.5 — August 25, 2026

- replaced the estimated public dates with the SpicyChat approval-email times for all 36 current public bots
- kept the public date separate from the first saved message baseline
- since-public message gains now stay marked as a minimum when the first message snapshot happened after publication
- bot history now shows the confirmed public time and when message tracking started
- Data Check now points out public bots that only have an estimated public date

## v0.6.4 — August 25, 2026

- expanded Stats with 6h, 12h, 24h, 3d, 7d, 14d, 30d and all-time views
- added recent popularity, message gain and percentage-growth rankings
- added per-bot history with saved message points and a small graph
- added update history so each saved stats update can be opened and compared
- added public message baselines so public bots can show how much they gained after first being seen public
- backfilled the public baselines from older saved SpicyChat pages where possible
- the automatic and local updaters now keep public baselines for future bots
- Stats now has the main navigation spot instead of Changelog
- changed the visible Dragon site image to `dragonfull.jpg` while keeping the smaller favicon/app icons

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
- cleaned up a few stats page labels
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
