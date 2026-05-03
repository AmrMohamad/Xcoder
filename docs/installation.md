# Installation

This plugin is designed to install through a Codex plugin marketplace, run from a local source checkout while developing, and package into a clean plugin zip.

The repository root is the plugin root. It must contain `.codex-plugin/plugin.json`, `skills/`, `bin/xcode`, and the supporting scripts/assets.

## Requirements

The Swift native helper and bundled Swift MCP server require macOS 14.0 or newer. This is enforced in two places:

- `bin/xcode-mcp` checks `sw_vers -productVersion` before launching `bin/xcode-mcp-server`.
- `bin/xcode doctor --json` reports `host-macos-minimum`, and the MCP server reports `mcp-server-minimum-macos` plus `mcp-server-host-macos-supported`.

Older macOS hosts should fail early with a clear message instead of trying to launch an incompatible Swift binary.

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

Explicit `@xcode` invocation is GUI-first. Codex should inspect and control Xcode.app through `bin/xcode native ...` and `bin/xcode ide ...` before falling back to `bin/xcode build ...`.

## Local Development Checkout

Clone the repo anywhere:

```bash
git clone git@github.com:AmrMohamad/Xcoder.git
cd Xcoder
chmod +x bin/xcode
bin/xcode --version
bin/xcode doctor --json
```

## First-Use MCP Bootstrap

When Codex uses this plugin for the first time, it must make the bundled MCP server usable before relying on Xcode workflows. The required path is:

```bash
bin/xcode mcp bootstrap --json
```

That single action validates `.codex-plugin/plugin.json` and `.mcp.json`, compiles `scripts/*.py`, builds `native/XcodeMCPServer`, installs `bin/xcode-mcp-server`, makes `bin/xcode`, `bin/xcode-mcp`, and `bin/xcode-mcp-server` executable, runs MCP self-checks, and runs `bin/xcode doctor --json`.

Then restart Codex so `.mcp.json` is reloaded.

Use the complete runbook in [First-Use MCP Bootstrap](first-use-mcp.md). If this still fails after local repair, report it at [AmrMohamad/Xcoder issues](https://github.com/AmrMohamad/Xcoder/issues) with compact redacted diagnostics.

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
CACHE="${CODEX_HOME:-$HOME/.codex}/plugins/cache/local/xcode/0.4.0"

mkdir -p "$CACHE"
rsync -a --delete \
  --exclude ".git" \
  --exclude "__pycache__" \
  --exclude ".DS_Store" \
  --exclude ".build" \
  --exclude ".swiftpm" \
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

## Bundled MCP Server

Xcoder v0.4.0 ships a Swift stdio MCP server. Build it once and copy the release binary into `bin/`:

```bash
swift build -c release --package-path native/XcodeMCPServer
cp native/XcodeMCPServer/.build/release/xcode-mcp-server bin/xcode-mcp-server
chmod +x bin/xcode-mcp bin/xcode-mcp-server
bin/xcode-mcp-server --version --json
bin/xcode-mcp-server --list-tools --json
bin/xcode-mcp-server --doctor --json
```

`.mcp.json` points Codex at `./bin/xcode-mcp`, which is only a wrapper around the built `bin/xcode-mcp-server`. Do not point `.mcp.json` at `swift run`; that makes tool startup slow and dependent on local build state.

The wrapper also enforces the macOS 14.0 minimum before it executes the Swift binary.

## Package Install

Create a clean zip from the repository root:

```bash
bin/xcode package zip --output /tmp/xcode-plugin-0.4.0.zip --json
bin/xcode package audit --zip /tmp/xcode-plugin-0.4.0.zip --json
```

The package command writes entries under:

```text
xcode/0.4.0/
```

The audit fails if the archive contains macOS metadata, Python caches, Swift `.build` output, local artifacts, nested zips, wrong root prefixes, missing package manifest, missing public binaries, or non-executable public binaries.

## OpenAI Plugin Format Notes

Xcoder follows the Codex plugin structure documented by OpenAI:

- `.codex-plugin/plugin.json` is the required plugin manifest.
- Marketplace files live at `.agents/plugins/marketplace.json` for repo-scoped catalogs or in a personal marketplace location.
- Local marketplace entries use `source: { "source": "local", "path": "./..." }`.
- Git-backed marketplace entries can use `source: "url"` when the plugin lives at the repository root.
- Manifest paths such as `skills`, `hooks`, `mcpServers`, and `logo` stay relative to the plugin root and start with `./`.
- `.mcp.json` uses Codex's MCP config shape: `{"mcpServers": {"xcode": {"command": "./bin/xcode-mcp", "args": ["--stdio"]}}}`.
- When a local cache version is replaced, make sure any personal local marketplace entry no longer points at the old deleted cache directory.
