# -*- coding: utf-8 -*-
"""Small helpers: title cleaning, pagination, followed channels store."""
import json
import os
import re
from urllib.parse import parse_qs, urlencode, urlparse

import xbmc
import xbmcvfs


# Emoji / symbol characters to strip from stream titles
_RE_STRIP = re.compile(
    '['
    '\U0001F000-\U0001FFFF'   # Misc symbols, emoticons, transport, etc.
    '\U00002600-\U000027BF'   # Misc symbols, dingbats
    '\U0000FE00-\U0000FE0F'   # Variation selectors
    '\U00020000-\U0002A6DF'   # CJK extension B
    '\u200d'                  # Zero-width joiner
    '\uFE0F'                  # Variation selector-16
    ']+',
    flags=re.UNICODE,
)


def clean_title(s):
    """Strip newlines and emoji/symbol characters from a string."""
    return _RE_STRIP.sub('', (s or '').replace('\n', ' ')).strip()


def next_page_url(url, cursor):
    """Return *url* with cursor= replaced by the new cursor value."""
    parsed = urlparse(url)
    pdict = parse_qs(parsed.query, keep_blank_values=True)
    pdict.pop('cursor', None)
    flat = {k: v[0] for k, v in pdict.items()}
    flat['cursor'] = cursor
    return parsed._replace(query=urlencode(flat)).geturl()


def load_followed(path):
    """Return the followed channels dict from *path* or {} on error."""
    try:
        if xbmcvfs.exists(path):
            with xbmcvfs.File(path) as f:
                return json.loads(f.read()) or {}
    except Exception as exc:
        xbmc.log('KICK: load_followed failed: {}'.format(exc), xbmc.LOGERROR)
    return {}


def save_followed(profile_dir, path, data):
    """Persist the followed channels dict to *path*."""
    try:
        xbmcvfs.mkdirs(profile_dir)
        with xbmcvfs.File(path, 'w') as f:
            f.write(json.dumps(data))
    except Exception as exc:
        xbmc.log('KICK: save_followed failed: {}'.format(exc), xbmc.LOGERROR)


def join_path(*parts):
    """os.path.join wrapper using forward slashes (Kodi-safe)."""
    return os.path.join(*parts)
