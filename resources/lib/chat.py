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
ABS_MAX_LINES = 30      # hard upper bound regardless of room available
MIN_LINES = 2
PING_INTERVAL = 60  # seconds between proactive pusher:ping

# ASS logical canvas. Kodi/libass scales this to the actual video size so
# coordinates are resolution-independent.
PLAY_RES_X = 1920
PLAY_RES_Y = 1080
MARGIN_X = 40          # horizontal padding from screen edges (in PlayResX units)
TOP_MARGIN_Y = 60      # padding from top when growing upward
BOTTOM_MARGIN_Y = 60   # padding from bottom edge for bottom-row positions
TOP_ROW_Y = int(PLAY_RES_Y * 0.50)     # y for top-row positions (= vertical middle)

# Max chat line width = ~1/3 of screen width (in PlayResX units).
MAX_LINE_PX = PLAY_RES_X // 3
MIN_WRAP_CHARS = 16    # never wrap below this (too-short lines look silly)
ABS_MAX_WRAP_CHARS = 80

# X coordinate for the left edge of the right-side column (2/3 of screen).
# Right-column positions anchor the block's LEFT edge here (not the right),
# so every line begins at the same horizontal offset and grows into the
# final third of the screen. Wrap width keeps text inside the 1/3 strip.
RIGHT_COL_X = PLAY_RES_X * 2 // 3

# Chat position -> (anchor, x, y, vertical_budget) of the anchor edge of the
# text block. Anchor is always 1/2/3 (bottom) so multi-line text grows upward
# naturally. For right-column positions we use 'an1' (bottom-LEFT) anchored at
# 2/3 so line-starts are aligned; for left-column we use 'an1' at the left
# margin.
#   top row (7/9)     -> bottom at screen middle -> fills upper half
#   middle row (4/6)  -> bottom at screen floor  -> fills WHOLE side column
#   bottom row (1/3)  -> bottom near screen floor-> fills lower half only
FULL_HEIGHT_BUDGET = PLAY_RES_Y - BOTTOM_MARGIN_Y - TOP_MARGIN_Y
HALF_HEIGHT_BUDGET = (PLAY_RES_Y - BOTTOM_MARGIN_Y) - PLAY_RES_Y // 2
POSITIONS = {
    # Left column: left-anchored at MARGIN_X
    'an7': ('an1', MARGIN_X,     TOP_ROW_Y,                    TOP_ROW_Y - TOP_MARGIN_Y),
    'an4': ('an1', MARGIN_X,     PLAY_RES_Y - BOTTOM_MARGIN_Y, FULL_HEIGHT_BUDGET),
    'an1': ('an1', MARGIN_X,     PLAY_RES_Y - BOTTOM_MARGIN_Y, HALF_HEIGHT_BUDGET),
    # Right column: left-anchored at 2/3 so line-starts line up vertically.
    'an9': ('an1', RIGHT_COL_X,  TOP_ROW_Y,                    TOP_ROW_Y - TOP_MARGIN_Y),
    'an6': ('an1', RIGHT_COL_X,  PLAY_RES_Y - BOTTOM_MARGIN_Y, FULL_HEIGHT_BUDGET),
    'an3': ('an1', RIGHT_COL_X,  PLAY_RES_Y - BOTTOM_MARGIN_Y, HALF_HEIGHT_BUDGET),
}


