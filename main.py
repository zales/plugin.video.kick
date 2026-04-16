# -*- coding: UTF-8 -*-
"""Kodi plugin for kick.com."""
import os
import traceback
from urllib.parse import quote, quote_plus

import xbmcgui
import xbmcplugin
import xbmcaddon
import xbmcvfs
import xbmc

from resources.lib.routing import Plugin
from resources.lib.http import (
    UA_STREAM, WORKER_BASE,
    api_get, pub_get, pub_get_ex, OK, EMPTY, ERROR,
)
from resources.lib import utils

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
ADDON_ID = 'plugin.video.kick'

# Public developer API (stable, needs Bearer token from client_credentials)
API_PUB    = 'https://api.kick.com/public/v1'
API_PUB_V2 = 'https://api.kick.com/public/v2'

# Public API endpoints
URL_PUB_LIVESTREAMS = API_PUB + '/livestreams'
URL_PUB_CHANNEL     = API_PUB + '/channels'
URL_PUB_CATEGORIES  = API_PUB + '/categories'
URL_PUB_V2_CATS     = API_PUB_V2 + '/categories'

# Worker endpoints
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
ICON          = os.path.join(PATH, 'icon.png')
NEXT_PAGE_IMG = os.path.join(PATH, 'resources', 'right.png')
PROFILE       = xbmcvfs.translatePath(addon.getAddonInfo('profile'))
FOLLOWED_FILE = os.path.join(PROFILE, 'followed.json')


def _load_followed():
    return utils.load_followed(FOLLOWED_FILE)


def _save_followed(data):
    utils.save_followed(PROFILE, FOLLOWED_FILE, data)


clean_title = utils.clean_title
_next_page_url = utils.next_page_url

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
LIVE_BADGE = ' · [B][COLOR yellowgreen]LIVE[/COLOR][/B]'


def _notify(msg, icon=xbmcgui.NOTIFICATION_INFO, ms=3000):
    xbmcgui.Dialog().notification('KICK.com', msg, icon, ms, False)


def _notify_loc(strid, icon=xbmcgui.NOTIFICATION_INFO, ms=3000):
    _notify(str(language(strid)), icon, ms)


def add_item(url, name, image, infoLabels=None, IsPlayable=False, folder=False, icon=None, context_items=None):
    """Create a ListItem and add it to the current directory listing."""
    li  = xbmcgui.ListItem(label=name)
    if IsPlayable:
        li.setProperty('IsPlayable', 'True')
    li.setArt({'thumb': image, 'poster': image, 'banner': image, 'icon': icon or image})
    info = infoLabels or {}
    tag  = li.getVideoInfoTag()
    tag.setTitle(info.get('title', name))
    tag.setPlot(info.get('plot', ''))
    if 'duration' in info:
        tag.setDuration(int(info['duration'] or 0))
    if context_items:
        li.addContextMenuItems(context_items)
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
    """Main menu: followed, live, categories, search, settings."""
    add_item(plugin.url_for(list_followed),
             str(language(30048)), ICON, folder=True)
    add_item(plugin.url_for(live),
             str(language(30003)), ICON, folder=True)
    add_item(plugin.url_for(list_subcategories, url=URL_PUB_V2_CATS + '?limit=50'),
             str(language(30004)), ICON, folder=True)
    add_item(plugin.url_for(search_dialog),     str(language(30005)), ICON)
    add_item(plugin.url_for(settings),   str(language(30041)), ICON)
    _end_dir()


@plugin.route('/subcategories')
def list_subcategories():
    """Browse all categories using the public v2 API."""
    murl   = plugin.args.get('url', URL_PUB_V2_CATS + '?limit=50')
    status, jsdata = pub_get_ex(murl)
    if status == ERROR:
        _notify_loc(30105, xbmcgui.NOTIFICATION_ERROR, 4000)
        _end_dir()
        return
    for x in (jsdata.get('data') or []):
        cat_id = x.get('id', '')
        title  = x.get('name', '')
        thumb  = x.get('thumbnail') or ICON
        live_url = URL_PUB_LIVESTREAMS + '?category_id={}&limit=100'.format(cat_id)
        add_item(plugin.url_for(live, url=live_url), title, thumb, folder=True,
                 infoLabels={'title': title, 'plot': title})
    cursor = (jsdata.get('pagination') or {}).get('next_cursor')
    if cursor:
        add_item(plugin.url_for(list_subcategories, url=_next_page_url(murl, cursor)),
                 str(language(30020)), NEXT_PAGE_IMG, folder=True)
    _end_dir()


