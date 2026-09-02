# mise radar

Catch stale mise tools before they bite. Radar watches the versions you actually use on [Omarchy](https://omarchy.org) (Claude, Node, gh, and anything else in `config.toml`) and badges the bar when one falls behind latest. Click for a compact table of requested, installed, and latest, including brand-new releases mise would otherwise hide.

![mise radar on the Omarchy bar](preview.png)

This plugin never upgrades, installs, or writes config.

## Install

```sh
omarchy plugin add https://github.com/chyld/omarchy-mise-radar.git --enable
```

Omarchy already includes mise (`mise-bin`) at `/usr/bin/mise`. The plugin also accepts `$HOME/.local/bin/mise` as a fallback if that distro binary is missing.

## Remove

```sh
omarchy plugin remove chyld.mise-radar
```

That deletes the plugin files. It does not change mise or `~/.config/mise/config.toml`.

## Trust boundary

The plugin executes only these two absolute paths, in this order:

1. `/usr/bin/mise`
2. `$HOME/.local/bin/mise`

It never searches `PATH` and never launches `sh`, `env`, or `test`. Relative paths and any path containing `..` are rejected. Each candidate is probed with `--version` before use.

Commands are argv lists (not a shell):

- `["/usr/bin/mise", "ls", "--json", "--current"]` (15s deadline)
- `["/usr/bin/mise", "outdated", "--bump", "--json"]` with `MISE_MINIMUM_RELEASE_AGE=0` inherited into the process environment (45s deadline; this command may use the network)

Stdout is capped at 256KiB. Timed-out, oversized, or superseded runs receive SIGTERM, then SIGKILL after 1.5s. The service kills leftover processes on destruction.

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
omarchy plugin validate .
```

## License

MIT
