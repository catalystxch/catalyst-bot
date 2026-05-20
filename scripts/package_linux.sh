#!/usr/bin/env bash
set -euo pipefail

release_ref="${1:?release tag required, e.g. v1.2.36}"
version="${release_ref#v}"
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
bundle_dir="$root/dist/Catalyst"
appdir="$root/build/AppDir"
deb_root="$root/build/deb/catalyst_${version}_amd64"
appimage_path="$root/Catalyst-linux-${release_ref}-x86_64.AppImage"
deb_path="$root/catalyst_${release_ref}_amd64.deb"

if [[ ! -x "$bundle_dir/Catalyst" ]]; then
  echo "Linux PyInstaller binary not found: $bundle_dir/Catalyst" >&2
  exit 1
fi

rm -rf "$appdir" "$deb_root" "$appimage_path" "${appimage_path}.sha256" "$deb_path" "${deb_path}.sha256"

install -d "$appdir/usr/lib/catalyst"
cp -a "$bundle_dir/." "$appdir/usr/lib/catalyst/"
chmod +x "$appdir/usr/lib/catalyst/Catalyst"

cat > "$appdir/AppRun" <<'APPRUN'
#!/usr/bin/env sh
set -eu
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/usr/lib/catalyst/Catalyst" "$@"
APPRUN
chmod +x "$appdir/AppRun"

install -d "$appdir/usr/share/applications" "$appdir/usr/share/icons/hicolor/256x256/apps" "$appdir/usr/share/metainfo"
install -m 0644 "$root/assets/bot_icon_new.png" "$appdir/usr/share/icons/hicolor/256x256/apps/catalyst.png"
cp "$appdir/usr/share/icons/hicolor/256x256/apps/catalyst.png" "$appdir/catalyst.png"
cp "$appdir/usr/share/icons/hicolor/256x256/apps/catalyst.png" "$appdir/.DirIcon"

cat > "$appdir/catalyst.desktop" <<'DESKTOP'
[Desktop Entry]
Type=Application
Name=CATalyst
Comment=Chia liquidity market maker
Exec=AppRun
Icon=catalyst
Terminal=false
Categories=Finance;Network;
DESKTOP
cp "$appdir/catalyst.desktop" "$appdir/usr/share/applications/catalyst.desktop"

cat > "$appdir/usr/share/metainfo/com.monkeyzoo.catalyst.metainfo.xml" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<component type="desktop-application">
  <id>com.monkeyzoo.catalyst</id>
  <name>CATalyst</name>
  <summary>Chia CAT liquidity market maker</summary>
  <metadata_license>MIT</metadata_license>
  <project_license>MIT</project_license>
  <launchable type="desktop-id">catalyst.desktop</launchable>
  <url type="homepage">https://catalystxch.com/</url>
  <url type="bugtracker">https://github.com/catalystxch/catalyst-bot/issues</url>
  <provides>
    <binary>Catalyst</binary>
  </provides>
  <releases>
    <release version="${version}" date="$(date -u +%Y-%m-%d)" />
  </releases>
</component>
EOF

if command -v desktop-file-validate >/dev/null 2>&1; then
  desktop-file-validate "$appdir/catalyst.desktop"
fi

tool="${APPIMAGETOOL:-$root/build/appimagetool-x86_64.AppImage}"
if [[ ! -x "$tool" ]]; then
  mkdir -p "$(dirname "$tool")"
  curl -L \
    -o "$tool" \
    https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-x86_64.AppImage
  chmod +x "$tool"
fi

ARCH=x86_64 APPIMAGE_EXTRACT_AND_RUN=1 "$tool" "$appdir" "$appimage_path"
chmod +x "$appimage_path"
appimage_digest="$(sha256sum "$appimage_path" | awk '{print $1}')"
printf "%s  %s\n" "$appimage_digest" "$(basename "$appimage_path")" > "${appimage_path}.sha256"

install -d "$deb_root/DEBIAN" "$deb_root/opt/catalyst" "$deb_root/usr/bin" "$deb_root/usr/share/applications" "$deb_root/usr/share/icons/hicolor/256x256/apps"
cp -a "$bundle_dir/." "$deb_root/opt/catalyst/"
chmod +x "$deb_root/opt/catalyst/Catalyst"
cat > "$deb_root/usr/bin/catalyst" <<'WRAPPER'
#!/usr/bin/env sh
set -eu
exec /opt/catalyst/Catalyst "$@"
WRAPPER
chmod +x "$deb_root/usr/bin/catalyst"
install -m 0644 "$root/assets/bot_icon_new.png" "$deb_root/usr/share/icons/hicolor/256x256/apps/catalyst.png"
cat > "$deb_root/usr/share/applications/catalyst.desktop" <<'DESKTOP'
[Desktop Entry]
Type=Application
Name=CATalyst
Comment=Chia liquidity market maker
Exec=catalyst
Icon=catalyst
Terminal=false
Categories=Finance;Network;
DESKTOP

installed_size="$(du -sk "$deb_root" | cut -f1)"
cat > "$deb_root/DEBIAN/control" <<EOF
Package: catalyst
Version: ${version}
Section: net
Priority: optional
Architecture: amd64
Maintainer: MonkeyZoo <support@catalystxch.com>
Installed-Size: ${installed_size}
Depends: ca-certificates, libgtk-3-0, libwebkit2gtk-4.1-0 | libwebkit2gtk-4.0-37, libnotify4, libnotify-bin, xdg-utils, libdbus-1-3, libegl1, libgl1, libgbm1, libnss3, libx11-xcb1, libxcb1, libxcb-cursor0, libxcb-icccm4, libxcb-image0, libxcb-keysyms1, libxcb-randr0, libxcb-render-util0, libxcb-shape0, libxcb-shm0, libxcb-sync1, libxcb-xfixes0, libxcb-xinerama0, libxcb-xkb1, libxcomposite1, libxdamage1, libxkbcommon-x11-0, libxrandr2
Homepage: https://catalystxch.com/
Description: CATalyst Chia CAT liquidity market maker
 CATalyst is a local desktop market-making app for Chia CAT tokens.
 It connects to Sage Wallet over local RPC and keeps offer ladders live.
EOF

if command -v desktop-file-validate >/dev/null 2>&1; then
  desktop-file-validate "$deb_root/usr/share/applications/catalyst.desktop"
fi

dpkg-deb --build --root-owner-group "$deb_root" "$deb_path"
deb_digest="$(sha256sum "$deb_path" | awk '{print $1}')"
printf "%s  %s\n" "$deb_digest" "$(basename "$deb_path")" > "${deb_path}.sha256"

echo "Created $appimage_path"
echo "Created ${appimage_path}.sha256"
echo "Created $deb_path"
echo "Created ${deb_path}.sha256"
