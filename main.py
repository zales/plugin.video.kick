# -*- coding: UTF-8 -*-
"""Kodi plugin for kick.com."""
import json
import sys
import functools
import unicodedata
from urllib.parse import quote, quote_plus, unquote_plus

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
API_BASE = 'https://kick.com'
API_V1   = API_BASE + '/api/v1'
API_V2   = API_BASE + '/api/v2'

# Public developer API (stable, needs Bearer token from client_credentials)
API_PUB    = 'https://api.kick.com/public/v1'
API_PUB_V2 = 'https://api.kick.com/public/v2'

# Cloudflare Worker base URL
WORKER_BASE = 'https://kodi.zales.dev'

URL_HOME           = API_BASE + '/'
URL_LIVESTREAMS    = API_BASE + '/stream/livestreams/{lang}?page=1'   # legacy, now proxied
URL_SUBCATEGORIES  = API_V1 + '/subcategories?page=1'                  # legacy, now proxied
URL_FOLLOWED       = API_V2 + '/channels/followed?cursor=0'
URL_TOP_CATEGORIES = API_V1 + '/user/categories/top'
URL_CHANNEL        = API_V1 + '/channels/{slug}'
URL_CHANNEL_FOLLOW = API_V2 + '/channels/{slug}/follow'
URL_SUBCAT_FOLLOW  = API_V1 + '/subcategories/{slug}/toggle-follow'
URL_LIVESTREAM     = API_V2 + '/channels/{slug}/livestream'
URL_CLIPS          = API_V2 + '/channels/{slug}/clips?cursor=0&sort=view&time=all'
URL_VIDEO          = API_V1 + '/video/{uuid}'
URL_SEARCH         = API_BASE + '/api/search?searched_word={query}'
URL_KICK_TOKEN     = API_BASE + '/kick-token-provider'
URL_LOGIN          = API_BASE + '/mobile/login'

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

# ---------------------------------------------------------------------------
# Kodi setup
# ---------------------------------------------------------------------------
plugin   = Plugin()
addon    = xbmcaddon.Addon(id=ADDON_ID)
language = addon.getLocalizedString

PATH          = addon.getAddonInfo('path')
RESOURCES     = PATH + '/resources/'
FANART        = RESOURCES + '../fanart.jpg'
ICON          = RESOURCES + '../icon.png'
NEXT_PAGE_IMG = RESOURCES + 'right.png'
askqual       = addon.getSetting('askqual')

# ---------------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------------
import requests
sessi = requests.Session()
sessi.headers.update({'User-Agent': UA, 'Accept': 'application/json'})


def _api_get(url):
    """GET url, return parsed JSON dict/list or {} on error."""
    try:
        r = sessi.get(url, timeout=15)
        xbmc.log('KICKCOMMB: GET {} → {}'.format(url[:120], r.status_code), xbmc.LOGINFO)
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        xbmc.log('KICKCOMMB: GET {} failed: {}'.format(url[:120], exc), xbmc.LOGERROR)
        return {}


_APP_TOKEN = ''


def _get_app_token():
    """Return a cached client_credentials Bearer token from the Worker."""
    global _APP_TOKEN
    if _APP_TOKEN:
        return _APP_TOKEN
    try:
        r = sessi.get(URL_APP_TOKEN, timeout=10)
        r.raise_for_status()
        _APP_TOKEN = r.json().get('token', '')
    except Exception as exc:
        xbmc.log('KICKCOMMB: app-token failed: {}'.format(exc), xbmc.LOGERROR)
    return _APP_TOKEN


def _pub_get(url):
    """GET a Kick public API URL with Bearer app token; return parsed JSON or {}."""
    token = _get_app_token()
    if not token:
        return {}
    try:
        r = sessi.get(url, timeout=15, headers={'Authorization': 'Bearer ' + token})
        xbmc.log('KICKCOMMB: PUB {} → {}'.format(url[:120], r.status_code), xbmc.LOGINFO)
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        xbmc.log('KICKCOMMB: PUB {} failed: {}'.format(url[:120], exc), xbmc.LOGERROR)
        return {}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
LIVE_BADGE = '     [B][COLOR yellowgreen]LIVE[/COLOR][/B]'

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


def title_with_viewers(title, viewers):
    """Return 'title [viewers]' label string."""
    return '{} [{}]'.format(title or '', viewers)


