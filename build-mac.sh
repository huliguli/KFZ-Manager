#!/bin/bash
# Local macOS build — mirrors the CI "build-macos" job.
# Produces an ad-hoc-signed KFZManager.app packed into a .dmg (+ .sha256).
# Requires macOS with the project's Python deps installed (pip install -r requirements.txt).
set -e
cd "$(dirname "$0")"

echo "==> App-Icon (.icns)"
python3 tools/make_icns.py
iconutil -c icns -o assets/app.icns build/AppIcon.iconset

echo "==> PyInstaller (.app)"
python3 -m PyInstaller --noconfirm --clean KFZManager.spec

echo "==> Ad-hoc signieren"
codesign --force --deep --sign - dist/KFZManager.app
codesign --verify --deep --strict dist/KFZManager.app || echo "codesign verify: Hinweis (ad-hoc)"

echo "==> Disk-Image (.dmg)"
rm -rf dist/dmg && mkdir -p dist/dmg
cp -R dist/KFZManager.app dist/dmg/
ln -s /Applications dist/dmg/Applications
hdiutil create -volname "KFZManager" -srcfolder dist/dmg \
  -ov -format UDZO dist/KFZManager-macOS.dmg
shasum -a 256 dist/KFZManager-macOS.dmg | awk '{print $1}' | tr -d '\n' \
  > dist/KFZManager-macOS.dmg.sha256

echo "==> Fertig: dist/KFZManager-macOS.dmg"
