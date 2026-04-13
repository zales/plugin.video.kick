# -*- coding: UTF-8 -*-
"""Kodi plugin for kick.com."""
import unicodedata
from urllib.parse import quote, quote_plus, parse_qs, urlencode, urlparse

import requests
import xbmcgui
import xbmcplugin
import xbmcaddon
import xbmc

from resources.lib.routing import Plugin

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
UA        = 'okhttp/4.9.2'
UA_STREAM = 'Dalvik/2.1.0 (Linux; U; Android 9; SM-G960F Build/R16NW)'
ADDON_ID  = 'plugin.video.kick'

# Public developer API (stable, needs Bearer token from client_credentials)
API_PUB    = 'https://api.kick.com/public/v1'
API_PUB_V2 = 'https://api.kick.com/public/v2'

# Cloudflare Worker base URL
WORKER_BASE = 'https://kodi.zales.dev'

# Public API endpoints (require Bearer app token)
URL_PUB_LIVESTREAMS = API_PUB + '/livestreams'
URL_PUB_CHANNEL     = API_PUB + '/channels'
URL_PUB_CATEGORIES  = API_PUB + '/categories'
URL_PUB_V2_CATS     = API_PUB_V2 + '/categories'

# Worker endpoints
URL_APP_TOKEN     = WORKER_BASE + '/app-token'
URL_PROXY_STREAM  = WORKER_BASE + '/proxy/kick/api/v2/channels/{slug}/livestream'
URL_PROXY_CHANNEL = WORKER_BASE + '/proxy/kick/api/v1/channels/{slug}'
URL_PROXY_CLIPS   = WORKER_BASE + '/proxy/kick/api/v2/channels/{slug}/clips?cursor=0&sort=view&time=all'
URL_PROXY_VIDEO   = WORKER_BASE + '/proxy/kick/api/v1/video/{uuid}'

# ---------------------------------------------------------------------------
# Kodi setup
# ---------------------------------------------------------------------------
plugin   = Plugin()
addon    = xbmcaddon.Addon(id=ADDON_ID)
language = addon.getLocalizedString

PATH          = addon.getAddonInfo('path')
RESOURCES     = PATH + '/resources/'
ICON          = RESOURCES + '../icon.png'
NEXT_PAGE_IMG = RESOURCES + 'right.png'

# ---------------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------------
session    = requests.Session()
session.headers.update({'User-Agent': UA, 'Accept': 'application/json'})

# Token cache: stored in the home Window so it persists across plugin invocations
# within a single Kodi session (each plugin call is a new Python process).
_WIN       = xbmc.Window(10000)
_TOKEN_KEY = 'kick_app_token'


def _api_get(url):
    """GET url, return parsed JSON dict/list or {} on error."""
    try:
        r = session.get(url, timeout=15)
        xbmc.log('KICK: GET {} → {}'.format(url[:120], r.status_code), xbmc.LOGINFO)
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        xbmc.log('KICK: GET {} failed: {}'.format(url[:120], exc), xbmc.LOGERROR)
        return {}


def _get_app_token():
    """Return a Bearer token, cached in the home Window property across requests."""
    token = _WIN.getProperty(_TOKEN_KEY)
    if token:
        return token
    try:
        r = session.get(URL_APP_TOKEN, timeout=10)
        r.raise_for_status()
        token = r.json().get('token', '')
        if token:
            _WIN.setProperty(_TOKEN_KEY, token)
    except Exception as exc:
        xbmc.log('KICK: app-token failed: {}'.format(exc), xbmc.LOGERROR)
    return token


def _pub_get(url):
    """GET a Kick public API URL with Bearer app token; return parsed JSON or {}."""
    token = _get_app_token()
    if not token:
        return {}
    try:
        r = session.get(url, timeout=15, headers={'Authorization': 'Bearer ' + token})
        xbmc.log('KICK: PUB {} → {}'.format(url[:120], r.status_code), xbmc.LOGINFO)
        if r.status_code == 401:
            # Token expired — clear cache and retry once
            _WIN.setProperty(_TOKEN_KEY, '')
            token = _get_app_token()
            if not token:
                return {}
            r = session.get(url, timeout=15, headers={'Authorization': 'Bearer ' + token})
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        xbmc.log('KICK: PUB {} failed: {}'.format(url[:120], exc), xbmc.LOGERROR)
        return {}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
LIVE_BADGE = ' · [B][COLOR yellowgreen]LIVE[/COLOR][/B]'