def apply_auth():
    """Load stored auth headers into the session. Returns True if present."""
    raw = addon.getSetting('auth_headers')
    if not raw:
        return False
    try:
        sessi.headers.update(json.loads(unquote_plus(raw)))
        return True
    except (ValueError, TypeError):
        return False


def auth_required(func):
    """Decorator: early-return if user is not authenticated."""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        if not apply_auth():
            return
        return func(*args, **kwargs)
    return wrapper


def _fetch_xsrf():
    """GET the home page to seed cookies, then apply XSRF token header."""
    try:
        sessi.get(URL_HOME, timeout=15)
    except Exception as exc:
        xbmc.log('KICKCOMMB: _fetch_xsrf failed: {}'.format(exc), xbmc.LOGWARNING)
        return
    xc = sessi.cookies.get_dict().get('XSRF-TOKEN')
    if xc:
        sessi.headers.update({'x-xsrf-token': xc})


def _auth_fail():
    """Mark auth as failed and refresh the container."""
    addon.setSetting('auth', '0')
    xbmc.executebuiltin('Container.Refresh()')


def follow_toggle(slug, follow):
    """Follow or unfollow a channel (follow=True) or category (slug starts with cat|)."""
    if not apply_auth():
        return
    slug = unquote_plus(slug)
    if 'cat|' in slug:
        url = URL_SUBCAT_FOLLOW.format(slug=quote(slug.split('|')[-1], safe=''))
        sessi.post(url, data={'follow': follow})
    else:
        url = URL_CHANNEL_FOLLOW.format(slug=quote(slug, safe=''))
        if follow:
            r = sessi.post(url)
            if r.status_code == 200:
                xbmcgui.Dialog().notification(
                    str(language(30021)), str(language(30022)),
                    xbmcgui.NOTIFICATION_INFO, 5000, False)
        else:
            sessi.delete(url)


def make_follow_menu(slug, following):
    """Return a Kodi context-menu list for follow/unfollow."""
    if following:
        return [(str(language(30019)),
                 'RunPlugin({})'.format(plugin.url_for(unfollow_action, slug=slug)))]
    return [(str(language(30023)),
             'RunPlugin({})'.format(plugin.url_for(follow_action, slug=slug)))]


def make_channel_menu(slug, name, img, following=None):
    """Context menu with Kodi favourites + optional follow/unfollow."""
    fav_url = plugin.url_for(list_channel, slug=slug)
    items = [
        ('Pridat do oblibenych',
         'RunPlugin({})'.format(plugin.url_for(add_favourite, slug=slug, name=name, img=img))),
    ]
    if following is True:
        items.append((str(language(30019)),
                      'RunPlugin({})'.format(plugin.url_for(unfollow_action, slug=slug))))
    elif following is False:
        items.append((str(language(30023)),
                      'RunPlugin({})'.format(plugin.url_for(follow_action, slug=slug))))
    return items


def add_header(text):
    """Non-clickable section label."""
    li = xbmcgui.ListItem(label=text)
    li.setInfo(type='video', infoLabels={'title': text})
    xbmcplugin.addDirectoryItem(handle=plugin.handle, url='', listitem=li, isFolder=False)


