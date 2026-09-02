# mise radar

Catch stale mise tools before they bite. Radar watches the versions you actually use on [Omarchy](https://omarchy.org) (Claude, Node, gh, and anything else in `config.toml`) and badges the bar when one falls behind latest. Click for a compact table of requested, installed, and latest, including brand-new releases mise would otherwise hide.

![mise radar on the Omarchy bar](preview.png)

This plugin never upgrades, installs, or writes config.

## Install

```sh
omarchy plugin add https://github.com/chyld/omarchy-mise-radar.git --enable
```

Omarchy already includes mise. You do not need to install anything else.

## Remove

```sh
omarchy plugin remove chyld.mise-radar
```

That deletes the plugin files. It does not change mise or `~/.config/mise/config.toml`.

## What it shows

- Quiet radar icon when everything is current
- Count badge when something is behind
- Panel table: tool, requested constraint, installed, latest

Latest comes from `mise outdated`, including brand-new releases mise would otherwise hide. That matches [mise-versions.jdx.dev](https://mise-versions.jdx.dev) more closely than mise's default delay.

## When it refreshes

On shell start, when you open the panel, and every 4 hours.

## Display-only

It never runs `mise upgrade`, `mise install`, `mise use`, or writes `~/.config/mise/config.toml`. If something is behind, you update it yourself.

## Development

```sh
node --test tests/model.test.js
/usr/bin/python3 -m unittest tests.supervise_test
omarchy plugin validate .
```

## License

MIT
