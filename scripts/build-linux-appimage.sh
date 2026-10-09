#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
SPEC_FILE="$ROOT_DIR/packaging/linux/open-structural-analysis.spec"
APPDIR="$ROOT_DIR/packaging/linux/AppDir"
PYINSTALLER_DIST="$ROOT_DIR/dist/open-structural-analysis"
VERSION="${OSA_VERSION:-2026.1}"
OUTPUT="$ROOT_DIR/dist/OpenStructuralAnalysis-${VERSION}-x86_64.AppImage"
RUNTIME_FILE="$ROOT_DIR/build-tools/runtime-x86_64"

if [[ -z "${APPIMAGE_TOOL:-}" ]]; then
    if [[ -x "$ROOT_DIR/build-tools/appimagetool-x86_64.AppImage" ]]; then
        APPIMAGE_TOOL="$ROOT_DIR/build-tools/appimagetool-x86_64.AppImage"
    else
        APPIMAGE_TOOL="appimagetool"
    fi
fi

cd "$ROOT_DIR"

if ! command -v "$APPIMAGE_TOOL" >/dev/null 2>&1; then
    echo "appimagetool não encontrado; defina APPIMAGE_TOOL ou instale-o antes de continuar." >&2
    exit 1
fi

UV_CACHE_DIR="${UV_CACHE_DIR:-/tmp/osa-uv-cache}"
export UV_CACHE_DIR

uv run pyinstaller --noconfirm --clean "$SPEC_FILE"

rm -rf "$APPDIR/usr"
rm -f "$APPDIR/.DirIcon" "$OUTPUT"
mkdir -p \
    "$APPDIR/usr/lib/openstructuralanalysis" \
    "$APPDIR/usr/bin" \
    "$APPDIR/usr/share/icons/hicolor/scalable/apps" \
    "$APPDIR/usr/share/icons/hicolor/256x256/apps"

cp -a "$PYINSTALLER_DIST/." "$APPDIR/usr/lib/openstructuralanalysis/"
ln -s ../lib/openstructuralanalysis/open-structural-analysis \
    "$APPDIR/usr/bin/open-structural-analysis"
cp "$ROOT_DIR/osa/resources/icons/openstructuralanalysis.svg" \
    "$APPDIR/openstructuralanalysis.svg"

QT_QPA_PLATFORM=offscreen uv run python scripts/render-appimage-icon.py \
    "$APPDIR/openstructuralanalysis.svg" \
    "$APPDIR/.DirIcon"
cp "$APPDIR/openstructuralanalysis.svg" \
    "$APPDIR/usr/share/icons/hicolor/scalable/apps/openstructuralanalysis.svg"
cp "$APPDIR/.DirIcon" \
    "$APPDIR/usr/share/icons/hicolor/256x256/apps/openstructuralanalysis.png"

case "$APPIMAGE_TOOL" in
    *.AppImage)
        # O ambiente de desenvolvimento pode não ter FUSE habilitado. O
        # modo extract-and-run usa o runtime interno do appimagetool.
        if [[ -f "$RUNTIME_FILE" ]]; then
            "$APPIMAGE_TOOL" --appimage-extract-and-run \
                --runtime-file "build-tools/runtime-x86_64" \
                "packaging/linux/AppDir" "dist/OpenStructuralAnalysis-${VERSION}-x86_64.AppImage"
        else
            "$APPIMAGE_TOOL" --appimage-extract-and-run \
                "packaging/linux/AppDir" "dist/OpenStructuralAnalysis-${VERSION}-x86_64.AppImage"
        fi
        ;;
    *)
        "$APPIMAGE_TOOL" "$APPDIR" "$OUTPUT"
        ;;
esac
echo "AppImage criado em: $OUTPUT"
