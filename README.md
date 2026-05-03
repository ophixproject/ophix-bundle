# ophix-bundle

A CLI tool for bundling packages from a local PyPI server into a distributable archive for air-gap deployment.

Bundles are simple requirements-style text files. The `package` command reads a bundle, downloads all matching packages (including transitive dependencies by default) from your local PyPI server, and produces a `.tgz` archive that can be transferred to an air-gapped environment and loaded onto a local PyPI server there.

---

## Installation

```
pip install ophix-bundle
```

---

## Quick start

```
# Point the tool at your local PyPI server
ophix-bundle config --server http://pypi.internal:8080/simple/

# Create a bundle, pinning each package to its current latest version
ophix-bundle add --name ophix-core --packages ophix-server-base,ophix-creds,ophix-docs --pin-version

# Download everything and produce a timestamped archive
ophix-bundle package --name ophix-core
```

The archive is written to the current directory as `ophix-core_20260503142305.tgz`. Extract it and copy the contents of `packages/` to the target PyPI server's packages directory.

---

## Configuration

Configuration is stored in `~/.config/ophix-bundle/config.ini`. Bundle files (`.txt`) are stored in `~/ophix-bundles/` by default.

Both settings can be changed:

```
ophix-bundle config --server http://pypi.internal:8080/simple/
ophix-bundle config --bundles-dir /srv/bundles
```

Running `ophix-bundle config` with no arguments shows the current configuration:

```
Config file:   /home/user/.config/ophix-bundle/config.ini
Server:        http://pypi.internal:8080/simple/
Bundles dir:   /home/user/ophix-bundles
```

Any command that contacts the server accepts `--server <url>` to override the configured value for that run without changing the stored configuration.

---

## Commands

### `config`

Show or update stored configuration.

```
ophix-bundle config [--server <url>] [--bundles-dir <dir>]
```

| Option | Description |
|---|---|
| `--server <url>` | Store this as the default PyPI server URL |
| `--bundles-dir <dir>` | Store this as the default bundles directory |

Omit both options to print the current configuration.

---

### `add`

Add packages to a bundle. Creates the bundle file if it does not exist. If a named package is already in the bundle its entry is replaced; otherwise it is appended.

```
ophix-bundle add --name <name> --packages <pkg1,pkg2,...> [--pin-version] [--server <url>]
```

| Option | Description |
|---|---|
| `--name <name>` | Bundle name (maps to `<name>.txt` in the bundles directory) |
| `--packages <pkgs>` | Comma-separated list of package names |
| `--pin-version` | Query the server for the current latest version of each package and record it as a minimum constraint (`package>=X.Y.Z`) |
| `--server <url>` | Override configured PyPI server URL (required when using `--pin-version` if no server is configured) |

**Examples**

Add packages without version pinning:
```
ophix-bundle add --name ophix-core --packages ophix-server-base,ophix-creds,ophix-docs
```

Add packages pinned to their current latest version:
```
ophix-bundle add --name ophix-core --packages ophix-codemirror --pin-version
```

The resulting bundle file (`ophix-core.txt`) is a standard pip requirements file:
```
ophix-server-base>=2026.04.23.01
ophix-creds>=2026.04.23.01
ophix-docs>=2026.04.23.01
ophix-codemirror>=2026.04.23.01
```

---

### `update`

Add or remove packages in an existing bundle. `--add` and `--remove` may be used together in a single call.

```
ophix-bundle update --name <name> [--add <pkgs>] [--remove <pkgs>] [--pin-version] [--server <url>]
```

| Option | Description |
|---|---|
| `--name <name>` | Bundle name |
| `--add <pkgs>` | Comma-separated packages to add (same behaviour as `add`) |
| `--remove <pkgs>` | Comma-separated packages to remove (version specifiers are ignored — any entry for the named package is removed) |
| `--pin-version` | Pin added packages to their current latest version (>=) |
| `--server <url>` | Override configured PyPI server URL |

**Examples**

