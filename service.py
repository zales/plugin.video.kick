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
        self._current_slug = None

    # ------------------------------------------------------------------
    # Settings helpers
    # ------------------------------------------------------------------
    def _read_settings(self):
        addon = xbmcaddon.Addon(id=ADDON_ID)
        enabled = addon.getSetting('chat') == 'true'
        position = (addon.getSetting('chat_pos') or 'an3').strip()
        if position not in ('an1', 'an2', 'an3'):
            position = 'an3'
        try:
            size = int((addon.getSetting('chat_size') or '10').strip())
        except ValueError:
            size = 10
        if size not in (8, 10, 12, 14, 16):
            size = 10
        return enabled, position, size

    def onSettingsChanged(self):
        """Re-apply chat settings live — called by Kodi on settings save."""
        enabled, position, size = self._read_settings()
        xbmc.log(
            'KICK service: onSettingsChanged chat=%s pos=%s size=%s slug=%s overlay=%s'
            % (enabled, position, size, self._current_slug,
               'yes' if self._overlay else 'no'),
            xbmc.LOGINFO,
        )
        player = xbmc.Player()
        if enabled:
            if self._overlay is None and self._current_slug and player.isPlaying():
                self._start(self._current_slug, position=position, size=size)
            elif self._overlay is not None:
                self._overlay.set_position(position)
                self._overlay.set_size(size)
        else:
            if self._overlay is not None:
                self._stop()

    # ------------------------------------------------------------------
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
                self._current_slug = slug
                enabled, position, size = self._read_settings()
                if enabled:
                    self._start(slug, position=position, size=size)

            # Playback stopped — tear down overlay + forget slug
            if not player.isPlaying():
                if self._overlay:
                    self._stop()
                self._current_slug = None

        self._stop()
        xbmc.log('KICK service: stopped', xbmc.LOGINFO)

    def _start(self, slug, position='an3', size=10):
        from resources.lib.chat import ChatOverlay
        addon = xbmcaddon.Addon(id=ADDON_ID)
        profile = xbmcvfs.translatePath(addon.getAddonInfo('profile'))
        xbmc.log('KICK service: starting overlay slug=%s pos=%s size=%s'
                 % (slug, position, size), xbmc.LOGINFO)
        self._overlay = ChatOverlay(
            slug, api_get, profile, URL_PROXY_CHANNEL,
            position=position, size=size)
        self._overlay.start()

    def _stop(self):
        if self._overlay:
            self._overlay.stop()
            self._overlay = None


ChatService().run()
