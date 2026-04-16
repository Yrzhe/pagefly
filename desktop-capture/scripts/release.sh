#!/usr/bin/env bash
#
# Build, sign, notarize, and staple a release of PageFly Capture.
#
# Required environment:
#   DEVELOPER_ID_APP            - "Developer ID Application: <Name> (TEAMID)"
#   NOTARY_KEYCHAIN_PROFILE     - profile name stored via `xcrun notarytool store-credentials`
#
# Optional environment:
#   CONFIGURATION               - xcodebuild configuration (default: Release)
#   OUTPUT_DIR                  - output directory (default: ./dist)
#
# Typical invocation:
#   DEVELOPER_ID_APP="Developer ID Application: Your Name (ABCDE12345)" \
#   NOTARY_KEYCHAIN_PROFILE="pagefly-notary" \
#   ./scripts/release.sh
#
# Pre-flight (one-time) to register notarization credentials:
#   xcrun notarytool store-credentials pagefly-notary \
#       --apple-id "you@example.com" \
#       --team-id "ABCDE12345" \
#       --password "<app-specific-password>"

set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
project_dir="$(dirname "$here")"
cd "$project_dir"

CONFIGURATION="${CONFIGURATION:-Release}"
OUTPUT_DIR="${OUTPUT_DIR:-$project_dir/dist}"
SCHEME="PageflyCapture"

# ── Pre-flight ──────────────────────────────────────────────────────────
: "${DEVELOPER_ID_APP:?Set DEVELOPER_ID_APP to your 'Developer ID Application: ... (TEAMID)' identity}"
: "${NOTARY_KEYCHAIN_PROFILE:?Set NOTARY_KEYCHAIN_PROFILE to a profile from xcrun notarytool store-credentials}"

for bin in xcodebuild xcodegen codesign ditto xcrun; do
    if ! command -v "$bin" >/dev/null 2>&1; then
        echo "error: required tool not found on PATH: $bin" >&2
        exit 1
    fi
done

mkdir -p "$OUTPUT_DIR"

# ── Regenerate project ───────────────────────────────────────────────────
echo "→ xcodegen"
xcodegen generate --quiet

# ── Archive ──────────────────────────────────────────────────────────────
archive_path="$OUTPUT_DIR/$SCHEME.xcarchive"
rm -rf "$archive_path"
echo "→ xcodebuild archive ($CONFIGURATION)"
# Run xcodebuild directly (no xcpretty pipe) so `set -e` honors a failing
# archive instead of relying on a stale-directory check.
xcodebuild \
    -project "$SCHEME.xcodeproj" \
    -scheme "$SCHEME" \
    -configuration "$CONFIGURATION" \
    -archivePath "$archive_path" \
    -destination 'generic/platform=macOS' \
    CODE_SIGN_IDENTITY="$DEVELOPER_ID_APP" \
    CODE_SIGN_STYLE=Manual \
    archive

if [[ ! -d "$archive_path" ]]; then
    echo "error: archive did not produce $archive_path" >&2
    exit 1
fi

# ── Export ───────────────────────────────────────────────────────────────
# Build the export plist via plutil so any `&`, `<`, `>`, or whitespace in
# a Developer ID identity string is handled as data rather than interpolated
# into XML.
export_plist="$(mktemp "${TMPDIR:-/tmp}/pagefly-export.XXXXXX").plist"
trap 'rm -f "$export_plist"' EXIT
plutil -create xml1 "$export_plist"
plutil -insert method -string "developer-id" "$export_plist"
plutil -insert signingStyle -string "manual" "$export_plist"
plutil -insert signingCertificate -string "$DEVELOPER_ID_APP" "$export_plist"

export_dir="$OUTPUT_DIR/export"
rm -rf "$export_dir"
echo "→ xcodebuild -exportArchive"
xcodebuild \
    -exportArchive \
    -archivePath "$archive_path" \
    -exportPath "$export_dir" \
    -exportOptionsPlist "$export_plist"

app_path="$export_dir/$SCHEME.app"
if [[ ! -d "$app_path" ]]; then
    echo "error: export did not produce $app_path" >&2
    exit 1
fi

# ── Verify signature before notarization ─────────────────────────────────
echo "→ codesign --verify"
codesign --verify --deep --strict --verbose=2 "$app_path"

# ── Zip for notarization ─────────────────────────────────────────────────
zip_path="$OUTPUT_DIR/$SCHEME.zip"
rm -f "$zip_path"
echo "→ ditto zip → $zip_path"
ditto -c -k --keepParent "$app_path" "$zip_path"

# ── Notarize ─────────────────────────────────────────────────────────────
echo "→ notarytool submit (this waits for Apple)"
xcrun notarytool submit "$zip_path" \
    --keychain-profile "$NOTARY_KEYCHAIN_PROFILE" \
    --wait

# ── Staple ───────────────────────────────────────────────────────────────
echo "→ stapler staple"
xcrun stapler staple "$app_path"
xcrun stapler validate "$app_path"

# Re-zip the stapled app so distribution archive matches what Apple verified.
rm -f "$zip_path"
ditto -c -k --keepParent "$app_path" "$zip_path"

echo ""
echo "OK. Release artifacts ready:"
echo "   app : $app_path"
echo "   zip : $zip_path"
