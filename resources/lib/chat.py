# -*- coding: utf-8 -*-
"""Kick chat overlay via Pusher WebSocket + SRT subtitles."""
import base64
import json
import os
import re
import socket
import ssl
import struct
import threading
import time
import uuid as _uuid
from collections import deque

import xbmc
import xbmcvfs

LOG_PREFIX = 'KICK chat: '
MAX_LINES = 12
MAX_WIDTH = 80
PING_INTERVAL = 60  # seconds between proactive pusher:ping

PUSHER_KEY = '32cbd69e4b950bf97679'
PUSHER_HOST = 'ws-us2.pusher.com'
PUSHER_PATH = '/app/%s?protocol=7&client=js&version=8.4.0-rc2&flash=false' % PUSHER_KEY


def _safe(text):
    """Strip problematic characters and convert emotes to :name:."""
    t = re.sub(r'\[emote:\d+:([^\]]+)\]', r':\1:', text or '')
    return t.replace('<', '').replace('>', '').replace('\n', ' ')


def _wrap(text, width=MAX_WIDTH):
    """Word-wrap text to max width."""
    words = text.split(' ')
    lines = []
    cur = ''
    for w in words:
        if cur and len(cur) + 1 + len(w) > width:
            lines.append(cur)
            cur = w
        else:
            cur = (cur + ' ' + w) if cur else w
    if cur:
        lines.append(cur)
    return '\n'.join(lines)


# ---------------------------------------------------------------------------
# Minimal WebSocket client (stdlib only, no dependencies)
# ---------------------------------------------------------------------------

def _recv_exact(sock, n):
    data = b''
    while len(data) < n:
        chunk = sock.recv(n - len(data))
        if not chunk:
            raise ConnectionError('WebSocket closed')
        data += chunk
    return data


def _ws_connect():
    """Open a WebSocket connection to Pusher, return the ssl socket."""
    ctx = ssl.create_default_context()
    raw = socket.create_connection((PUSHER_HOST, 443), timeout=15)
    sock = ctx.wrap_socket(raw, server_hostname=PUSHER_HOST)
    sock.settimeout(15)

    ws_key = base64.b64encode(os.urandom(16)).decode()
    handshake = (
        'GET %s HTTP/1.1\r\n'
        'Host: %s\r\n'
        'Upgrade: websocket\r\n'
        'Connection: Upgrade\r\n'
        'Sec-WebSocket-Key: %s\r\n'
        'Sec-WebSocket-Version: 13\r\n'
        '\r\n'
    ) % (PUSHER_PATH, PUSHER_HOST, ws_key)
    sock.sendall(handshake.encode())

    resp = b''
    while b'\r\n\r\n' not in resp:
        chunk = sock.recv(256)
        if not chunk:
            raise ConnectionError('WebSocket handshake: connection closed')
        resp += chunk
        if len(resp) > 8192:
            raise ConnectionError('WebSocket handshake: response too large')
    if b'101' not in resp.split(b'\r\n')[0]:
        raise ConnectionError('WebSocket handshake failed')
    return sock


def _ws_recv(sock):
    """Read one WebSocket frame, return payload string or None on close.

    Transparently replies to ping frames and continues until a data frame
    (or close) arrives.
    """
    while True:
        header = _recv_exact(sock, 2)
        opcode = header[0] & 0x0F
        length = header[1] & 0x7F

        if length == 126:
            length = struct.unpack('!H', _recv_exact(sock, 2))[0]
        elif length == 127:
            length = struct.unpack('!Q', _recv_exact(sock, 8))[0]

        masked = (header[1] & 0x80) != 0
        if masked:
            mask = _recv_exact(sock, 4)
            payload = _recv_exact(sock, length)
            payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        else:
            payload = _recv_exact(sock, length) if length else b''

        if opcode == 0x8:  # close
            return None
        if opcode == 0x9:  # ping
            _ws_send(sock, payload, opcode=0xA)  # pong
            continue
        if opcode == 0xA:  # pong
            continue
        return payload.decode('utf-8', errors='replace')


