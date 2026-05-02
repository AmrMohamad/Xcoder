# Installation

This plugin is designed to install through a Codex plugin marketplace, run from a local source checkout while developing, and package into a clean plugin zip.

The repository root is the plugin root. It must contain `.codex-plugin/plugin.json`, `skills/`, `bin/xcode`, and the supporting scripts/assets.

## Install From GitHub Marketplace

The repository includes a marketplace file at `.agents/plugins/marketplace.json`. Add that marketplace to Codex:

```bash
codex plugin marketplace add AmrMohamad/Xcoder --ref main --sparse .agents/plugins
codex plugin marketplace upgrade xcoder
```

Then open the plugin directory and install the `xcode` plugin:

```bash
codex
/plugins
```

Choose the Xcoder marketplace, open `xcode`, and install it. After installation, start a new Codex thread and invoke it with `@xcode` or one of its bundled skills.

## Local Development Checkout

Clone the repo anywhere:

```bash
git clone git@github.com:AmrMohamad/Xcoder.git
cd Xcoder
chmod +x bin/xcode
bin/xcode --version
bin/xcode doctor --json
```

## Local Marketplace Registration

For an unpacked checkout, add or update a marketplace file such as `$REPO_ROOT/.agents/plugins/marketplace.json` or a personal marketplace file. Keep existing marketplace entries and add one plugin object:

```json
{
  "name": "xcode",
  "source": {
    "source": "local",
    "path": "./"
  },
  "policy": {
    "installation": "AVAILABLE",
    "authentication": "NONE"
  },
  "category": "Developer Tools"
}
```

`source.path` is resolved relative to the marketplace root, must start with `./`, and must stay inside that root. When the plugin lives somewhere else, either copy it under the marketplace root or use the Git-backed marketplace install above.

## Cache Refresh For Development

Codex installs plugins into its plugin cache. For local development, prefer reinstalling or upgrading the marketplace through Codex. If you need to refresh a local cache manually, use environment variables instead of machine-specific paths:

```bash
SOURCE="$(pwd)"
CACHE="${CODEX_HOME:-$HOME/.codex}/plugins/cache/local/xcode/0.3.0"

mkdir -p "$CACHE"
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

Do not edit the cache as the source of truth. Make changes in the repository checkout, validate them there, then refresh or reinstall the plugin.

## Optional Native Helper

The Swift helper is optional. It improves native macOS/Xcode state sensing, but normal build, simulator, results, warnings, and context commands do not require it.

Rebuild it from the repository root when the binary is missing, wrong architecture, or blocked by local trust state:

```bash
cd native/XcodeNativeHelper
swift build -c release
cp .build/release/xcode-native-helper ../../bin/xcode-native-helper
chmod +x ../../bin/xcode-native-helper

cd ../..
bin/xcode native helper version --json
bin/xcode native permissions status --json
bin/xcode native app xcode-state --json
```

`native permissions status` does not trigger a macOS prompt. `native permissions request` is the explicit command that asks macOS to show the Accessibility permission prompt.

## Package Install

Create a clean zip from the repository root:

```bash
bin/xcode package zip --output /tmp/xcode-plugin-0.3.0.zip --json
bin/xcode package audit --zip /tmp/xcode-plugin-0.3.0.zip --json
```

The package command writes entries under:

```text
xcode/0.3.0/
```

The audit fails if the archive contains macOS metadata, Python caches, Swift `.build` output, local artifacts, nested zips, wrong root prefixes, missing package manifest, missing public binaries, or non-executable public binaries.

## OpenAI Plugin Format Notes

Xcoder follows the Codex plugin structure documented by OpenAI:

- `.codex-plugin/plugin.json` is the required plugin manifest.
- Marketplace files live at `.agents/plugins/marketplace.json` for repo-scoped catalogs or in a personal marketplace location.
- Local marketplace entries use `source: { "source": "local", "path": "./..." }`.
- Git-backed marketplace entries can use `source: "url"` when the plugin lives at the repository root.
- Manifest paths such as `skills` and `logo` stay relative to the plugin root and start with `./`.