@plugin.route('/followed')
def list_followed():
    """List channels the user is following, with live status."""
    followed = _load_followed()
    if not followed:
        _notify_loc(30053)
        _end_dir()
        return

    # Fetch live status for all followed slugs in one API call
    slugs_qs = '&'.join('slug=' + quote(s, safe='') for s in followed)
    live_data = pub_get(URL_PUB_CHANNEL + '?' + slugs_qs)
    live_map  = {}
    for ch in (live_data.get('data') or []):
        s = ch.get('slug', '')
        stream = ch.get('stream') or {}
        live_map[s] = {
            'is_live':   stream.get('is_live', False),
            'thumbnail': stream.get('thumbnail'),
            'pic':       ch.get('profile_picture'),
        }

    for slug, info in followed.items():
        name    = info.get('name', slug)
        lm      = live_map.get(slug, {})
        is_live = lm.get('is_live', False)
        pic     = lm.get('pic') or info.get('pic', ICON)
        thumb   = (lm.get('thumbnail') or pic) if is_live else pic
        label   = name + (LIVE_BADGE if is_live else '')
        # Always Unfollow here — entry exists because slug is followed
        ctx = [(str(language(30050)),
                'RunPlugin({})'.format(
                    plugin.url_for(toggle_follow, slug=slug, name=name, pic=pic)))]
        add_item(plugin.url_for(list_channel, slug=slug), label, thumb,
                 infoLabels={'title': label, 'plot': label},
                 icon=pic, folder=True, context_items=ctx)
    _end_dir()


@plugin.route('/follow/<slug>')
def toggle_follow(slug):
    """Toggle follow state for a channel slug."""
    followed = _load_followed()
    if slug in followed:
        del followed[slug]
        _save_followed(followed)
        _notify_loc(30052, ms=2000)
    else:
        name = plugin.args.get('name', slug)
        pic  = plugin.args.get('pic', ICON)
        followed[slug] = {'slug': slug, 'name': name, 'pic': pic}
        _save_followed(followed)
        _notify_loc(30051, ms=2000)
    xbmc.executebuiltin('Container.Refresh')


@plugin.route('/live')
def live():
    """List currently live streams (public API)."""
    # Read lang setting fresh every time so changes take effect immediately
    url = plugin.args.get('url')
    if not url:
        lang_val = addon.getSetting('lang') or 'all'
        qs = 'limit=100' + ('' if lang_val == 'all' else '&language=' + lang_val)
        url = URL_PUB_LIVESTREAMS + '?' + qs
    status, jsdata = pub_get_ex(url)
    if status == ERROR:
        _notify_loc(30105, xbmcgui.NOTIFICATION_ERROR, 4000)
        _end_dir()
        return
    followed = _load_followed()
    for x in (jsdata.get('data') or []):
        title_raw = clean_title(x.get('stream_title', ''))
        viewers   = x.get('viewer_count', 0)
        thumbnail = x.get('thumbnail') or ICON
        slug      = x.get('slug', '')
        pic       = x.get('profile_picture') or ICON
        label     = '[B]{}[/B] {} [{}]'.format(slug, title_raw, viewers)
        plot      = '[B]{}[/B] {}'.format(slug, title_raw)
        follow_label = str(language(30050 if slug in followed else 30049))
        ctx = [(follow_label, 'RunPlugin({})'.format(
                plugin.url_for(toggle_follow, slug=slug, name=slug, pic=pic)))]
        add_item(plugin.url_for(list_channel, slug=slug), label, thumbnail,
                 infoLabels={'title': plot, 'plot': plot},
                 icon=pic, folder=True, context_items=ctx)
    cursor = (jsdata.get('pagination') or {}).get('next_cursor')
    if cursor:
        add_item(plugin.url_for(live, url=_next_page_url(url, cursor)),
                 str(language(30020)), NEXT_PAGE_IMG, folder=True)
    _end_dir()


