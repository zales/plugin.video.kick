# plugin.video.kick

Kodi addon for [kick.com](https://kick.com) — watch live streams, VODs, and clips.

## Features

- Browse live streams by language and category
- Browse and search subcategories
- Channel pages with live stream, past VODs, and clips
- Search channels and categories
- Login with kick.com account
- Follow / unfollow channels and categories
- HLS playback via InputStream Adaptive (quality selector optional)
- Languages: English, Polish, Czech

## Requirements

- Kodi 19+ (Matrix) with Python 3
- [InputStream Adaptive](https://kodi.wiki/view/Add-on:InputStream_Adaptive) (for playback)
- [InputStream Helper](https://kodi.wiki/view/Add-on:InputStream_Helper) (optional, for helper dialogs)

## Installation

1. Download `plugin.video.kick.zip` from [Releases](../../releases)
2. In Kodi: **Settings → Add-ons → Install from zip file**
3. Select the downloaded zip

## Building from source

```bash
cd ..
ditto -c -k --sequesterRsrc --keepParent plugin.video.kick plugin.video.kick.zip
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
