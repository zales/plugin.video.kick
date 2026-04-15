# -*- coding: utf-8 -*-
"""Kick chat overlay using SRT subtitles — simple, no blink."""
import os
import re
import threading
from collections import deque

import xbmc
import xbmcvfs

LOG_PREFIX = 'KICK chat: '
MAX_LINES = 12


def _safe(text):
    """Strip problematic characters and convert emotes to :name:."""
    t = re.sub(r'\[emote:\d+:([^\]]+)\]', r':\1:', text or '')
    return t.replace('<', '').replace('>', '').replace('\n', ' ')


class ChatOverlay:
    """Poll Kick chat via REST and display as SRT subtitles."""

    POLL_INTERVAL = 1.0

    def __init__(self, slug, api_get_func, profile_dir, worker_base, channel_url_tpl):
        self._slug = slug
        self._api_get = api_get_func
        self._profile = profile_dir
        self._worker_base = worker_base
        self._channel_url_tpl = channel_url_tpl
        self._seen_ids = set()
        self._lines = deque(maxlen=MAX_LINES)
        self._sub_path = os.path.join(profile_dir, 'chat.srt')
        self._subs_loaded = False
        xbmcvfs.mkdirs(profile_dir)

    def start(self):
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        from urllib.parse import quote
        player = xbmc.Player()

        for _ in range(30):
            if player.isPlaying():
                break
            xbmc.sleep(500)
        if not player.isPlaying():
            return

        ch_data = self._api_get(
            self._channel_url_tpl.format(slug=quote(self._slug, safe='')))
        channel_id = ch_data.get('id')
        if not channel_id:
            xbmc.log(LOG_PREFIX + 'no channel id for ' + self._slug, xbmc.LOGWARNING)
            return

        url = '%s/proxy/kick/api/v2/channels/%s/messages' % (
            self._worker_base, channel_id)
        xbmc.log(LOG_PREFIX + 'started for %s (id=%s)' % (self._slug, channel_id),
                 xbmc.LOGINFO)

        # Write initial empty SRT and load it once
        self._write_srt('')
        player.setSubtitles(self._sub_path)
        self._subs_loaded = True

        while player.isPlaying():
            try:
                self._poll(player, url)
            except Exception as exc:
                xbmc.log(LOG_PREFIX + 'poll error: %s' % exc, xbmc.LOGWARNING)
            for _ in range(int(self.POLL_INTERVAL * 4)):
                if not player.isPlaying():
                    break
                xbmc.sleep(250)

        try:
            xbmcvfs.delete(self._sub_path)
        except Exception:
            pass
        xbmc.log(LOG_PREFIX + 'stopped', xbmc.LOGINFO)

    def _poll(self, player, url):
        data = self._api_get(url)
        messages = (data.get('data') or {}).get('messages') or []

        new_count = 0
        for msg in messages:
            mid = msg.get('id', '')
            if mid in self._seen_ids:
                continue
            self._seen_ids.add(mid)
            sender = msg.get('sender') or {}
            username = _safe(sender.get('username') or '???')
            color = (sender.get('identity') or {}).get('color', '#FFFFFF').lstrip('#')
            content = _safe(msg.get('content', ''))
            if not content:
                continue
            line = '<font color="#%s">%s:</font> %s' % (color, username, content)
            self._lines.append(line)
            new_count += 1

        if new_count > 0:
            # Build one SRT entry spanning 0:00:00 → 9:59:59
            body = '\n'.join(self._lines)
            srt = '1\n00:00:00,000 --> 09:59:59,000\n%s\n' % body
            self._write_srt(srt)
            # Reload subs so Kodi picks up the new content
            player.setSubtitles(self._sub_path)

    def _write_srt(self, content):
        try:
            with open(self._sub_path, 'w', encoding='utf-8') as f:
                f.write(content)
        except Exception as exc:
            xbmc.log(LOG_PREFIX + 'write error: %s' % exc, xbmc.LOGWARNING)