LANGUAGES = [
    ('af',  'afrikaans'),    ('sq',  'albanian'),    ('ar',  'arabic'),
    ('bn',  'bangla'),       ('bg',  'bulgarian'),   ('ca',  'catalan'),
    ('zh',  'chinese'),      ('cs',  'czech'),       ('nl',  'dutch'),
    ('en',  'english'),      ('fil', 'filipino'),    ('fi',  'finnish'),
    ('fr',  'french'),       ('ka',  'georgian'),    ('de',  'german'),
    ('el',  'greek'),        ('he',  'hebrew'),      ('hi',  'hindi'),
    ('hu',  'hungarian'),    ('id',  'indonesian'),  ('it',  'italian'),
    ('ja',  'japanese'),     ('ko',  'korean'),      ('la',  'latin'),
    ('mn',  'mongolian'),    ('fa',  'persian'),     ('pl',  'polish'),
    ('pt',  'portuguese'),   ('ro',  'romanian'),    ('ru',  'russian'),
    ('sr',  'serbian'),      ('sk',  'slovak'),      ('es',  'spanish'),
    ('sv',  'swedish'),      ('th',  'thai'),        ('tr',  'turkish'),
    ('uk',  'ukrainian'),    ('ur',  'urdu'),        ('vi',  'vietnamese'),
    ('yo',  'yoruba'),       ('zu',  'zulu'),
]


def clean_title(s):
    """Strip newlines, known emoji, and Unicode Symbol-other characters from a string."""
    s = (s or '').replace('\n', ' ').replace('\U0001f534', '').replace('\U0001f42a', '')
    return ''.join(c for c in s if 'So' not in unicodedata.category(c))


def add_item(url, name, image, infoLabels=None, IsPlayable=False, folder=False, icon=None):
    """Create a ListItem and add it to the current directory listing."""
    li = xbmcgui.ListItem(label=name)
    if IsPlayable:
        li.setProperty('IsPlayable', 'True')
    li.setInfo(type='video', infoLabels=infoLabels or {'title': name})
    li.setArt({'thumb': image, 'poster': image, 'banner': image, 'icon': icon or image})
    xbmcplugin.addDirectoryItem(handle=plugin.handle, url=url, listitem=li, isFolder=folder)


def _end_dir():
    """Finalise the directory listing (add sort method and signal end)."""
    xbmcplugin.addSortMethod(plugin.handle, xbmcplugin.SORT_METHOD_NONE,
                             label2Mask='%R, %Y, %P')
    xbmcplugin.endOfDirectory(plugin.handle)


# ---------------------------------------------------------------------------
# Routes — Views
# ---------------------------------------------------------------------------
@plugin.route('/')
def home():
    """Main menu: language picker, live, categories, search, settings."""
    lang_val  = addon.getSetting('lang')
    lang_lab  = addon.getSetting('lang_lab')

    add_item(plugin.url_for(select_language),
             '{}: {}'.format(str(language(30000)), lang_lab), ICON)
    add_item(plugin.url_for(live, url=URL_PUB_LIVESTREAMS + '?language={}&limit=25'.format(lang_val)),
             str(language(30003)), ICON, folder=True)
    add_item(plugin.url_for(list_subcategories, url=URL_PUB_V2_CATS + '?limit=50'),
             str(language(30004)), ICON, folder=True)
    add_item(plugin.url_for(search_dialog),     str(language(30005)), ICON)
    add_item(plugin.url_for(settings),   str(language(30041)), ICON)
    _end_dir()


@plugin.route('/language')
def select_language():
    """Show a dialog to pick the content language and persist the choice."""
    labels = [label for _, label in LANGUAGES]
    sel = xbmcgui.Dialog().select(str(language(30013)) + str(language(30014)), labels)
    if sel == -1:
        return
    addon.setSetting('lang',     LANGUAGES[sel][0])
    addon.setSetting('lang_lab', LANGUAGES[sel][1])
    xbmc.executebuiltin('Container.Refresh')


@plugin.route('/categories')
def list_categories():
    """Redirect straight to all categories (kept for back-compat)."""
    xbmc.executebuiltin('Container.Update({})'.format(
        plugin.url_for(list_subcategories, url=URL_PUB_V2_CATS + '?limit=50')))


@plugin.route('/subcategories')
def list_subcategories():
    """Browse all categories using the public v2 API."""
    murl   = plugin.args.get('url', URL_PUB_V2_CATS + '?limit=50')
    jsdata = _pub_get(murl)
    for x in (jsdata.get('data') or []):
        cat_id = x.get('id', '')
        title  = x.get('name', '')
        thumb  = x.get('thumbnail') or ICON
        live_url = URL_PUB_LIVESTREAMS + '?category_id={}&limit=25'.format(cat_id)
        add_item(plugin.url_for(live, url=live_url), title, thumb, folder=True,
                 infoLabels={'title': title, 'plot': title})
    cursor = (jsdata.get('pagination') or {}).get('next_cursor')
    if cursor:
        parsed   = urlparse(murl)
        pdict    = parse_qs(parsed.query, keep_blank_values=True)
        pdict.pop('cursor', None)
        flat     = {k: v[0] for k, v in pdict.items()}
        flat['cursor'] = cursor
        next_url = parsed._replace(query=urlencode(flat)).geturl()
        add_item(plugin.url_for(list_subcategories, url=next_url),
                 str(language(30020)), NEXT_PAGE_IMG, folder=True)
    _end_dir()


