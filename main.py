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

URL_HOME           = API_BASE + '/'
URL_LIVESTREAMS    = API_BASE + '/stream/livestreams/{lang}?page=1'
URL_SUBCATEGORIES  = API_V1 + '/subcategories?page=1'
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
_lib_path = addon.getAddonInfo('path') + '/resources/lib'
if _lib_path not in sys.path:
    sys.path.insert(0, _lib_path)

try:
    import cloudscraper
    sessi = cloudscraper.create_scraper(browser={'browser': 'chrome', 'platform': 'android', 'desktop': False})
except Exception as _e:
    xbmc.log('KICKCOMMB: cloudscraper failed ({}), falling back to requests'.format(_e), xbmc.LOGWARNING)
    import requests
    sessi = requests.Session()
    sessi.headers.update({'User-Agent': UA})


def _api_get(url):
    """GET url, return parsed JSON dict/list or {} on error."""
    try:
        r = sessi.get(url, timeout=15)
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        xbmc.log('KICKCOMMB: GET {} failed: {}'.format(url[:120], exc), xbmc.LOGERROR)
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
    """Main menu: language picker, login/followed, live, categories, search, settings."""
    lang_val  = addon.getSetting('lang')
    lang_lab  = addon.getSetting('lang_lab')
    logged_in = addon.getSetting('auth') == '1'

    add_item(plugin.url_for(select_language),
             '{}: {}'.format(str(language(30000)), lang_lab), ICON)
    if logged_in:
        add_item(plugin.url_for(list_followed),
                 str(language(30002)), ICON, folder=True)
    else:
        add_item(plugin.url_for(login), str(language(30001)), ICON)
        add_item(plugin.url_for(google_login), str(language(30044)), ICON)
    add_item(plugin.url_for(live, url=URL_LIVESTREAMS.format(lang=lang_val)),
             str(language(30003)), ICON, folder=True)
    add_item(plugin.url_for(list_categories), str(language(30004)), ICON, folder=True)
    add_item(plugin.url_for(search_dialog),     str(language(30005)), ICON)
    add_item(plugin.url_for(settings),   str(language(30041)), ICON)
    if logged_in:
        add_item(plugin.url_for(logout), str(language(30006)), ICON)
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
    """List top-level content categories (Games, IRL, Music, …)."""
    categories = [
        ('games',       30007),
        ('irl',         30008),
        ('music',       30009),
        ('gambling',    30010),
        ('creative',    30011),
        ('alternative', 30012),
    ]
    for slug, str_id in categories:
        add_item(plugin.url_for(list_subcategories, url='{}|{}'.format(slug, URL_SUBCATEGORIES)),
                 str(language(str_id)), ICON, folder=True)
    _end_dir()


@plugin.route('/subcategories')
def list_subcategories():
    """List subcategories for a given category slug, with pagination."""
    lang_val = addon.getSetting('lang')
    mainurl  = plugin.args.get('url', '')
    tt, murl = mainurl.split('|', 1)
    jsdata   = _api_get(murl + '&limit=20&category=' + quote_plus(tt))
    for x in (jsdata.get('data') or []):
        title       = x.get('name', '')
        slug        = x.get('slug', '')
        description = x.get('description') or ''
        viewers     = x.get('viewers')
        label       = title_with_viewers(title, viewers)
        live_url    = '{}|{}'.format(slug, URL_LIVESTREAMS.format(lang=lang_val))
        add_item(plugin.url_for(live, url=live_url), label, ICON, folder=True,
                 infoLabels={'title': label, 'plot': description or label},
                 contextmenu=make_follow_menu('cat|' + slug, False))
    if jsdata.get('next_page_url'):
        add_item(plugin.url_for(list_subcategories, url='{}|{}'.format(tt, jsdata['next_page_url'])),
                 str(language(30020)), NEXT_PAGE_IMG, folder=True)
    _end_dir()


@plugin.route('/live')
def live():
    """List currently live streams, optionally filtered by subcategory slug."""
    urlmain = plugin.args.get('url', '')
    tt = ''
    if '|' in urlmain:
        tt, urlmain = urlmain.split('|', 1)
    url    = urlmain + '&limit=25&subcategory={}&sort={}'.format(
        quote_plus(tt), 'desc' if tt else 'featured')
    jsdata = _api_get(url)
    for x in (jsdata.get('data') or []):
        title_raw = clean_title(x.get('session_title'))
        viewers   = x.get('viewers')
        thumbnail = (x.get('thumbnail') or {}).get('src', ICON)
        slug      = (x.get('channel') or {}).get('slug', '')
        label     = '[B]{}[/B] {} [{}]'.format(slug, title_raw, viewers)
        add_item(plugin.url_for(list_channel, slug=slug), label, thumbnail,
                 infoLabels={'title': label, 'plot': label}, folder=True)
    if jsdata.get('next_page_url'):
        next_raw = jsdata['next_page_url']
        nturl = '{}|{}'.format(tt, next_raw) if tt else next_raw
        add_item(plugin.url_for(live, url=nturl),
                 str(language(30020)), NEXT_PAGE_IMG, folder=True)
    _end_dir()


