# -*- coding: utf-8 -*-
"""Background service for Kick chat overlay.

The plugin script (main.py) sets a home-window property with the channel slug
when live playback starts. This service picks it up and manages the WebSocket
chat overlay in its own long-running process — avoiding the 5-second script
kill timeout that CPythonInvoker enforces on plugin sources.
"""
import requests
import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs

ADDON_ID = 'plugin.video.kick'
PROP_SLUG = 'kick.chat.slug'
WORKER_BASE = 'https://kodi.zales.dev'
URL_PROXY_CHANNEL = WORKER_BASE + '/proxy/kick/api/v1/channels/{slug}'


def _api_get(url):
    try:
        r = requests.get(url, headers={
            'User-Agent': 'okhttp/4.9.2',
            'Accept': 'application/json',
        }, timeout=15)
        r.raise_for_status()
        return r.json()
    except Exception:
        return {}


class ChatService(xbmc.Monitor):
    def __init__(self):
        super().__init__()
        self._overlay = None
        self._window = xbmcgui.Window(10000)

    def run(self):
        xbmc.log('KICK service: started', xbmc.LOGINFO)
        player = xbmc.Player()

        while not self.abortRequested():
            if self.waitForAbort(0.5):
                break

            slug = self._window.getProperty(PROP_SLUG)

            # New chat request
            if slug and self._overlay is None:
                self._window.clearProperty(PROP_SLUG)
                self._start(slug)

            # Playback stopped — tear down overlay
            if self._overlay and not player.isPlaying():
                self._stop()

        self._stop()
        xbmc.log('KICK service: stopped', xbmc.LOGINFO)

    def _start(self, slug):
        from resources.lib.chat import ChatOverlay
        addon = xbmcaddon.Addon(id=ADDON_ID)
        profile = xbmcvfs.translatePath(addon.getAddonInfo('profile'))
        self._overlay = ChatOverlay(
            slug, _api_get, profile, WORKER_BASE, URL_PROXY_CHANNEL)
        self._overlay.start()

    def _stop(self):
        if self._overlay:
            self._overlay.stop()
            self._overlay = None


ChatService().run()