@plugin.route('/channel/<slug>')
def list_channel(slug):
    """Show channel page: live stream (if any), past VODs, and clips."""
    status, jsdata = pub_get_ex(URL_PUB_CHANNEL + '?slug=' + quote(slug, safe=''))
    if status == ERROR:
        _notify_loc(30105, xbmcgui.NOTIFICATION_ERROR, 4000)
        _end_dir()
        return
    ch     = (jsdata.get('data') or [{}])[0]

    if not ch:
        _notify(str(language(30042)).format(slug),
                xbmcgui.NOTIFICATION_ERROR, 4000)
        _end_dir()
        return

    pic         = ch.get('profile_picture') or ICON
    username    = ch.get('slug', slug)
    stream      = ch.get('stream') or {}

    followed = _load_followed()
    follow_label = str(language(30050 if slug in followed else 30049))
    follow_ctx = [(follow_label, 'RunPlugin({})'.format(
            plugin.url_for(toggle_follow, slug=slug, name=username, pic=pic)))]

    if stream.get('is_live'):
        thumbnail = stream.get('thumbnail') or ICON
        title     = clean_title(ch.get('stream_title', '')) + LIVE_BADGE
        add_item(plugin.url_for(play_video, url=slug), title, thumbnail,
                 infoLabels={'title': title, 'plot': title},
                 IsPlayable=True, context_items=follow_ctx)

    vods_label  = str(language(30024)) + username + '[/B]'
    clips_label = str(language(30025)) + username + '[/B]'
    add_item(plugin.url_for(list_vods, slug=slug),
             vods_label, pic,
             infoLabels={'title': vods_label, 'plot': vods_label},
             folder=True, context_items=follow_ctx)
    add_item(plugin.url_for(list_clips, slug=slug),
             clips_label, pic,
             infoLabels={'title': clips_label, 'plot': clips_label},
             folder=True, context_items=follow_ctx)
    _end_dir()


@plugin.route('/vods/<slug>')
def list_vods(slug):
    """List a channel's previous livestreams (VODs) via Worker proxy."""
    data = api_get(URL_PROXY_CHANNEL.format(slug=quote(slug, safe='')))
    vods = data.get('previous_livestreams') or []
    for x in vods:
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
    if not vods:
        _notify_loc(30043)
    _end_dir()


@plugin.route('/clips/<slug>')
def list_clips(slug):
    """List clips for the given channel slug via Worker proxy."""
    jsdata = api_get(URL_PROXY_CLIPS.format(slug=quote(slug, safe='')))
    clips = jsdata.get('clips') or []
    for x in clips:
        title     = x.get('title', '')
        thumbnail = x.get('thumbnail_url') or ICON
        duration  = x.get('duration') or 0
        href      = x.get('video_url', '')
        add_item(plugin.url_for(play_video, url=href), title, thumbnail,
                 infoLabels={'title': title, 'plot': title, 'duration': duration},
                 IsPlayable=True)
    if not clips:
        _notify_loc(30044)
    _end_dir()


@plugin.route('/play_video')
def play_video():
    """Resolve and play a stream URL or channel slug via InputStream Adaptive (HLS)."""
    try:
        import inputstreamhelper
    except ImportError:
        _notify_loc(30046, xbmcgui.NOTIFICATION_ERROR, 5000)
        xbmcplugin.setResolvedUrl(plugin.handle, False, listitem=xbmcgui.ListItem())
        return
    raw_url = plugin.args.get('url', '')
    stream = _resolve_stream(raw_url)
    if not stream:
        _notify_loc(30045, xbmcgui.NOTIFICATION_ERROR, 5000)
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

    # Chat overlay — only for live channel slugs (not VOD/clip URLs)
    is_live = raw_url and not raw_url.startswith('http') and \
              not raw_url.endswith('.mp4') and not raw_url.endswith('.m3u8')
    if is_live and addon.getSetting('chat') == 'true':
        xbmcgui.Window(10000).setProperty('kick.chat.slug', raw_url)


