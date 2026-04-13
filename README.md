# plugin.video.kick

![Kodi](https://img.shields.io/badge/Kodi-19%2B-brightgreen?logo=kodi)
![License](https://img.shields.io/badge/license-GPL--2.0-green)
![Version](https://img.shields.io/github/v/release/zales/plugin.video.kick)

A Kodi add-on for [kick.com](https://kick.com) — the live streaming platform.  
Watch live streams, browse VODs and clips, all from inside Kodi.

## Features

- **Live streams** — browse by language (41 languages) and category
- **Categories & subcategories** — all Kick categories with cursor pagination
- **Channel pages** — live stream indicator, past VODs, clips
- **Search** — find channels and categories instantly
- **HLS playback** — via InputStream Adaptive with optional quality selector
- **Cloudflare Worker proxy** — at [kodi.zales.dev](https://kodi.zales.dev) to bypass Kick WAF
- **UI languages** — English, Czech, Polish

## Requirements

- Kodi 19+ (Matrix) with Python 3
- [InputStream Adaptive](https://kodi.wiki/view/Add-on:InputStream_Adaptive) (for playback)
- [InputStream Helper](https://kodi.wiki/view/Add-on:InputStream_Helper) (optional, for helper dialogs)

## Installation

### Via Kodi repository (recommended — auto-updates)

1. Kodi → **Settings → File Manager → Add source**
   - URL: `https://kodi.zales.dev`
   - Name: `KICK repo`
2. Kodi → **Add-ons → Install from zip file → KICK repo** → `repository.zales.kick` → `repository.zales.kick-1.0.0.zip`
3. Kodi → **Add-ons → Install from repository → KICK.com Repository → Video add-ons → KICK.com → Install**

### Direct install (no auto-updates)

1. Download `plugin.zip` from [kodi.zales.dev](https://kodi.zales.dev) or `plugin.video.kick-x.x.x.zip` from [Releases](https://github.com/zales/plugin.video.kick/releases)
2. Kodi → **Add-ons → Install from zip file** → select the downloaded zip

## Building from source

```bash
cd ..
zip -r plugin.video.kick.zip plugin.video.kick \
  --exclude "*/.git*" --exclude "*/__pycache__/*" --exclude "*/.DS_Store"
```

## License

GPL-2.0 — see [LICENSE](LICENSE)

## Disclaimer

This addon is not affiliated with or endorsed by kick.com.
