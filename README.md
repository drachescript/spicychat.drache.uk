# spicychat.drache.uk

Static GitHub Pages site for Dragon's SpicyChat bot collection and project links.

- `/` — landing page / project hub
- `/chatbots/` — chatbot collection
- `/.well-known/discord` — Discord domain verification

## Bot data
Bots live in `assets/bots.json`; the renderer is generic and bot entries are not hardcoded in JS.

Useful fields: `id`, `name`, `category`, `tags`, `title`, `blurb`, `url`, `requested`, `order`, `image`, `imageHidden`, `favoriteOrder`, `addedAt`.

For an avatar that must not be displayed, use `"image": null`, `"imageHidden": true`, and optionally `"imageNote": "NSFW avatar hidden"`.

Personal favorite order is controlled by `favoriteOrder`. Current order: Yui Kimura, Raptor Pack, Nova, Rhea Mercer.

`addedAt` uses `YYYY-MM-DD`; the `New` badge lifetime is controlled by `newBadgeDays`.
