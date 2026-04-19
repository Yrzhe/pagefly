#!/usr/bin/env bash
#
# Build, sign, notarize, staple, package as DMG, and (optionally) push to
# GitHub Releases. The in-app UpdateChecker polls GitHub Releases every 6h
# and surfaces new tags in the About tab — so a successful run here is the
# only step needed to ship a build to existing installs.
#
# Usage:
#   ./scripts/release.sh <version>
#
#   ./scripts/release.sh 0.1.0                    # build + notarize + DMG
#   PUBLISH=1 ./scripts/release.sh 0.1.0          # also push to GitHub Releases
#   PUBLISH=1 DRAFT=1 ./scripts/release.sh 0.1.0  # publish as draft for review
#
# Required environment:
#   DEVELOPER_ID_APP          - "Developer ID Application: <Name> (TEAMID)"
#   NOTARY_KEYCHAIN_PROFILE   - profile name stored via `xcrun notarytool store-credentials`
#
# Optional environment:
#   CONFIGURATION             - xcodebuild configuration (default: Release)
#   OUTPUT_DIR                - output directory (default: ./dist)
#   PUBLISH                   - 1 to push artifacts to GitHub Releases via gh CLI
#   DRAFT                     - 1 to publish as a draft release (PUBLISH=1 only)
#   GITHUB_REPO               - owner/repo to release into (default: gh's current)
#
# Pre-flight (one-time) to register notarization credentials in the user's
# Keychain — far safer than putting an app-specific password in env vars:
#
#   xcrun notarytool store-credentials pagefly-notary \
#       --apple-id "you@example.com" \
#       --team-id "ABCDE12345" \
#       --password "<app-specific-password from appleid.apple.com>"

set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
project_dir="$(dirname "$here")"
cd "$project_dir"

CONFIGURATION="${CONFIGURATION:-Release}"
OUTPUT_DIR="${OUTPUT_DIR:-$project_dir/dist}"
SCHEME="PageflyCapture"
PUBLISH="${PUBLISH:-0}"
DRAFT="${DRAFT:-0}"

# ── Pre-flight ──────────────────────────────────────────────────────────
VERSION="${1:-}"
if [[ -z "$VERSION" ]]; then
    echo "usage: $0 <version>   (e.g. $0 0.1.0)" >&2
    exit 1
fi
# Reject anything that isn't strict semver — gh release uses the version
# as a tag, and bad characters there break the in-app updater later.
if ! [[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+(-[A-Za-z0-9.]+)?$ ]]; then
    echo "error: VERSION must be MAJOR.MINOR.PATCH (e.g. 0.1.0), got '$VERSION'" >&2
    exit 1
fi

: "${DEVELOPER_ID_APP:?Set DEVELOPER_ID_APP to your 'Developer ID Application: ... (TEAMID)' identity}"
: "${NOTARY_KEYCHAIN_PROFILE:?Set NOTARY_KEYCHAIN_PROFILE to a profile from xcrun notarytool store-credentials}"

required_bins=(xcodebuild xcodegen codesign ditto xcrun hdiutil)
if [[ "$PUBLISH" == "1" ]]; then
    required_bins+=(gh git)
fi
for bin in "${required_bins[@]}"; do
    if ! command -v "$bin" >/dev/null 2>&1; then
        echo "error: required tool not found on PATH: $bin" >&2
        exit 1
    fi
done

mkdir -p "$OUTPUT_DIR"

