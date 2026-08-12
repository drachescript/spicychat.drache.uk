# spicychat.drache.uk

Small static site for my SpicyChat stuff.

## Pages

- `/` — landing page with Chatbots / SpicyChat QoL
- `/chatbots/` — bot showcase, categories and search
- QoL links to https://spicychatqol.drache.uk/

## Add or edit bots

Everything is in `assets/bots.json`. The layout itself does not contain the bot list.

Each bot has:

- `name`
- `category`
- `title`
- `blurb`
- `url`
- `image`
- `requested`

Set `requested` to `true` if somebody requested the bot. It will still show in its normal category and will also appear under Requested.

For SpicyChat avatar images I use the CDN URL, for example:

```text
https://cdn.nd-api.com/avatars/c764f723-5894-448e-ae8e-a6d6b48f824f.jpg?class=avatar256x256
```

## Current categories

- `dragon-hybrid`
- `indoraptor`
- `pov`
- `fandom`
- `other`
- `requested` is generated from `requested: true`

## Site icons

The cropped profile picture/favicon files are in `assets/icons/`.

## GitHub Pages

Publish the root of the `main` branch. `CNAME` is already set to `spicychat.drache.uk`.
