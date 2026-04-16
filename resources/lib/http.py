# -*- coding: utf-8 -*-
"""Shared HTTP layer for Kick addon: plain GET + public API with Bearer token."""
import requests
import xbmc
import xbmcgui

UA = 'okhttp/4.9.2'
UA_STREAM = 'Dalvik/2.1.0 (Linux; U; Android 9; SM-G960F Build/R16NW)'

WORKER_BASE = 'https://kodi.zales.dev'
URL_APP_TOKEN = WORKER_BASE + '/app-token'

# Token cache in the home Window — persists across plugin invocations
# within a single Kodi session (each plugin call is a new Python process).
_WIN = xbmcgui.Window(10000)
_TOKEN_KEY = 'kick_app_token'

# Sentinels for api_get return contract
OK = 'ok'
EMPTY = 'empty'
ERROR = 'error'


def _new_session():
    s = requests.Session()
    s.headers.update({'User-Agent': UA, 'Accept': 'application/json'})
    return s


session = _new_session()


def api_get(url, timeout=15):
    """GET url, return parsed JSON (dict/list) or {} on error."""
    try:
        r = session.get(url, timeout=timeout)
        xbmc.log('KICK: GET {} \u2192 {}'.format(url[:120], r.status_code), xbmc.LOGINFO)
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        xbmc.log('KICK: GET {} failed: {}'.format(url[:120], exc), xbmc.LOGERROR)
        return {}


def api_get_ex(url, timeout=15):
    """Like api_get, but returns (status, data) where status is OK/EMPTY/ERROR.

    EMPTY means request succeeded but payload is empty.
    ERROR means network/HTTP failure.
    """
    try:
        r = session.get(url, timeout=timeout)
        xbmc.log('KICK: GET {} \u2192 {}'.format(url[:120], r.status_code), xbmc.LOGINFO)
        r.raise_for_status()
        data = r.json()
        if not data:
            return EMPTY, {}
        return OK, data
    except Exception as exc:
        xbmc.log('KICK: GET {} failed: {}'.format(url[:120], exc), xbmc.LOGERROR)
        return ERROR, {}


def get_app_token():
    """Return a Bearer token, cached in the home Window property across requests."""
    token = _WIN.getProperty(_TOKEN_KEY)
    if token:
        return token
    try:
        r = session.get(URL_APP_TOKEN, timeout=10)
        r.raise_for_status()
        token = r.json().get('token', '')
        if token:
            _WIN.setProperty(_TOKEN_KEY, token)
    except Exception as exc:
        xbmc.log('KICK: app-token failed: {}'.format(exc), xbmc.LOGERROR)
    return token


def pub_get(url, timeout=15):
    """GET a Kick public API URL with Bearer app token; return parsed JSON or {}."""
    status, data = pub_get_ex(url, timeout=timeout)
    return data


def pub_get_ex(url, timeout=15):
    """Public API GET returning (status, data) tuple — see api_get_ex."""
    token = get_app_token()
    if not token:
        return ERROR, {}
    try:
        hdrs = {'Authorization': 'Bearer ' + token}
        r = session.get(url, timeout=timeout, headers=hdrs)
        xbmc.log('KICK: PUB {} \u2192 {}'.format(url[:120], r.status_code), xbmc.LOGINFO)
        if r.status_code == 401:
            # Token expired — clear cache and retry once
            _WIN.setProperty(_TOKEN_KEY, '')
            token = get_app_token()
            if not token:
                return ERROR, {}
            r = session.get(url, timeout=timeout,
                            headers={'Authorization': 'Bearer ' + token})
        r.raise_for_status()
        data = r.json()
        if not data:
            return EMPTY, {}
        return OK, data
    except Exception as exc:
        xbmc.log('KICK: PUB {} failed: {}'.format(url[:120], exc), xbmc.LOGERROR)
        return ERROR, {}