# ── Bump version ─────────────────────────────────────────────────────────
# Build number is the total commit count — monotonic, unique per build,
# and "what does the in-app updater compare?" stays straightforward
# because UpdateChecker reads CFBundleShortVersionString, not Version.
BUILD_NUMBER="$(git -C "$project_dir/.." rev-list --count HEAD 2>/dev/null || echo "1")"
echo "→ bumping version → CFBundleShortVersionString=$VERSION CFBundleVersion=$BUILD_NUMBER"
plist="$project_dir/Resources/Info.plist"
if [[ -f "$plist" ]]; then
    /usr/libexec/PlistBuddy -c "Set :CFBundleShortVersionString $VERSION" "$plist" 2>/dev/null \
        || /usr/libexec/PlistBuddy -c "Add :CFBundleShortVersionString string $VERSION" "$plist"
    /usr/libexec/PlistBuddy -c "Set :CFBundleVersion $BUILD_NUMBER" "$plist" 2>/dev/null \
        || /usr/libexec/PlistBuddy -c "Add :CFBundleVersion string $BUILD_NUMBER" "$plist"
fi
# project.yml is the canonical source — also patch it so the next
# `xcodegen` run doesn't roll the version back to whatever was stored.
sed -i.bak -E "s/(CFBundleShortVersionString:) \"[^\"]+\"/\1 \"$VERSION\"/" "$project_dir/project.yml"
sed -i.bak -E "s/(CFBundleVersion:) \"[^\"]+\"/\1 \"$BUILD_NUMBER\"/" "$project_dir/project.yml"
rm -f "$project_dir/project.yml.bak"

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

# ── Package as DMG ───────────────────────────────────────────────────────
# DMG is the Mac-native "drag this into Applications" flow — much friendlier
# than asking users to unzip + manually copy. The DMG itself is also
# stapled (the ticket lives in the .app inside) so Gatekeeper passes
# offline.
dmg_path="$OUTPUT_DIR/$SCHEME-$VERSION.dmg"
rm -f "$dmg_path"
stage="$OUTPUT_DIR/dmg-stage"
rm -rf "$stage"
mkdir -p "$stage"
cp -R "$app_path" "$stage/"
ln -s /Applications "$stage/Applications"
echo "→ hdiutil create → $dmg_path"
hdiutil create \
    -volname "PageFly Capture" \
    -srcfolder "$stage" \
    -ov -format UDZO \
    "$dmg_path" >/dev/null
rm -rf "$stage"

# ── Optionally publish to GitHub Releases ────────────────────────────────
if [[ "$PUBLISH" == "1" ]]; then
    tag="v$VERSION"
    repo_arg=()
    if [[ -n "${GITHUB_REPO:-}" ]]; then
        repo_arg=(--repo "$GITHUB_REPO")
    fi

    if gh release view "$tag" "${repo_arg[@]}" >/dev/null 2>&1; then
        echo "→ release $tag already exists — uploading artifacts (clobber)"
        gh release upload "$tag" "${repo_arg[@]}" --clobber "$dmg_path" "$zip_path"
    else
        draft_arg=()
        [[ "$DRAFT" == "1" ]] && draft_arg=(--draft)
        echo "→ gh release create $tag"
        # Pull recent commit messages as the release notes — short and
        # honest beats writing nothing. User can edit on the GitHub side
        # afterwards.
        notes_file="$(mktemp "${TMPDIR:-/tmp}/release-notes.XXXXXX")"
        trap 'rm -f "$notes_file"' EXIT
        {
            echo "## What's changed"
            echo ""
            git -C "$project_dir/.." log --pretty=format:'- %s' "$(git -C "$project_dir/.." describe --tags --abbrev=0 2>/dev/null || git -C "$project_dir/.." rev-list --max-parents=0 HEAD)..HEAD" \
                -- desktop-capture/ 2>/dev/null | head -30 || true
            echo ""
            echo "_Auto-generated by scripts/release.sh._"
        } > "$notes_file"

        gh release create "$tag" "${repo_arg[@]}" \
            --title "PageFly Capture $tag" \
            --notes-file "$notes_file" \
            "${draft_arg[@]}" \
            "$dmg_path" "$zip_path"
    fi
fi

echo ""
echo "OK. Release artifacts ready:"
echo "   app : $app_path"
echo "   zip : $zip_path"
echo "   dmg : $dmg_path"
if [[ "$PUBLISH" == "1" ]]; then
    echo "   gh  : pushed to release v$VERSION"
fi
