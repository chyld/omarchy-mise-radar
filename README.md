# mise radar

Display-only mise version radar for [Omarchy](https://omarchy.org) Quattro. A bar badge when configured tools are behind latest. Click for a compact table of requested, installed, and latest.

![mise radar on the Omarchy bar](preview.png)

This plugin never upgrades, installs, or writes config.

## Install

```sh
omarchy plugin add https://github.com/chyld/omarchy-mise-radar.git --enable
```

Requires Omarchy Quattro and [mise](https://mise.jdx.dev) on `PATH` or `~/.local/bin/mise`.

## Remove

```sh
omarchy plugin remove chyld.mise-radar
```

That deletes the plugin files. It does not change mise or `~/.config/mise/config.toml`.

## What it shows

- Quiet radar icon when everything is current
- Count badge when something is behind
- Panel table: tool, requested constraint, installed, latest

Latest comes from `mise outdated --bump`, with `MISE_MINIMUM_RELEASE_AGE=0` so brand-new releases are not hidden. That matches [mise-versions.jdx.dev](https://mise-versions.jdx.dev) more closely than mise's default age filter.

## When it refreshes

On shell start, when you open the panel, and every 4 hours.

## Display-only

It only runs:

```sh
mise ls --json --current
MISE_MINIMUM_RELEASE_AGE=0 mise outdated --bump --json
```

It never runs `mise upgrade`, `mise install`, `mise use`, or writes `~/.config/mise/config.toml`.

## Development

```sh
node --test tests/model.test.js
omarchy plugin validate .
```

## License

MIT