def _ws_send(sock, data, opcode=0x1):
    """Send a masked WebSocket frame."""
    if isinstance(data, str):
        data = data.encode('utf-8')
    mask = os.urandom(4)
    masked = bytes(b ^ mask[i % 4] for i, b in enumerate(data))

    header = bytes([0x80 | opcode])
    length = len(data)
    if length < 126:
        header += bytes([0x80 | length])
    elif length < 65536:
        header += bytes([0x80 | 126]) + struct.pack('!H', length)
    else:
        header += bytes([0x80 | 127]) + struct.pack('!Q', length)

    sock.sendall(header + mask + masked)


# ---------------------------------------------------------------------------
# Chat overlay
# ---------------------------------------------------------------------------

class ChatOverlay:
    """Connect to Kick chat via Pusher WebSocket, render as SRT subtitles."""

    def __init__(self, slug, api_get_func, profile_dir, channel_url_tpl,
                 position='an3', size=10):
        self._slug = slug
        self._api_get = api_get_func
        self._profile = profile_dir
        self._channel_url_tpl = channel_url_tpl
        self._position = position if position in ('an1', 'an2', 'an3') else 'an3'
        self._size = size if isinstance(size, int) and 4 <= size <= 40 else 10
        self._lines = deque(maxlen=MAX_LINES)
        # Unique filename per session — Kodi caches parsed subtitle tracks by
        # path, so changing only the file contents does not re-apply override
        # tags like {\an1}. New path forces a fresh parse.
        fname = 'chat-{}.srt'.format(_uuid.uuid4().hex[:8])
        self._sub_path = os.path.join(profile_dir, fname)
        self._stop = threading.Event()
        self._ws = None
        xbmcvfs.mkdirs(profile_dir)
        xbmc.log(LOG_PREFIX + 'overlay init position=%s size=%s file=%s' % (
            self._position, self._size, fname), xbmc.LOGINFO)

    def start(self):
        threading.Thread(target=self._run, daemon=True).start()

    def stop(self):
        self._stop.set()
        ws = self._ws
        if ws:
            try:
                ws.close()
            except Exception:
                pass

    def set_position(self, pos):
        """Update on-screen position of the chat overlay at runtime."""
        if pos not in ('an1', 'an2', 'an3') or pos == self._position:
            return
        self._position = pos
        self._rotate_and_refresh('position=%s' % pos)

    def set_size(self, size):
        """Update font size of existing chat lines at runtime."""
        if not isinstance(size, int) or size == self._size or not (4 <= size <= 40):
            return
        # Rewrite already-cached lines with the new font size so the overlay
        # updates even before the next chat message arrives.
        new_lines = deque(maxlen=MAX_LINES)
        for ln in self._lines:
            new_lines.append(re.sub(
                r'<font size="\d+">', '<font size="%d">' % size, ln, count=1))
        self._lines = new_lines
        self._size = size
        self._rotate_and_refresh('size=%s' % size)

    def _rotate_and_refresh(self, reason):
        # Kodi caches a parsed subtitle track by path — rotate the file name
        # so the updated override tags / font size are re-parsed.
        fname = 'chat-{}.srt'.format(_uuid.uuid4().hex[:8])
        old_path = self._sub_path
        self._sub_path = os.path.join(self._profile, fname)
        xbmc.log(LOG_PREFIX + 'rotate %s (file=%s)' % (reason, fname),
                 xbmc.LOGINFO)
        if self._lines:
            try:
                self._update_srt(xbmc.Player())
            except Exception as exc:
                xbmc.log(LOG_PREFIX + 'rotate update failed: %s' % exc,
                         xbmc.LOGWARNING)
        try:
            xbmcvfs.delete(old_path)
        except Exception:
            pass

    def _run(self):
        from urllib.parse import quote
        player = xbmc.Player()

        # Wait for playback
        for _ in range(30):
            if self._stop.is_set() or player.isPlaying():
                break
            xbmc.sleep(500)
        if self._stop.is_set() or not player.isPlaying():
            return

        # Resolve chatroom_id (Pusher uses chatroom.id, not channel id)
        ch_data = self._api_get(
            self._channel_url_tpl.format(slug=quote(self._slug, safe='')))
        chatroom_id = (ch_data.get('chatroom') or {}).get('id')
        if not chatroom_id:
            xbmc.log(LOG_PREFIX + 'no chatroom id for ' + self._slug, xbmc.LOGWARNING)
            return

        channel = 'chatrooms.%s.v2' % chatroom_id
        xbmc.log(LOG_PREFIX + 'connecting WS for %s (chatroom=%s)' % (
            self._slug, chatroom_id), xbmc.LOGINFO)

        try:
            self._ws = _ws_connect()
            # Read connection_established
            _ws_recv(self._ws)
            # Subscribe
            _ws_send(self._ws, json.dumps({
                'event': 'pusher:subscribe',
                'data': {'channel': channel}
            }))
            xbmc.log(LOG_PREFIX + 'subscribed to ' + channel, xbmc.LOGINFO)

            # Defer first setSubtitles() until we have a real cue — loading an
            # empty file caches a track with no override tag and Kodi then
            # ignores {\anN} on subsequent reloads of the same path.

            self._ws.settimeout(1.0)
            last_ping = time.time()
            while not self._stop.is_set() and player.isPlaying():
                # Proactive keepalive — Pusher closes idle conns after ~120s
                now = time.time()
                if now - last_ping >= PING_INTERVAL:
                    try:
                        _ws_send(self._ws, json.dumps(
                            {'event': 'pusher:ping', 'data': {}}))
                        last_ping = now
                    except Exception:
                        break
                try:
                    raw = _ws_recv(self._ws)
                except socket.timeout:
                    continue
                except Exception:
                    break
                if raw is None:
                    break
                try:
                    evt = json.loads(raw)
                except Exception:
                    continue

                event_name = evt.get('event', '')

                # Pusher ping
                if event_name == 'pusher:ping':
                    _ws_send(self._ws, json.dumps({'event': 'pusher:pong', 'data': {}}))
                    continue
                if event_name == 'pusher:pong':
                    continue

                # Chat message
                if 'ChatMessage' not in event_name:
                    continue

                try:
                    data = json.loads(evt.get('data', '{}'))
                except Exception:
                    continue

                username = _safe((data.get('sender') or {}).get('username', '???'))
                color = ((data.get('sender') or {}).get('identity') or {}).get(
                    'color', '#FFFFFF').lstrip('#')
                content = _safe(data.get('content', ''))
                if not content:
                    continue

                line = '<font size="%d"><font color="#%s">%s:</font> %s</font>' % (
                    self._size, color, username, content)
                self._lines.append(_wrap(line))
                self._update_srt(player)

        except Exception as exc:
            xbmc.log(LOG_PREFIX + 'WS error: %s' % exc, xbmc.LOGWARNING)
        finally:
            if self._ws:
                try:
                    self._ws.close()
                except Exception:
                    pass
                self._ws = None
            try:
                xbmcvfs.delete(self._sub_path)
            except Exception:
                pass
            xbmc.log(LOG_PREFIX + 'stopped', xbmc.LOGINFO)

    def _update_srt(self, player):
        body = '\n'.join(self._lines)
        srt = '1\n00:00:00,000 --> 99:59:59,000\n{\\%s}%s\n' % (self._position, body)
        self._write_srt(srt)
        player.setSubtitles(self._sub_path)

    def _write_srt(self, content):
        try:
            with open(self._sub_path, 'w', encoding='utf-8-sig') as f:
                f.write(content)
        except Exception as exc:
            xbmc.log(LOG_PREFIX + 'write error: %s' % exc, xbmc.LOGWARNING)
