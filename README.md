# plugin.video.kick

![Kodi](https://img.shields.io/badge/Kodi-19%2B-brightgreen?logo=kodi)
![License](https://img.shields.io/badge/license-GPL--2.0-green)
![Version](https://img.shields.io/github/v/release/zales/plugin.video.kick)

A Kodi add-on for [kick.com](https://kick.com) — the live streaming platform.  
Watch live streams, browse VODs and clips, follow your favourite channels, all from inside Kodi.

## Features

- **Live streams** — browse by language (41 languages) and category
- **Categories & subcategories** — Games, IRL, Music, Gambling, Creative, Alternative
- **Channel pages** — live stream indicator, past VODs, clips
- **Search** — find channels and categories instantly
- **Account login** — including 2FA support
- **Follow / unfollow** — channels and categories, with context menu
- **HLS playback** — via InputStream Adaptive with optional quality selector
- **Cloudflare bypass** — via bundled cloudscraper
- **UI languages** — English, Czech, Polish

## Requirements

- Kodi 19+ (Matrix) with Python 3
- [InputStream Adaptive](https://kodi.wiki/view/Add-on:InputStream_Adaptive) (for playback)
- [InputStream Helper](https://kodi.wiki/view/Add-on:InputStream_Helper) (optional, for helper dialogs)

## Installation

### Via Kodi repository (recommended)

1. In Kodi: **Settings → File Manager → Add source**
2. Enter URL: `https://zales.github.io/plugin.video.kick/`  name it `KICK repo`
3. **Add-ons → Install from zip file → KICK repo** → select the zip
4. The add-on will update automatically with new releases

### Manual (zip)

1. Download `plugin.video.kick-x.x.zip` from [Releases](https://github.com/zales/plugin.video.kick/releases)
2. In Kodi: **Settings → Add-ons → Install from zip file**
3. Select the downloaded zip

## Building from source

```bash
cd ..
zip -r plugin.video.kick.zip plugin.video.kick \
  --exclude "*/.git*" --exclude "*/__pycache__/*" --exclude "*/.DS_Store"
```

## Bundled libraries

- [cloudscraper](https://github.com/venomous/cloudscraper) — MIT License  
  Used to bypass Cloudflare bot protection on kick.com API endpoints.
- [requests-toolbelt](https://github.com/requests/toolbelt) — Apache 2.0 License  
  Dependency of cloudscraper.

## License

GPL-2.0 — see [LICENSE](LICENSE)

## Disclaimer

This addon is not affiliated with or endorsed by kick.com.
