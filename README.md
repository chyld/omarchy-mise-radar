# mise radar

Agent harnesses move every week. A stale Claude, Codex, or OpenCode pin can mean a new model is out and your CLI does not even know it exists. mise radar watches the tools you actually use on [Omarchy](https://omarchy.org) and turns the bar red when one falls behind latest, including brand-new releases mise would otherwise hide. Click for requested, installed, and latest.

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
- Red radar when something is behind
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
