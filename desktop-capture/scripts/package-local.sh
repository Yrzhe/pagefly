#!/usr/bin/env bash
#
# Build a local, unsigned DMG of PageFly Capture for personal use.
#
# The distribution-grade counterpart is `scripts/release.sh`, which needs a
# paid Apple Developer ID + notarytool credentials. This script skips all
# that: ad-hoc signed, no notarization, installs by drag-to-Applications.
#
# Output: dist/PageflyCapture-<version>.dmg
#
# Gatekeeper will refuse to launch an unsigned build on the first double
# click. The script prints the one-liner to clear the quarantine bit when
# it finishes.

set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
project_dir="$(dirname "$here")"
cd "$project_dir"

CONFIGURATION="${CONFIGURATION:-Release}"
OUTPUT_DIR="${OUTPUT_DIR:-$project_dir/dist}"
SCHEME="PageflyCapture"

for bin in xcodebuild xcodegen codesign hdiutil; do
    if ! command -v "$bin" >/dev/null 2>&1; then
        echo "error: required tool not found on PATH: $bin" >&2
        exit 1
    fi
done

mkdir -p "$OUTPUT_DIR"

echo "→ xcodegen"
xcodegen generate --quiet

# Pull the marketing version straight from the generated Info.plist so the
# DMG name matches CFBundleShortVersionString.
version="$(/usr/libexec/PlistBuddy -c "Print :CFBundleShortVersionString" \
    Resources/Info.plist 2>/dev/null || echo "dev")"

echo "→ xcodebuild build ($CONFIGURATION)"
derived="$OUTPUT_DIR/DerivedData"
xcodebuild \
    -project "$SCHEME.xcodeproj" \
    -scheme "$SCHEME" \
    -configuration "$CONFIGURATION" \
    -derivedDataPath "$derived" \
    -destination 'generic/platform=macOS' \
    build

app_built="$derived/Build/Products/$CONFIGURATION/$SCHEME.app"
if [[ ! -d "$app_built" ]]; then
    echo "error: build did not produce $app_built" >&2
    exit 1
fi

app_out="$OUTPUT_DIR/$SCHEME.app"
rm -rf "$app_out"
cp -R "$app_built" "$app_out"

# Pick a code-signing identity. Preference order:
#   1. $SIGN_ID env var (lets the user override explicitly)
#   2. The first "Apple Development" identity in the login keychain — these
#      have a stable Team ID, so macOS TCC keeps Accessibility/Microphone
#      grants across rebuilds. Far better than ad-hoc, which gets a fresh
#      cdhash every build and trips re-grant prompts every time.
#   3. Fallback: ad-hoc ("-"). Works but the user has to re-grant every
#      rebuild, which is what we're trying to avoid.
#
# This is still NOT the same as signing for distribution — for that you
# want a "Developer ID Application" cert + notarization (see release.sh).
ident_line="$(security find-identity -v -p codesigning 2>/dev/null \
    | grep -E 'Apple Development|Developer ID Application' | head -1)"
if [[ -n "${SIGN_ID:-}" ]]; then
    sign_target="${SIGN_ID}"
    echo "→ signing as: ${sign_target} (from \$SIGN_ID)"
elif [[ -n "$ident_line" ]]; then
    sign_target="$(echo "$ident_line" | awk '{print $2}')"
    sign_label="$(echo "$ident_line" | sed -E 's/^[^"]*"([^"]+)".*/\1/')"
    echo "→ signing with stable identity: ${sign_label}"
    echo "  (cdhash will change but Team ID stays — TCC keeps your grants)"
else
    sign_target="-"
    echo "→ no signing identity found in login keychain — falling back to ad-hoc"
    echo "  WARNING: every rebuild will require re-granting Accessibility / Microphone."
fi

# CRITICAL: pass --entitlements. A bare `codesign --force --deep --sign -`
# silently strips the entitlements Xcode baked in, which leaves the hardened
# runtime enforcing nothing — so the microphone/audio-input grants are
# missing and AVAudioRecorder.prepareToRecord() returns false. Re-sign with
# the entitlements file directly so the result is deterministic.
ent="$project_dir/Resources/PageflyCapture.entitlements"
codesign --force --deep --sign "$sign_target" -o runtime --entitlements "$ent" "$app_out"
codesign --verify --deep --strict --verbose=2 "$app_out" || true
# Sanity check: the microphone entitlement must be present, otherwise the
# next launch will silently break audio capture again.
if ! codesign -d --entitlements - "$app_out" 2>&1 | grep -q "com.apple.security.device.microphone"; then
    echo "error: re-signed bundle is missing the microphone entitlement" >&2
    exit 1
fi

# Stage a folder with the app + an /Applications alias so the DMG, when
# mounted, shows the familiar "drag X into Applications" layout.
stage="$OUTPUT_DIR/dmg-stage"
rm -rf "$stage"
mkdir -p "$stage"
cp -R "$app_out" "$stage/"
ln -s /Applications "$stage/Applications"

dmg_path="$OUTPUT_DIR/PageflyCapture-$version.dmg"
rm -f "$dmg_path"
echo "→ hdiutil create → $dmg_path"
hdiutil create \
    -volname "PageFly Capture" \
    -srcfolder "$stage" \
    -ov -format UDZO \
    "$dmg_path" >/dev/null

rm -rf "$stage"

echo ""
echo "OK. Built $dmg_path"
echo ""
echo "Install:"
echo "  1. open \"$dmg_path\""
echo "  2. Drag PageflyCapture.app into Applications."
echo "  3. First launch: right-click the app → Open, or run:"
echo "       xattr -dr com.apple.quarantine /Applications/PageflyCapture.app"
echo "     (the app is ad-hoc signed, so Gatekeeper warns on first double-click)."