def add_item(url, name, image, fanart=FANART, infoLabels=None,
             contextmenu=None, IsPlayable=False, folder=False):
    """Create a ListItem and add it to the current directory listing."""
    li = xbmcgui.ListItem(label=name)
    if IsPlayable:
        li.setProperty('IsPlayable', 'True')
    li.setInfo(type='video', infoLabels=infoLabels or {'title': name})
    li.setArt({'thumb': image, 'poster': image, 'banner': image, 'fanart': fanart})
    if contextmenu:
        li.addContextMenuItems(contextmenu, replaceItems=True)
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
        base   = murl.split('?')[0]
        params = murl.split('?')[1] if '?' in murl else ''
        pdict  = dict(p.split('=', 1) for p in params.split('&') if '=' in p)
        pdict.pop('cursor', None)
        next_url = base + '?' + '&'.join('{}={}'.format(k, v) for k, v in pdict.items()) + '&cursor=' + quote_plus(cursor)
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
                 contextmenu=make_channel_menu(slug, slug, pic),
                 folder=True)
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

    pic         = ICON
    username    = ch.get('slug', slug)
    contextmenu = make_channel_menu(slug, username, pic)
    stream      = ch.get('stream') or {}

    if stream.get('is_live'):
        thumbnail = stream.get('thumbnail') or ICON
        title     = clean_title(ch.get('stream_title', '')) + LIVE_BADGE
        add_item(plugin.url_for(play_video, url=slug), title, thumbnail,
                 infoLabels={'title': title, 'plot': title},
                 contextmenu=contextmenu, IsPlayable=True)

    vods_label  = str(language(30024)) + username + '[/B]'
    clips_label = str(language(30025)) + username + '[/B]'
    add_item(plugin.url_for(list_vods, slug=slug),
             vods_label, pic,
             infoLabels={'title': vods_label, 'plot': vods_label},
             contextmenu=contextmenu, folder=True)
    add_item(plugin.url_for(list_clips, slug=slug),
             clips_label, pic,
             infoLabels={'title': clips_label, 'plot': clips_label},
             contextmenu=contextmenu, folder=True)
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
        add_item(plugin.url_for(play_video, url=URL_VIDEO.format(uuid=uuid)),
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
    if slug.startswith('http') and not slug.endswith('.mp4') and not slug.endswith('.m3u8'):
        return _api_get(slug).get('source')
    # Slug: proxy the internal kick.com livestream endpoint via Worker
    return (_api_get(URL_PROXY_STREAM.format(slug=quote(slug, safe='')))
            .get('data') or {}).get('playback_url')


def _setup_inputstream(play_item, is_helper, hea):
    """Configure InputStream Adaptive properties on a ListItem."""
    play_item.setProperty('IsPlayable', 'true')
    play_item.setProperty('inputstream', is_helper.inputstream_addon)
    if askqual != 'false':
        play_item.setProperty('inputstream.adaptive.stream_selection_type', 'ask-quality')
    play_item.setProperty('inputstream.adaptive.manifest_type', 'hls')
    play_item.setMimeType('application/vnd.apple.mpegurl')
    play_item.setProperty('inputstream.adaptive.manifest_update_parameter', 'full')
    play_item.setProperty('inputstream.adaptive.manifest_headers', hea)


@plugin.route('/add_favourite')
def add_favourite():
    """Add a channel to Kodi's built-in favourites list."""
    slug = plugin.args.get('slug', '')
    name = plugin.args.get('name', slug)
    img  = plugin.args.get('img', ICON)
    if not slug:
        return
    fav_url = plugin.url_for(list_channel, slug=slug)
    xbmc.executebuiltin('AddFavourite({},{},{},{})'.format(
        fav_url, 'window', name, img))
    xbmcgui.Dialog().notification(
        'KICK.com',
        '{} pridano do oblibenych'.format(name),
        xbmcgui.NOTIFICATION_INFO, 3000, False)


@plugin.route('/login_menu')
def login_menu():
    """Show a dialog to choose login method: email/password or Google."""
    methods = [str(language(30045)), str(language(30044))]
    sel = xbmcgui.Dialog().select(str(language(30001)), methods)
    if sel == 0:
        login()
    elif sel == 1:
        google_login()


@plugin.route('/login')
def login():
    """Authenticate with kick.com using stored credentials; handles 2FA if required."""
    username_ = addon.getSetting('username')
    password_ = addon.getSetting('password')
    if not (username_ and password_):
        addon.openSettings()
        return

    _fetch_xsrf()
    tok_data = _api_get(URL_KICK_TOKEN)
    payload  = {
        'email':           username_,
        'password':        password_,
        'isMobileRequest': True,
        tok_data.get('nameFieldName', ''):      '',
        tok_data.get('validFromFieldName', ''): tok_data.get('encryptedValidFrom'),
    }

    response = sessi.post(URL_LOGIN, json=payload, headers=sessi.headers)
    if response.status_code != 200:
        _auth_fail()
        return

    r = response
    if '"2fa_required":true' in response.text:
        code = xbmcgui.Dialog().input(str(language(30026)), type=xbmcgui.INPUT_NUMERIC)
        if not code:
            _auth_fail()
            return
        payload['one_time_password'] = code
        r = sessi.post(URL_LOGIN, json=payload)

    auth = r.json().get('token')
    if not auth:
        _auth_fail()
        return

    sessi.headers.update({'authorization': 'Bearer ' + auth})
    addon.setSetting('auth_headers', quote_plus(json.dumps(dict(sessi.headers))))
    addon.setSetting('auth', '1')
    xbmcgui.Dialog().notification('[COLOR yellowgreen][B]OK[/B][/COLOR]',
                                  str(language(30027)),
                                  xbmcgui.NOTIFICATION_INFO, 5000, False)
    xbmc.executebuiltin('Container.Refresh')


# ---------------------------------------------------------------------------
# QR-code login dialog
# ---------------------------------------------------------------------------

class _QRLoginDialog(xbmcgui.WindowDialog):
    """Full-screen overlay showing a QR code + URL.  Polls for the auth token."""

    ACTION_BACK = 92
    ACTION_NAV_BACK = 9
    ACTION_ESCAPE = 10

    def __init__(self, img_path, url):
        super().__init__()
        self.cancelled = False
        self._img_path = img_path
        self._url = url
        self._build_ui()

    def _build_ui(self):
        sw = self.getWidth()
        sh = self.getHeight()
        qr_size = min(sw, sh, 500) // 2
        x = (sw - qr_size) // 2
        y = (sh - qr_size) // 2 - 50

        qr_ctrl = xbmcgui.ControlImage(x, y, qr_size, qr_size, self._img_path)
        self.addControl(qr_ctrl)

        url_lbl = xbmcgui.ControlLabel(
            0, y + qr_size + 16, sw, 46,
            '[B]{}[/B]'.format(self._url),
            textColor='0xFFFFFFFF',
            alignment=0x00000002,  # XBFONT_CENTER_X
        )
        self.addControl(url_lbl)

        hint = xbmcgui.ControlLabel(
            0, y + qr_size + 62, sw, 34,
            'Naskenujte QR telefonem  —  Back = zrusit',
            textColor='0xFF888888',
            alignment=0x00000002,
        )
        self.addControl(hint)

    def onAction(self, action):
        if action.getId() in (self.ACTION_BACK, self.ACTION_NAV_BACK, self.ACTION_ESCAPE):
            self.cancelled = True
            self.close()


@plugin.route('/google_login')
def google_login():
    """KV relay auth: show QR → user opens kodi.zales.dev/connect/ID on phone → runs script on kick.com."""
    import os
    import uuid
    from resources.lib import auth_server

    RELAY_BASE = 'https://kodi.zales.dev'
    session_id = uuid.uuid4().hex
    connect_url = '{}/connect/{}'.format(RELAY_BASE, session_id)
    poll_url    = '{}/token/{}'.format(RELAY_BASE, session_id)

    # Try to open browser automatically (Kodi 20+)
    try:
        xbmc.openBrowserWindow(connect_url)
    except AttributeError:
        pass

    # QR code image
    qr_path = None
    try:
        qr_path = auth_server.get_qr_image(connect_url)
    except Exception:
        pass

    token = None

    def _poll_relay(timeout_secs=300):
        """Poll kodi.zales.dev/token/:id until token arrives or timeout."""
        import requests as _req
        for _ in range(timeout_secs):
            xbmc.sleep(1000)
            try:
                r = _req.get(poll_url, timeout=5)
                if r.status_code == 200:
                    return r.json().get('token')
            except Exception:
                pass
        return None

    if qr_path:
        dlg = _QRLoginDialog(qr_path, connect_url)

        import threading
        result_box = [None]

        def _bg():
            result_box[0] = _poll_relay()
            dlg.close()

        threading.Thread(target=_bg, daemon=True).start()
        dlg.doModal()
        token = result_box[0]
        del dlg
        try:
            os.remove(qr_path)
        except Exception:
            pass
    else:
        # Fallback: text progress dialog
        progress = xbmcgui.DialogProgress()
        msg = '{}\n[B]{}[/B]\n\n{}'.format(
            str(language(30042)), connect_url, str(language(30046)))
        progress.create('KICK.com — Google Login', msg)
        timeout_secs = 300
        elapsed = 0
        while elapsed < timeout_secs:
            if progress.iscanceled():
                break
            try:
                import requests as _req
                r = _req.get(poll_url, timeout=5)
                if r.status_code == 200:
                    token = r.json().get('token')
                    break
            except Exception:
                pass
            xbmc.sleep(1000)
            elapsed += 1
            progress.update(int(elapsed / timeout_secs * 100), msg)
        progress.close()

    if not token:
        xbmcgui.Dialog().notification(
            'KICK.com', str(language(30043)),
            xbmcgui.NOTIFICATION_ERROR, 5000)
        return

    sessi.headers.update({'authorization': 'Bearer ' + token})
    addon.setSetting('auth_headers', quote_plus(json.dumps(dict(sessi.headers))))
    addon.setSetting('auth', '1')
    xbmcgui.Dialog().notification(
        '[COLOR yellowgreen][B]OK[/B][/COLOR]',
        str(language(30027)),
        xbmcgui.NOTIFICATION_INFO, 5000, False)
    xbmc.executebuiltin('Container.Refresh')


@plugin.route('/followed')
@auth_required
def list_followed():
    """List channels and categories the authenticated user follows."""
    lang_val = addon.getSetting('lang')

    raw = _api_get(URL_FOLLOWED)
    # Internal API returns {"channels": [...]}, but requires session token (email/password login)
    # Developer OAuth token from id.kick.com returns 401 here
    channels = raw.get('channels') or raw.get('data') or []
    if not channels and not raw:
        # 401 = OAuth token not accepted by internal API
        xbmc.log('KICKCOMMB: followed channels unavailable — OAuth token rejected by internal API', xbmc.LOGWARNING)
    add_header(str(language(30015)))
    for x in channels:
        # Internal API: channel_slug, user_username, profile_picture, is_live
        # Developer API: slug, broadcaster_user_id, stream.is_live (different structure)
        is_live  = x.get('is_live') or bool((x.get('stream') or {}).get('is_live'))
        pic      = x.get('profile_picture') or ICON
        slug     = x.get('channel_slug') or x.get('slug', '')
        username = x.get('user_username') or x.get('slug') or ''
        title    = username + (LIVE_BADGE if is_live else '')
        add_item(plugin.url_for(list_channel, slug=slug), title, pic,
                 infoLabels={'title': title, 'plot': title},
                 contextmenu=make_follow_menu(slug, True),
                 folder=True)
    if not channels:
        add_header('[COLOR orange]Sledovane kanaly vyzaduji prihlaseni emailem a heslem[/COLOR]')

    categories = _api_get(URL_TOP_CATEGORIES)
    # URL_TOP_CATEGORIES also returns 401 with OAuth token — skip categories in that case
    if isinstance(categories, list) and categories:
        add_header(str(language(30016)))
        for x in categories:
            slug    = x.get('slug', '')
            title   = x.get('name', '')
            viewers = x.get('viewers')
            label   = title_with_viewers(title, viewers)
            live_url = URL_PUB_LIVESTREAMS + '?category_id={}&limit=25'.format(slug)
            add_item(plugin.url_for(live, url=live_url), label, ICON,
                     infoLabels={'title': label, 'plot': label},
                     contextmenu=make_follow_menu('cat|' + slug, True),
                     folder=True)
    else:
        add_header(str(language(30018)))
    _end_dir()


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


@plugin.route('/follow')
def follow_action():
    """Context-menu action: follow a channel or category."""
    follow_toggle(plugin.args.get('slug', ''), True)
    xbmc.executebuiltin('Container.Refresh()')


@plugin.route('/unfollow')
def unfollow_action():
    """Context-menu action: unfollow a channel or category."""
    follow_toggle(plugin.args.get('slug', ''), False)
    xbmc.executebuiltin('Container.Refresh()')


@plugin.route('/logout')
def logout():
    """Ask for confirmation and clear stored auth credentials."""
    yes = xbmcgui.Dialog().yesno(str(language(30031)), str(language(30030)),
                                 yeslabel=str(language(30032)),
                                 nolabel=str(language(30033)))
    if yes:
        addon.setSetting('auth', '0')
        addon.setSetting('auth_headers', '')
        xbmc.executebuiltin('Container.Refresh()')


if __name__ == '__main__':
    try:
        plugin.run()
    except Exception as exc:
        import traceback
        xbmc.log('KICKCOMMB: unhandled exception: ' + traceback.format_exc(), xbmc.LOGERROR)
        raise