def _max_visual_lines_for(position, size):
    """How many VISUAL (post-wrap) lines fit into the vertical budget of the
    selected position at the given font size."""
    budget = POSITIONS.get(position, POSITIONS['an3'])[3]
    line_h = max(1.0, size * 1.2)  # libass line height ≈ 1.2 * fontsize
    n = int(budget // line_h)
    return max(MIN_LINES, min(ABS_MAX_LINES, n))


def _buffer_size_for(position, size):
    """Logical-message buffer size. Each message may wrap to several visual
    lines, but also may fit on one. Reserve 4x visual budget so even when
    every cached message is single-line we still have history to show after
    a font-size change."""
    return min(ABS_MAX_LINES * 4, max(MIN_LINES * 2,
                                      _max_visual_lines_for(position, size) * 4))

PUSHER_KEY = '32cbd69e4b950bf97679'
PUSHER_HOST = 'ws-us2.pusher.com'
PUSHER_PATH = '/app/%s?protocol=7&client=js&version=8.4.0-rc2&flash=false' % PUSHER_KEY


def _safe(text):
    """Strip problematic characters and convert emotes to :name:."""
    t = re.sub(r'\[emote:\d+:([^\]]+)\]', r':\1:', text or '')
    # Strip chars that have special meaning in ASS override blocks or HTML.
    return (t.replace('<', '').replace('>', '')
             .replace('{', '(').replace('}', ')')
             .replace('\n', ' '))


def _hex_to_ass_color(hex_color):
    """Convert #RRGGBB to ASS &HBBGGRR&. Accepts leading '#' optional."""
    h = (hex_color or 'FFFFFF').lstrip('#')
    if len(h) != 6 or not re.match(r'^[0-9A-Fa-f]{6}$', h):
        h = 'FFFFFF'
    return '&H%s%s%s&' % (h[4:6].upper(), h[2:4].upper(), h[0:2].upper())


def _wrap_chars_for(size):
    """Approximate character budget so a line fits within MAX_LINE_PX.
    Arial proportional font: average glyph width ≈ 0.5 * fs."""
    avg_w = max(1.0, size * 0.5)
    n = int(MAX_LINE_PX // avg_w)
    return max(MIN_WRAP_CHARS, min(ABS_MAX_WRAP_CHARS, n))


def _tokenize_for_wrap(text):
    r"""Split text into (token, visible_len) pairs. ASS override blocks like
    {\c&H..&} and {\r} are kept atomic and treated as zero-width so word
    wrapping never splits them."""
    parts = re.split(r'(\{[^}]*\})', text)
    tokens = []
    for part in parts:
        if not part:
            continue
        if part.startswith('{') and part.endswith('}'):
            tokens.append((part, 0))
        else:
            # Split on whitespace, keeping spaces as their own tokens so we
            # can join without losing them.
            for sub in re.split(r'( +)', part):
                if sub:
                    tokens.append((sub, len(sub)))
    return tokens


def _wrap(text, width):
    """Word-wrap text to max visible character width, preserving ASS
    override tags as atomic unbreakable tokens."""
    tokens = _tokenize_for_wrap(text)
    lines = []
    cur = ''
    cur_len = 0
    for tok, vlen in tokens:
        # Hard-split oversized non-tag tokens so a single huge word can't
        # exceed the width budget.
        if vlen > width and not tok.startswith('{'):
            if cur.strip():
                lines.append(cur.rstrip())
            while len(tok) > width:
                lines.append(tok[:width])
                tok = tok[width:]
            cur = tok
            cur_len = len(tok)
            continue
        if cur_len + vlen > width and cur.strip():
            lines.append(cur.rstrip())
            # drop leading spaces on new line
            if tok.strip() == '':
                cur = ''
                cur_len = 0
            else:
                cur = tok
                cur_len = vlen
        else:
            cur += tok
            cur_len += vlen
    if cur.strip():
        lines.append(cur.rstrip())
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
                 position='an3', size=30):
        self._slug = slug
        self._api_get = api_get_func
        self._profile = profile_dir
        self._channel_url_tpl = channel_url_tpl
        self._position = position if position in POSITIONS else 'an3'
        self._size = size if isinstance(size, int) and 4 <= size <= 80 else 30
        self._lines = deque(maxlen=_buffer_size_for(self._position, self._size))
        # Unique filename per session — Kodi caches parsed subtitle tracks by
        # path, so changing only the file contents does not re-apply override
        # tags. New path forces a fresh parse.
        fname = 'chat-{}.ass'.format(_uuid.uuid4().hex[:8])
        self._sub_path = os.path.join(profile_dir, fname)
        self._stop = threading.Event()
        self._ws = None
        xbmcvfs.mkdirs(profile_dir)
        xbmc.log(LOG_PREFIX + 'overlay init position=%s size=%s maxlines=%d file=%s' % (
            self._position, self._size, self._lines.maxlen, fname), xbmc.LOGINFO)

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
        if pos not in POSITIONS or pos == self._position:
            return
        self._position = pos
        self._resize_buffer()
        self._rotate_and_refresh('position=%s' % pos)

    def set_size(self, size):
        """Update font size at runtime."""
        if not isinstance(size, int) or size == self._size or not (4 <= size <= 80):
            return
        self._size = size
        self._resize_buffer()
        self._rotate_and_refresh('size=%s' % size)

    def _resize_buffer(self):
        """Adjust deque capacity to fit the vertical room at current size/pos."""
        new_max = _buffer_size_for(self._position, self._size)
        if new_max == self._lines.maxlen:
            return
        old_lines = list(self._lines)
        # keep the most recent items that still fit
        self._lines = deque(old_lines[-new_max:], maxlen=new_max)
        xbmc.log(LOG_PREFIX + 'buffer resized maxlines=%d' % new_max,
                 xbmc.LOGINFO)

    def _rotate_and_refresh(self, reason):
        # Kodi caches a parsed subtitle track by path — rotate the file name
        # so the updated override tags / font size are re-parsed.
        fname = 'chat-{}.ass'.format(_uuid.uuid4().hex[:8])
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
                    'color', '#FFFFFF')
                content = _safe(data.get('content', ''))
                if not content:
                    continue

                # Per-message line: colored username + default-colored content.
                # {\r} resets color back to Style default for the content.
                line = '{\\c%s}%s:{\\r} %s' % (
                    _hex_to_ass_color(color), username, content)
                # Store UNWRAPPED; wrap happens at render time so a font-size
                # change re-wraps existing buffered messages correctly.
                self._lines.append(line)
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
        # Wrap each buffered logical message to the font-size-dependent width,
        # then pick messages from the END (most recent) while their combined
        # VISUAL line count fits the vertical budget.
        width = _wrap_chars_for(self._size)
        visual_budget = _max_visual_lines_for(self._position, self._size)
        pieces = []     # list of wrapped strings in display order
        visual_used = 0
        for ln in reversed(self._lines):
            wrapped = _wrap(ln, width)
            n = wrapped.count('\n') + 1
            if visual_used + n > visual_budget and pieces:
                break
            pieces.append(wrapped.replace('\n', '\\N'))
            visual_used += n
            if visual_used >= visual_budget:
                break
        pieces.reverse()
        body = '\\N'.join(pieces)
        anchor, px, py, _budget = POSITIONS.get(self._position, POSITIONS['an3'])
        ass = self._build_ass(body, anchor, px, py, self._size)
        self._write_srt(ass)
        player.setSubtitles(self._sub_path)

    def _build_ass(self, body, anchor, px, py, size):
        # Minimal ASS document. Style 'Default' defines font, default colour,
        # outline; per-Dialogue override tags set alignment, position and size.
        header = (
            '[Script Info]\n'
            'ScriptType: v4.00+\n'
            'PlayResX: %d\n'
            'PlayResY: %d\n'
            'ScaledBorderAndShadow: yes\n'
            'WrapStyle: 2\n'
            '\n'
            '[V4+ Styles]\n'
            'Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour,'
            ' OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut,'
            ' ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow,'
            ' Alignment, MarginL, MarginR, MarginV, Encoding\n'
            'Style: Default,Arial,%d,&H00FFFFFF,&H00FFFFFF,&H00000000,'
            '&H80000000,0,0,0,0,100,100,0,0,1,2,1,2,20,20,20,1\n'
            '\n'
            '[Events]\n'
            'Format: Layer, Start, End, Style, Name, MarginL, MarginR,'
            ' MarginV, Effect, Text\n'
        ) % (PLAY_RES_X, PLAY_RES_Y, size)
        dialogue = (
            'Dialogue: 0,0:00:00.00,9:59:59.00,Default,,0,0,0,,'
            '{\\%s\\pos(%d,%d)\\fs%d}%s\n' % (anchor, px, py, size, body)
        )
        return header + dialogue

    def _write_srt(self, content):
        try:
            with open(self._sub_path, 'w', encoding='utf-8-sig') as f:
                f.write(content)
        except Exception as exc:
            xbmc.log(LOG_PREFIX + 'write error: %s' % exc, xbmc.LOGWARNING)