Remove a package:
```
ophix-bundle update --name ophix-core --remove ophix-docs
```

Add a new package pinned to its current version:
```
ophix-bundle update --name ophix-core --add ophix-theme-midnight --pin-version
```

Add and remove in one step:
```
ophix-bundle update --name ophix-core --add ophix-theme-midnight --remove ophix-docs
```

---

### `list`

List all bundles in the configured bundles directory, or show the contents of a specific bundle.

```
ophix-bundle list [--name <name>]
```

| Option | Description |
|---|---|
| `--name <name>` | Show the contents of this bundle instead of listing all bundles |

**Examples**

List all bundles:
```
$ ophix-bundle list
Bundles in /home/user/ophix-bundles:

  ophix-core                                4 package(s)
  ophix-full-stack                          9 package(s)
```

Show a specific bundle:
```
$ ophix-bundle list --name ophix-core
Bundle: ophix-core  (/home/user/ophix-bundles/ophix-core.txt)
4 package(s):

  ophix-server-base>=2026.04.23.01
  ophix-creds>=2026.04.23.01
  ophix-docs>=2026.04.23.01
  ophix-codemirror>=2026.04.23.01
```

---

### `package`

Download all packages in a bundle from the configured PyPI server and produce a timestamped `.tgz` archive.

```
ophix-bundle package --name <name> [--server <url>] [--output-dir <dir>] [--no-deps]
```

| Option | Description |
|---|---|
| `--name <name>` | Bundle name |
| `--server <url>` | Override configured PyPI server URL |
| `--output-dir <dir>` | Write the archive to this directory (default: current directory) |
| `--no-deps` | Download only the packages listed in the bundle; skip transitive dependencies |

The archive is named `<bundle-name>_<YYYYMMDDHHMMSS>.tgz`. Running the command again on the same bundle produces a new archive with a new timestamp, pulling the latest version of any package whose bundle entry has no upper bound.

Package files are stored under a `packages/` subdirectory inside the archive:
```
ophix-core_20260503142305.tgz
└── packages/
      ├── ophix-creds-2026.04.23.01-py3-none-any.whl
      ├── ophix-docs-2026.04.23.01-py3-none-any.whl
      ├── ophix-server-base-2026.04.23.01-py3-none-any.whl
      └── ...
```

**Example**

```
$ ophix-bundle package --name ophix-core
Bundle:     ophix-core (4 package spec(s))
Server:     http://pypi.internal:8080/simple/
Output:     /home/user/ophix-core_20260503142305.tgz
Deps:       included

Running pip download...
...
Downloaded 12 file(s). Creating archive...

Created: /home/user/ophix-core_20260503142305.tgz (3.4 MB)
Contains 12 file(s) in packages/
```

---

## Installing the archive on the target server

Extract the archive and copy the package files into your local PyPI server's packages directory.

For **pypi-server**:
```
tar xzf ophix-core_20260503142305.tgz
cp packages/* /srv/pypi/packages/
```

For **devpi**:
```
tar xzf ophix-core_20260503142305.tgz
devpi upload --from-dir packages/
```

Once the files are in place, installation from the air-gapped server works normally:
```
pip install --index-url http://pypi.internal:8080/simple/ ophix-creds
```

---

## Version pinning strategy

| Bundle entry | Behaviour |
|---|---|
| `package` | Always fetches the latest available version on the server |
| `package>=1.2.3` | Fetches the latest version that satisfies the constraint |
| `package==1.2.3` | Fetches exactly that version |

`--pin-version` records `>=` constraints. This means re-running `package` will pick up newer versions if they have been added to the server since the bundle was created. Use `==` constraints (written manually in the bundle `.txt` file) to freeze a bundle to exact versions.

---

## Bundle files

Bundle files are plain text and can be edited directly. They follow pip requirements file syntax — one entry per line, `#` comments supported. They live in the configured bundles directory (`~/ophix-bundles/` by default) and are named `<bundle-name>.txt`.
