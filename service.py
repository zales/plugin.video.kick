# -*- coding: utf-8 -*-
"""Background service for Kick chat overlay.

The plugin script (main.py) sets a home-window property with the channel slug
when live playback starts. This service picks it up and manages the WebSocket
chat overlay in its own long-running process — avoiding the 5-second script
kill timeout that CPythonInvoker enforces on plugin sources.
"""
import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs

from resources.lib.http import api_get, WORKER_BASE

ADDON_ID = 'plugin.video.kick'
PROP_SLUG = 'kick.chat.slug'
URL_PROXY_CHANNEL = WORKER_BASE + '/proxy/kick/api/v1/channels/{slug}'


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
        position = addon.getSetting('chat_pos') or 'an3'
        self._overlay = ChatOverlay(
            slug, api_get, profile, URL_PROXY_CHANNEL, position=position)
        self._overlay.start()

    def _stop(self):
        if self._overlay:
            self._overlay.stop()
            self._overlay = None


ChatService().run()
