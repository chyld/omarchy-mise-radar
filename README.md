# mise radar

Catch stale mise tools before they bite. Radar watches the versions you actually use on [Omarchy](https://omarchy.org) (Claude, Node, gh, and anything else in `config.toml`) and badges the bar when one falls behind latest. Click for a compact table of requested, installed, and latest, including brand-new releases mise would otherwise hide.

![mise radar on the Omarchy bar](preview.png)

This plugin never upgrades, installs, or writes config.

## Install

```sh
omarchy plugin add https://github.com/chyld/omarchy-mise-radar.git --enable
```

Omarchy already includes mise (`mise-bin`) at `/usr/bin/mise`. That is the only binary this plugin will run. There is no home-directory fallback and no install-mise-yourself path.

## Remove

```sh
omarchy plugin remove chyld.mise-radar
```

That deletes the plugin files. It does not change mise or `~/.config/mise/config.toml`.

## Trust boundary

The plugin launches only `/usr/bin/python3` with this plugin's `supervise.py`. That helper is the process supervisor: it `setsid`s a trusted mise identity into its own session/process group, copies stdout with a 256KiB producer-side ceiling, and on timeout, overflow, SIGTERM/SIGINT/SIGHUP, or replacement it sends SIGTERM to the group, waits 1.5s, then SIGKILL and reaps the tree.

mise itself is never searched on `PATH`. The only accepted binary is `/usr/bin/mise` (Omarchy's `mise-bin` package). `$HOME/.local/bin/mise`, relative paths, any path containing `..`, and any other location are rejected. The plugin never launches `sh`, `env`, or `test`, never uses `curl | sh`, and never asks you to install mise yourself.

Before exec, the supervisor `lstat`s each path component `/`, `/usr`, `/usr/bin`, and `/usr/bin/mise`. Each must be root-owned and not group- or world-writable (`st_mode & 0o022 == 0`). Intermediate components must be directories. The final component must be a regular file, not a symlink. It then opens that file (`O_RDONLY | O_NOFOLLOW`), `fstat`s the fd (regular file, uid 0, not group/world-writable), keeps the fd, and executes `/proc/self/fd/N` with argv0 `mise`. It never reopens the pathname for exec, so the check-to-execute race is closed.

For `ls` and `outdated`, the supervisor runs `--version` against that same open fd first (4KiB bound, 5s timeout, TERM then KILL in its own session). Stdout must look like a mise version (`^[0-9]{4}\.` or starting with `mise`). On failure it exits non-zero and does not run the real command.

Commands are argv lists (not a shell), always:

`["/usr/bin/python3", "<plugin>/supervise.py", TIMEOUT, "262144", "1.5", "/usr/bin/mise", "--", ...]`

- `ls --json --current` (15s supervisor deadline; supervisor also binds the fd and checks `--version` on it first)
- `outdated --bump --json` with `MISE_MINIMUM_RELEASE_AGE=0` inherited into the process environment (45s supervisor deadline; this command may use the network)

There is no separate QML `--version` probe that later reopens the path. The first real command is `ls` through the supervisor.

QML keeps a slightly longer backup timer, a 256KiB StdioCollector cap, generation tokens, and destruction that SIGTERM's the supervisor then SIGKILL after 1.5s so the helper can reap the group first.

## What it shows

- Quiet radar icon when everything is current
- Count badge when something is behind
- Panel table: tool, requested constraint, installed, latest

Latest comes from `mise outdated --bump`, with `MISE_MINIMUM_RELEASE_AGE=0` so brand-new releases are not hidden. That matches [mise-versions.jdx.dev](https://mise-versions.jdx.dev) more closely than mise's default age filter.

## When it refreshes

On shell start, when you open the panel, and every 4 hours.

## Display-only

It only runs the argv lists above. It never runs `mise upgrade`, `mise install`, `mise use`, or writes `~/.config/mise/config.toml`.

## Development

```sh
node --test tests/model.test.js
/usr/bin/python3 -m py_compile supervise.py
/usr/bin/python3 -m unittest tests.supervise_test
omarchy plugin validate .
```

## License

MIT
