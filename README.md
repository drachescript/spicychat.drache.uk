# spicychat.drache.uk

Small static site for Dragon's SpicyChat stuff.

## Pages

- `/` — landing page with Chatbots / SpicyChat QoL choices
- `/chatbots/` — all chatbot categories and links
- QoL links to https://spicychatqol.drache.uk/

## Add a bot

Open `assets/bots.js` and add another object to `window.BOTS`.

Main fields:

- `name`
- `category`
- `title`
- `blurb`
- `url`
- `requested`

Set `requested: true` if the bot was made from a request. It will stay in its normal category and also appear in the Requested section.

## Current categories

- `dragon-hybrid`
- `indoraptor`
- `pov`
- `fandom`
- `other`
- `requested` is generated from `requested: true`

## GitHub Pages

This repository is ready to be published from the root of the `main` branch. The `CNAME` file is already set to `spicychat.drache.uk`.