@plugin.route('/live')
def live():
    """List currently live streams (public API)."""
    url    = plugin.args.get('url', URL_PUB_LIVESTREAMS + '?limit=25')
    jsdata = _pub_get(url)
    for x in (jsdata.get('data') or []):
        title_raw = clean_title(x.get('stream_title', ''))
        viewers   = x.get('viewer_count', 0)
        thumbnail = x.get('thumbnail') or ICON
        slug      = x.get('slug', '')
        pic       = x.get('profile_picture') or ICON
        label     = '[B]{}[/B] {} [{}]'.format(slug, title_raw, viewers)
        add_item(plugin.url_for(list_channel, slug=slug), label, thumbnail,
                 infoLabels={'title': label, 'plot': label},
                 icon=pic, folder=True)
    cursor = (jsdata.get('pagination') or {}).get('next_cursor')
    if cursor:
        sep      = '&' if '?' in url else '?'
        next_url = url.split('&cursor=')[0] + sep + 'cursor=' + quote_plus(cursor)
        add_item(plugin.url_for(live, url=next_url),
                 str(language(30020)), NEXT_PAGE_IMG, folder=True)
    _end_dir()


@plugin.route('/channel/<slug>')
def list_channel(slug):
    """Show channel page: live stream (if any), past VODs, and clips."""
    jsdata = _pub_get(URL_PUB_CHANNEL + '?slug=' + quote(slug, safe=''))
    ch     = (jsdata.get('data') or [{}])[0]

    pic         = ch.get('profile_picture') or ICON
    username    = ch.get('slug', slug)
    stream      = ch.get('stream') or {}

    if stream.get('is_live'):
        thumbnail = stream.get('thumbnail') or ICON
        title     = clean_title(ch.get('stream_title', '')) + LIVE_BADGE
        add_item(plugin.url_for(play_video, url=slug), title, thumbnail,
                 infoLabels={'title': title, 'plot': title},
                 IsPlayable=True)

    vods_label  = str(language(30024)) + username + '[/B]'
    clips_label = str(language(30025)) + username + '[/B]'
    add_item(plugin.url_for(list_vods, slug=slug),
             vods_label, pic,
             infoLabels={'title': vods_label, 'plot': vods_label},
             folder=True)
    add_item(plugin.url_for(list_clips, slug=slug),
             clips_label, pic,
             infoLabels={'title': clips_label, 'plot': clips_label},
             folder=True)
    _end_dir()


@plugin.route('/vods')
def list_vods():
    """List a channel's previous livestreams (VODs) via Worker proxy."""
    slug = plugin.args.get('slug', '')
    data = (_api_get(URL_PROXY_CHANNEL.format(slug=quote(slug, safe='')))
            .get('previous_livestreams') or [])
    for x in data:
        title_raw  = clean_title(x.get('session_title'))
        duration   = int(x.get('duration') or 0) // 1000
        thumbnail  = (x.get('thumbnail') or {}).get('src', ICON)
        created_at = x.get('created_at', '')
        uuid       = (x.get('video') or {}).get('uuid', '')
        if not uuid:
            continue
        title = '{} [I]({})[/I]'.format(title_raw, created_at)
        add_item(plugin.url_for(play_video, url=URL_PROXY_VIDEO.format(uuid=uuid)),
                 title, thumbnail,
                 infoLabels={'title': title, 'plot': title, 'duration': duration},
                 IsPlayable=True)
    _end_dir()


@plugin.route('/clips/<slug>')
def list_clips(slug):
    """List clips for the given channel slug via Worker proxy."""
    jsdata = _api_get(URL_PROXY_CLIPS.format(slug=quote(slug, safe='')))
    for x in (jsdata.get('clips') or []):
        title     = x.get('title', '')
        thumbnail = x.get('thumbnail_url') or ICON
        duration  = x.get('duration')
        href      = x.get('video_url', '')
        add_item(plugin.url_for(play_video, url=href), title, thumbnail,
                 infoLabels={'title': title, 'plot': title, 'duration': duration},
                 IsPlayable=True)
    _end_dir()