def _resolve_stream(slug):
    """Resolve a slug/URL to a playable HLS stream URL, or None."""
    if slug.endswith('.mp4') or slug.endswith('.m3u8'):
        return slug
    if slug.startswith('http'):
        # VOD / clip / worker proxy source URL
        data = api_get(slug)
        return data.get('source') or data.get('url')
    # Channel slug: proxy the internal livestream endpoint via Worker
    return (api_get(URL_PROXY_STREAM.format(slug=quote(slug, safe='')))
            .get('data') or {}).get('playback_url')


def _setup_inputstream(play_item, is_helper, hea):
    """Configure InputStream Adaptive properties on a ListItem."""
    quality = addon.getSetting('quality')
    # quality is now a boolean toggle: 'true' = ask every time, 'false' = automatic
    ask_quality = (quality == 'true')
    play_item.setProperty('IsPlayable', 'true')
    play_item.setProperty('inputstream', is_helper.inputstream_addon)
    if ask_quality:
        play_item.setProperty('inputstream.adaptive.stream_selection_type', 'ask-quality')
    play_item.setProperty('inputstream.adaptive.manifest_type', 'hls')
    play_item.setMimeType('application/vnd.apple.mpegurl')
    play_item.setProperty('inputstream.adaptive.manifest_headers', hea)


@plugin.route('/search')
def list_search():
    """Display search results (categories + exact channel match) for the given query."""
    query    = plugin.args.get('q', '')
    followed = _load_followed()

    # Exact channel slug match via public API (includes stream/live info)
    ch_data  = pub_get(URL_PUB_CHANNEL + '?slug=' + quote(query, safe=''))
    channels = ch_data.get('data') or []
    for x in channels:
        slug      = x.get('slug', '')
        pic       = x.get('profile_picture') or ICON
        stream    = x.get('stream') or {}
        is_live   = stream.get('is_live', False)
        thumbnail = stream.get('thumbnail') or pic
        label     = slug + (LIVE_BADGE if is_live else '')
        follow_label = str(language(30050 if slug in followed else 30049))
        ctx = [(follow_label, 'RunPlugin({})'.format(
                plugin.url_for(toggle_follow, slug=slug, name=slug, pic=pic)))]
        add_item(plugin.url_for(list_channel, slug=slug), label, thumbnail,
                 infoLabels={'title': label, 'plot': label},
                 icon=pic, folder=True, context_items=ctx)

    # Category search (deprecated v1 endpoint but still works)
    cat_data = pub_get(URL_PUB_CATEGORIES + '?q=' + quote_plus(query))
    cats     = cat_data.get('data') or []
    for x in cats:
        cat_id = x.get('id', '')
        title  = x.get('name', '')
        thumb  = x.get('thumbnail') or ICON
        live_url = URL_PUB_LIVESTREAMS + '?category_id={}&limit=100'.format(cat_id)
        add_item(plugin.url_for(live, url=live_url), title, thumb,
                 infoLabels={'title': title, 'plot': title},
                 folder=True)

    _end_dir()
    if not (channels or cats):
        _notify_loc(30029, ms=5000)


# ---------------------------------------------------------------------------
# Routes — Actions (no directory listing)
# ---------------------------------------------------------------------------
@plugin.route('/search_dialog')
def search_dialog():
    """Open a keyboard dialog and navigate to search results for the entered query."""
    query = xbmcgui.Dialog().input(str(language(30038)), type=xbmcgui.INPUT_ALPHANUM).strip()
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
    except Exception:
        xbmc.log('KICK: unhandled exception: ' + traceback.format_exc(), xbmc.LOGERROR)
        raise