@plugin.route('/channel/<slug>')
def list_channel(slug):
    """Show channel page: live stream (if any), past VODs, and clips."""
    auth_ok     = apply_auth()
    jsdata      = _api_get(URL_CHANNEL.format(slug=quote(slug, safe='')))
    following   = jsdata.get('following') if auth_ok else None
    contextmenu = make_follow_menu(slug, bool(following)) if auth_ok else []

    user       = jsdata.get('user') or {}
    pic        = user.get('profile_pic', ICON)
    username   = user.get('username', '')
    livestream = jsdata.get('livestream')

    if livestream:
        thumbnail = (livestream.get('thumbnail') or {}).get('url', ICON)
        title     = clean_title(livestream.get('session_title')) + LIVE_BADGE
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
    """List a channel's previous livestreams (VODs) fetched by channel slug."""
    slug = plugin.args.get('slug', '')
    data = (_api_get(URL_CHANNEL.format(slug=quote(slug, safe='')))
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
    """List clips for the given channel slug, sorted by views (all time)."""
    jsdata = _api_get(URL_CLIPS.format(slug=quote(slug, safe='')))
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
    """Resolve a slug/URL to a playable stream URL, or None."""
    if slug.startswith('http') and not (slug.endswith('.mp4') or slug.endswith('.m3u8')):
        return _api_get(slug).get('source')
    if slug.endswith('.mp4') or slug.endswith('.m3u8'):
        return slug
    return (_api_get(URL_LIVESTREAM.format(slug=quote(slug, safe='')))
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


@plugin.route('/google_login')
def google_login():
    """Open a local browser page that guides the user through Google OAuth on kick.com."""
    from resources.lib import auth_server

    port = auth_server.start()
    local_url = 'http://localhost:{}'.format(port)

    # Try to open the browser automatically (Kodi 20+)
    try:
        xbmc.openBrowserWindow(local_url)
    except AttributeError:
        pass  # Kodi < 20 — user will open it manually

    progress = xbmcgui.DialogProgress()
    progress.create(
        'KICK.com — Google Login',
        '{}\n\n{}'.format(str(language(30042)), local_url),
    )

    timeout_secs = 300  # 5 minutes
    elapsed = 0
    token = None
    while elapsed < timeout_secs:
        if progress.iscanceled():
            break
        token = auth_server.get_token()
        if token:
            break
        xbmc.sleep(1000)
        elapsed += 1
        progress.update(
            int(elapsed / timeout_secs * 100),
            '{}\n\n{}'.format(str(language(30042)), local_url),
        )

    progress.close()
    auth_server.stop()

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

    channels = _api_get(URL_FOLLOWED).get('channels') or []
    add_header(str(language(30015)))
    for x in channels:
        is_live  = x.get('is_live')
        pic      = x.get('profile_picture') or ICON
        slug     = x.get('channel_slug', '')
        username = x.get('user_username') or ''
        title    = username + (LIVE_BADGE if is_live else '')
        add_item(plugin.url_for(list_channel, slug=slug), title, pic,
                 infoLabels={'title': title, 'plot': title},
                 contextmenu=make_follow_menu(slug, True),
                 folder=True)
    if not channels:
        add_header(str(language(30017)))

    categories = _api_get(URL_TOP_CATEGORIES)
    if isinstance(categories, list) and categories:
        add_header(str(language(30016)))
        for x in categories:
            slug    = x.get('slug', '')
            title   = x.get('name', '')
            viewers = x.get('viewers')
            label   = title_with_viewers(title, viewers)
            live_url = '{}|{}'.format(slug, URL_LIVESTREAMS.format(lang=lang_val))
            add_item(plugin.url_for(live, url=live_url), label, ICON,
                     infoLabels={'title': label, 'plot': label},
                     contextmenu=make_follow_menu('cat|' + slug, True),
                     folder=True)
    else:
        add_header(str(language(30018)))
    _end_dir()


@plugin.route('/search')
def list_search():
    """Display search results (channels and categories) for the given query."""
    lang_val = addon.getSetting('lang')
    query    = plugin.args.get('q', '')

    data      = _api_get(URL_SEARCH.format(query=quote_plus(query)))
    channels  = data.get('channels') or []
    cats      = data.get('categories') or []

    for x in channels:
        slug     = x.get('slug', '')
        user     = x.get('user') or {}
        username = user.get('username', '')
        pic      = user.get('profilePic') or ICON
        bio = user.get('bio') or ''
        bio = clean_title(bio).replace('\n', '[CR]')
        add_item(plugin.url_for(list_channel, slug=slug), username, pic,
                 infoLabels={'title': username, 'plot': bio or username},
                 folder=True)

    for x in cats:
        title       = x.get('name', '')
        slug        = x.get('slug', '')
        description = x.get('description') or ''
        viewers     = x.get('viewers')
        label       = title_with_viewers(title, viewers)
        live_url    = '{}|{}'.format(slug, URL_LIVESTREAMS.format(lang=lang_val))
        add_item(plugin.url_for(live, url=live_url), label, ICON,
                 infoLabels={'title': label, 'plot': description or label},
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