@plugin.route('/play_video')
def play_video():
    """Resolve and play a stream URL or channel slug via InputStream Adaptive (HLS)."""
    try:
        import inputstreamhelper
    except ImportError:
        xbmcgui.Dialog().notification('KICK.com', 'InputStream Helper not installed',
                                      xbmcgui.NOTIFICATION_ERROR, 5000)
        xbmcplugin.setResolvedUrl(plugin.handle, False, listitem=xbmcgui.ListItem())
        return
    stream = _resolve_stream(plugin.args.get('url', ''))
    if not stream:
        xbmcplugin.setResolvedUrl(plugin.handle, False, listitem=xbmcgui.ListItem())
        return
    hdz = {
        'Accept':     'application/x-mpegURL, application/vnd.apple.mpegurl, application/json, text/plain',
        'User-Agent': UA_STREAM,
    }
    hea = '&'.join('{}={}'.format(k, quote(str(v), safe='')) for k, v in hdz.items())
    is_helper = inputstreamhelper.Helper('hls')
    if not is_helper.check_inputstream():
        return
    play_item = xbmcgui.ListItem(path=stream + '|' + hea)
    _setup_inputstream(play_item, is_helper, hea)
    xbmcplugin.setResolvedUrl(plugin.handle, True, listitem=play_item)


def _resolve_stream(slug):
    """Resolve a slug/URL to a playable HLS stream URL, or None."""
    if slug.endswith('.mp4') or slug.endswith('.m3u8'):
        return slug
    if slug.startswith(WORKER_BASE):
        # Worker proxy for VOD: returns {"url": "..."}
        return _api_get(slug).get('url')
    if slug.startswith('http'):
        # Direct VOD / clip source URL
        data = _api_get(slug)
        return data.get('source') or data.get('url')
    # Channel slug: proxy the internal livestream endpoint via Worker
    return (_api_get(URL_PROXY_STREAM.format(slug=quote(slug, safe='')))
            .get('data') or {}).get('playback_url')


def _setup_inputstream(play_item, is_helper, hea):
    """Configure InputStream Adaptive properties on a ListItem."""
    askqual = addon.getSetting('askqual')
    play_item.setProperty('IsPlayable', 'true')
    play_item.setProperty('inputstream', is_helper.inputstream_addon)
    if askqual != 'false':
        play_item.setProperty('inputstream.adaptive.stream_selection_type', 'ask-quality')
    play_item.setProperty('inputstream.adaptive.manifest_type', 'hls')
    play_item.setMimeType('application/vnd.apple.mpegurl')
    play_item.setProperty('inputstream.adaptive.manifest_update_parameter', 'full')
    play_item.setProperty('inputstream.adaptive.manifest_headers', hea)


@plugin.route('/search')
def list_search():
    """Display search results (categories + exact channel match) for the given query."""
    query = plugin.args.get('q', '')

    # Exact channel slug match
    ch_data  = _pub_get(URL_PUB_CHANNEL + '?slug=' + quote(query, safe=''))
    channels = ch_data.get('data') or []
    for x in channels:
        slug  = x.get('slug', '')
        label = slug
        add_item(plugin.url_for(list_channel, slug=slug), label, ICON,
                 infoLabels={'title': label, 'plot': label},
                 folder=True)

    # Category search (deprecated v1 endpoint but still works)
    cat_data = _pub_get(URL_PUB_CATEGORIES + '?q=' + quote_plus(query))
    cats     = cat_data.get('data') or []
    for x in cats:
        cat_id = x.get('id', '')
        title  = x.get('name', '')
        thumb  = x.get('thumbnail') or ICON
        live_url = URL_PUB_LIVESTREAMS + '?category_id={}&limit=25'.format(cat_id)
        add_item(plugin.url_for(live, url=live_url), title, thumb,
                 infoLabels={'title': title, 'plot': title},
                 folder=True)

    _end_dir()
    if not (channels or cats):
        xbmcgui.Dialog().notification('[COLOR yellowgreen][B]Info[/B][/COLOR]',
                                      str(language(30029)),
                                      xbmcgui.NOTIFICATION_INFO, 5000, False)


# ---------------------------------------------------------------------------
# Routes — Actions (no directory listing)
# ---------------------------------------------------------------------------
@plugin.route('/search_dialog')
def search_dialog():
    """Open a keyboard dialog and navigate to search results for the entered query."""
    query = xbmcgui.Dialog().input(str(language(30038)), type=xbmcgui.INPUT_ALPHANUM)
    if query:
        xbmc.executebuiltin('Container.Update({})'.format(
            plugin.url_for(list_search, q=query)))


@plugin.route('/settings')
def settings():
    """Open the addon settings dialog."""
    addon.openSettings()


if __name__ == '__main__':
    try:
        plugin.run()
    except Exception as exc:
        import traceback
        xbmc.log('KICK: unhandled exception: ' + traceback.format_exc(), xbmc.LOGERROR)
        raise
