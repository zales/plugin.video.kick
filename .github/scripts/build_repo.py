#!/usr/bin/env python3
"""Build Kodi repository structure for GitHub Pages deployment."""
import hashlib
import os
import shutil
import sys
import xml.etree.ElementTree as ET

ADDON_ID = 'plugin.video.kick'
OUT_DIR  = 'repo_output'

version  = sys.argv[1] if len(sys.argv) > 1 else 'unknown'
zip_name = f'{ADDON_ID}-{version}.zip'
addon_out = os.path.join(OUT_DIR, ADDON_ID)
os.makedirs(addon_out, exist_ok=True)

# Addon zip
if os.path.exists(zip_name):
    shutil.copy(zip_name, os.path.join(addon_out, zip_name))

# Assets
for fname in ('addon.xml', 'icon.png', 'fanart.jpg'):
    if os.path.exists(fname):
        shutil.copy(fname, os.path.join(addon_out, fname))

# addons.xml
tree    = ET.parse('addon.xml')
root    = tree.getroot()
wrapper = ET.Element('addons')
wrapper.append(root)
ET.indent(wrapper, space='    ')
body       = ET.tostring(wrapper, encoding='unicode')
addons_xml = f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n{body}\n'

with open(os.path.join(OUT_DIR, 'addons.xml'), 'w', encoding='utf-8') as f:
    f.write(addons_xml)

# addons.xml.md5
md5 = hashlib.md5(addons_xml.encode('utf-8')).hexdigest()
with open(os.path.join(OUT_DIR, 'addons.xml.md5'), 'w') as f:
    f.write(md5)

# .nojekyll (prevent Jekyll from processing files on GitHub Pages)
open(os.path.join(OUT_DIR, '.nojekyll'), 'w').close()

# index.html
repo_url = f'https://zales.github.io/{ADDON_ID}'
html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>KICK.com Kodi Repository</title>
<style>
  body {{ font-family: sans-serif; max-width: 680px; margin: 60px auto; padding: 0 20px; background: #0a120a; color: #ddd; }}
  h1   {{ color: #53fc1b; margin-bottom: 4px; }}
  h2   {{ color: #888; font-size: .85rem; text-transform: uppercase; letter-spacing: .1em; margin-top: 2em; }}
  code {{ background: #111; color: #53fc1b; padding: 3px 10px; border-radius: 4px; word-break: break-all; }}
  ol   {{ line-height: 2.4; }}
  a    {{ color: #53fc1b; }}
</style>
</head>
<body>
<h1>KICK.com Kodi Add-on</h1>
<p>Repository for <strong>{ADDON_ID}</strong> &mdash; latest: <strong>v{version}</strong></p>

<h2>Installation via Kodi repository</h2>
<ol>
  <li>Kodi &rarr; <b>Settings &rarr; File Manager &rarr; Add source</b></li>
  <li>Enter URL: <code>{repo_url}</code> &nbsp; name it <code>KICK repo</code></li>
  <li><b>Add-ons &rarr; Install from zip file &rarr; KICK repo</b> &rarr; select the zip</li>
</ol>

<h2>Direct download</h2>
<p><a href="{ADDON_ID}/{zip_name}">{zip_name}</a></p>

<p><a href="https://github.com/zales/{ADDON_ID}">&larr; GitHub source</a></p>
</body>
</html>"""

with open(os.path.join(OUT_DIR, 'index.html'), 'w', encoding='utf-8') as f:
    f.write(html)

print(f'Built: {ADDON_ID} v{version}  MD5={md5}')
