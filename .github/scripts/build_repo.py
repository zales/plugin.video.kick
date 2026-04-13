#!/usr/bin/env python3
"""Build Kodi repository structure for GitHub Pages deployment."""
import hashlib
import os
import shutil
import sys
import zipfile
import xml.etree.ElementTree as ET

ADDON_ID = 'plugin.video.kick'
REPO_ID  = 'repository.zales.kick'
OUT_DIR  = 'repo_output'

version      = sys.argv[1] if len(sys.argv) > 1 else 'unknown'
zip_name     = f'{ADDON_ID}-{version}.zip'
repo_zip     = f'{REPO_ID}-1.0.0.zip'
addon_out    = os.path.join(OUT_DIR, ADDON_ID)
repo_out_dir = os.path.join(OUT_DIR, REPO_ID)

os.makedirs(addon_out, exist_ok=True)
os.makedirs(repo_out_dir, exist_ok=True)

# --- plugin.video.kick ---
if os.path.exists(zip_name):
    shutil.copy(zip_name, os.path.join(addon_out, zip_name))
for fname in ('addon.xml', 'icon.png', 'fanart.jpg'):
    if os.path.exists(fname):
        shutil.copy(fname, os.path.join(addon_out, fname))

# --- repository.zales.kick zip ---
repo_addon_xml = os.path.join(REPO_ID, 'addon.xml')
repo_zip_path  = os.path.join(repo_out_dir, repo_zip)
with zipfile.ZipFile(repo_zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
    zf.write(repo_addon_xml, f'{REPO_ID}/addon.xml')
    if os.path.exists(f'{REPO_ID}/icon.png'):
        zf.write(f'{REPO_ID}/icon.png', f'{REPO_ID}/icon.png')
shutil.copy(repo_addon_xml, os.path.join(repo_out_dir, 'addon.xml'))

# --- addons.xml (includes both addons) ---
addons_el = ET.Element('addons')
for xml_path in (os.path.join(ADDON_ID, 'addon.xml') if os.path.exists(os.path.join(ADDON_ID, 'addon.xml')) else 'addon.xml',
                 repo_addon_xml):
    if os.path.exists(xml_path):
        addons_el.append(ET.parse(xml_path).getroot())
    else:
        addons_el.append(ET.parse('addon.xml' if xml_path.endswith(f'{ADDON_ID}/addon.xml') else xml_path).getroot())

# plugin addon.xml is in workspace root
addons_el2 = ET.Element('addons')
addons_el2.append(ET.parse('addon.xml').getroot())
addons_el2.append(ET.parse(repo_addon_xml).getroot())
ET.indent(addons_el2, space='    ')
body       = ET.tostring(addons_el2, encoding='unicode')
addons_xml = f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n{body}\n'

with open(os.path.join(OUT_DIR, 'addons.xml'), 'w', encoding='utf-8') as f:
    f.write(addons_xml)

md5 = hashlib.md5(addons_xml.encode('utf-8')).hexdigest()
with open(os.path.join(OUT_DIR, 'addons.xml.md5'), 'w') as f:
    f.write(md5)

# --- stable shortlinks ---
shutil.copy(repo_zip_path, os.path.join(OUT_DIR, 'repo.zip'))
plugin_zip_src = os.path.join(addon_out, zip_name)
if os.path.exists(plugin_zip_src):
    shutil.copy(plugin_zip_src, os.path.join(OUT_DIR, 'plugin.zip'))

# --- static files ---
open(os.path.join(OUT_DIR, '.nojekyll'), 'w').close()

repo_url        = 'https://kodi.zales.dev'
repo_zip_url    = f'{repo_url}/{REPO_ID}/{repo_zip}'
repo_short_url  = f'{repo_url}/repo.zip'
plugin_zip_url  = f'{repo_url}/plugin.zip'
html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>KICK.com Kodi Repository</title>
<style>
  body {{ font-family: sans-serif; max-width: 720px; margin: 60px auto; padding: 0 20px; background: #0a120a; color: #ddd; }}
  h1   {{ color: #53fc1b; margin-bottom: 4px; }}
  h2   {{ color: #888; font-size: .85rem; text-transform: uppercase; letter-spacing: .1em; margin-top: 2em; }}
  code {{ background: #111; color: #53fc1b; padding: 3px 10px; border-radius: 4px; word-break: break-all; display:inline-block; }}
  ol   {{ line-height: 2.4; }}
  a    {{ color: #53fc1b; }}
</style>
</head>
<body>
<h1>KICK.com Kodi Add-on</h1>
<p>Latest: <strong>v{version}</strong> &nbsp;&bull;&nbsp; <a href="https://github.com/zales/{ADDON_ID}/releases">All releases</a></p>

<h2>1 — Install the repository (one-time)</h2>
<ol>
  <li>Download: <a href="{repo_short_url}">repo.zip</a> &nbsp;<code>{repo_short_url}</code></li>
  <li>Kodi &rarr; <b>Add-ons &rarr; Install from zip file</b> &rarr; select the downloaded zip</li>
</ol>

<h2>2a — Install via repository (recommended — auto-updates)</h2>
<ol>
  <li>Kodi &rarr; <b>Add-ons &rarr; Install from repository &rarr; KICK.com Repository</b></li>
  <li>Select <b>Video add-ons &rarr; KICK.com</b> &rarr; Install</li>
  <li>The add-on will update automatically from now on</li>
</ol>

<h2>2b — Install plugin directly (no auto-updates)</h2>
<ol>
  <li>Download: <a href="{plugin_zip_url}">plugin.zip</a> &nbsp;<code>{plugin_zip_url}</code></li>
  <li>Kodi &rarr; <b>Add-ons &rarr; Install from zip file</b> &rarr; select the downloaded zip</li>
</ol>

<p><a href="https://github.com/zales/{ADDON_ID}">&larr; GitHub source</a></p>
</body>
</html>"""

with open(os.path.join(OUT_DIR, 'index.html'), 'w', encoding='utf-8') as f:
    f.write(html)

print(f'Built: {ADDON_ID} v{version}, {REPO_ID}  MD5={md5}')
