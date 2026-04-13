# -*- coding: utf-8 -*-
"""Minimal path-based routing for Kodi plugins.  Python 3 only."""
import sys
import re
from urllib.parse import urlencode, parse_qs, urlparse, quote


class RouteMissingError(Exception):
    pass


class Plugin:
    """
    Decorate view functions with ``@plugin.route('/path')`` and call
    ``plugin.run()`` as the entry point.  Path params use ``<name>`` syntax.
    """

    def __init__(self):
        self._routes = []
        parsed = urlparse(sys.argv[0])
        self.base_url = '{}://{}'.format(parsed.scheme, parsed.netloc)
        self.handle = int(sys.argv[1])
        self._path = parsed.path or '/'
        # Flatten single-value lists so args['key'] == 'value' (not ['value'])
        self.args = {k: (v[0] if len(v) == 1 else v)
                     for k, v in parse_qs(sys.argv[2][1:]).items()}

    # ------------------------------------------------------------------
    def route(self, pattern):
        """Register *func* to handle requests matching *pattern*."""
        def decorator(func):
            re_pat = re.sub(r'<(\w+)>', r'(?P<\1>[^/?]+)', pattern)
            self._routes.append((pattern, re.compile('^' + re_pat + '$'), func))
            return func
        return decorator

    # ------------------------------------------------------------------
    def url_for(self, func, **kwargs):
        """Build the full ``plugin://`` URL that invokes *func*."""
        for pattern, _, f in self._routes:
            if f is func:
                url = self.base_url + pattern
                remaining = {}
                for k, v in kwargs.items():
                    ph = '<{}>'.format(k)
                    if ph in url:
                        url = url.replace(ph, quote(str(v), safe=''))
                    else:
                        remaining[k] = v
                if remaining:
                    url += '?' + urlencode(remaining)
                return url
        raise RouteMissingError('No route registered for: ' + func.__name__)

    # ------------------------------------------------------------------
    def run(self):
        """Dispatch the current request to the matching route handler."""
        for _, regex, func in self._routes:
            m = regex.match(self._path)
            if m:
                func(**m.groupdict())
                return
        raise RouteMissingError('No route matches: ' + self._path)
