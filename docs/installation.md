# Installation

This plugin is designed to run from a local source checkout and can also be packed into a clean plugin zip.

## Source Install

```bash
git clone git@github.com:AmrMohamad/Xcoder.git /Users/amrmohamad/Developer/Xcoder
cd /Users/amrmohamad/Developer/Xcoder
chmod +x bin/xcode
bin/xcode --version
bin/xcode doctor --json
```

## Marketplace Registration

Add an entry for the plugin without deleting existing marketplace entries:

```json
{
  "name": "xcode",
  "path": "/Users/amrmohamad/Developer/Xcoder",
  "category": "Developer Tools"
}
```

If your local marketplace resolves paths from `/Users/amrmohamad`, this relative path is also valid:

```json
{
  "name": "xcode",
  "path": "./Developer/Xcoder",
  "category": "Developer Tools"
}
```

## Cache Install

Codex may cache local plugins under:

```text
/Users/amrmohamad/.codex/plugins/cache/local/xcode/0.3.0
```

To refresh that cache from the source checkout:

```bash
SOURCE=/Users/amrmohamad/Developer/Xcoder
CACHE=/Users/amrmohamad/.codex/plugins/cache/local/xcode/0.3.0

rsync -a --delete \
  --exclude ".git" \
  --exclude "__pycache__" \
  --exclude ".DS_Store" \
  --exclude ".build" \
  --exclude ".codex/xcode/artifacts" \
  "$SOURCE/" "$CACHE/"

cd "$CACHE"
bin/xcode --version
bin/xcode doctor --json
python3 -m py_compile scripts/*.py
```

## Optional Native Helper

The Swift helper is optional. It improves native macOS/Xcode state sensing, but normal build, simulator, results, warnings, and context commands do not require it.

Rebuild it when the binary is missing, wrong architecture, or blocked by local trust state:

```bash
cd /Users/amrmohamad/Developer/Xcoder/native/XcodeNativeHelper
swift build -c release
cp .build/release/xcode-native-helper ../../bin/xcode-native-helper
chmod +x ../../bin/xcode-native-helper

cd /Users/amrmohamad/Developer/Xcoder
bin/xcode native helper version --json
bin/xcode native permissions status --json
bin/xcode native app xcode-state --json
```

`native permissions status` does not trigger a macOS prompt. `native permissions request` is the explicit command that asks macOS to show the Accessibility permission prompt.

## Package Install

Create a clean zip:

```bash
cd /Users/amrmohamad/Developer/Xcoder
bin/xcode package zip --output /tmp/xcode-plugin-0.3.0.zip --json
bin/xcode package audit --zip /tmp/xcode-plugin-0.3.0.zip --json
```

The package command writes entries under:

```text
xcode/0.3.0/
```

The audit fails if the archive contains macOS metadata, Python caches, Swift `.build` output, local artifacts, nested zips, wrong root prefixes, missing package manifest, missing public binaries, or non-executable public binaries.
