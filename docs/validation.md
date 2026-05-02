# Validation

Run these checks before publishing or refreshing the Codex cache.

## Source Validation

```bash
cd /Users/amrmohamad/Developer/Xcoder

python3 -m json.tool .codex-plugin/plugin.json >/dev/null
python3 -m py_compile scripts/*.py
test -x bin/xcode
bin/xcode --help
bin/xcode --version
bin/xcode doctor --json
```

## Package Validation

```bash
cd /Users/amrmohamad/Developer/Xcoder

bin/xcode package zip --output /tmp/xcode-plugin-0.3.0.zip --json
bin/xcode package audit --zip /tmp/xcode-plugin-0.3.0.zip --json
```

Manual structure check:

```bash
python3 - <<'PY'
import stat
import zipfile

path = "/tmp/xcode-plugin-0.3.0.zip"
with zipfile.ZipFile(path) as archive:
    names = archive.namelist()
    print("entry_count", len(names))
    print("expected_prefix_only", all(name.startswith("xcode/0.3.0/") for name in names))
    print("manifest", "xcode/0.3.0/package-manifest.json" in names)
    print("has_docs_hero", "xcode/0.3.0/docs/images/xcoder-hero.png" in names)
    bad = [
        name for name in names
        if any(part in name for part in [
            "__MACOSX",
            ".DS_Store",
            "__pycache__",
            ".codex/xcode/artifacts",
            ".build",
            "DerivedData",
        ])
        or name.endswith(".zip")
        or name.endswith(".zip.manifest.json")
    ]
    print("bad_entries", len(bad))
    for name in ["xcode/0.3.0/bin/xcode", "xcode/0.3.0/bin/xcode-native-helper"]:
        info = archive.getinfo(name)
        mode = (info.external_attr >> 16) & 0o777777
        print(name, oct(mode), stat.filemode(mode))
PY
```

Expected:

```text
entry_count 42
expected_prefix_only True
manifest True
has_docs_hero True
bad_entries 0
xcode/0.3.0/bin/xcode 0o100755 -rwxr-xr-x
xcode/0.3.0/bin/xcode-native-helper 0o100755 -rwxr-xr-x
```

## Cache Validation

```bash
cd /Users/amrmohamad/.codex/plugins/cache/local/xcode/0.3.0

bin/xcode --version
bin/xcode doctor --json
python3 -m py_compile scripts/*.py
bin/xcode package audit --zip /tmp/xcode-plugin-0.3.0.zip --json
```

## Fixture Checks

Simulator duplicate-name/runtime normalization:

```bash
bin/xcode simulator resolve \
  --fixture tests/fixtures/simctl-list-duplicate-names.json \
  --name "iPhone SE (3rd generation)" \
  --runtime "iOS 18.5" \
  --json
```

Warning parser:

```bash
bin/xcode warnings summarize \
  --log tests/fixtures/xcodebuild-warning.log \
  --json
```

## Native Helper Checks

On macOS:

```bash
bin/xcode native helper version --json
bin/xcode native permissions status --json
bin/xcode native app xcode-state --json
bin/xcode native app installed-xcodes --json
```

Do not run `native permissions request` during automated doctor checks. It is intentionally explicit because it may show a macOS permission prompt.
