const { test } = require("node:test");
const assert = require("node:assert");
const Model = require("../Model.js");

test("parseMiseList with empty input", () => {
  assert.deepStrictEqual(Model.parseMiseList({}), []);
  assert.deepStrictEqual(Model.parseMiseList(null), []);
  assert.deepStrictEqual(Model.parseMiseList(undefined), []);
});

test("parseMiseList with real mise ls output", () => {
  const input = {
    "claude": [
      {
        "version": "2.1.257",
        "requested_version": "latest",
        "install_path": "/home/chyld/.local/share/mise/installs/claude/2.1.257",
        "source": {
          "type": "mise.toml",
          "path": "/home/chyld/.config/mise/config.toml"
        },
        "installed": true,
        "active": true
      }
    ],
    "node": [
      {
        "version": "26.8.1",
        "requested_version": "26.8.1",
        "install_path": "/home/chyld/.local/share/mise/installs/node/26.8.1",
        "source": {
          "type": "mise.toml",
          "path": "/home/chyld/.config/mise/config.toml"
        },
        "installed": true,
        "active": true
      }
    ]
  };
  
  const result = Model.parseMiseList(input);
  assert.strictEqual(result.length, 2);
  assert.strictEqual(result[0].name, "claude");
  assert.strictEqual(result[0].requested, "latest");
  assert.strictEqual(result[0].current, "2.1.257");
  assert.strictEqual(result[0].latest, "");
  assert.strictEqual(result[0].outdated, false);
  
  assert.strictEqual(result[1].name, "node");
  assert.strictEqual(result[1].requested, "26.8.1");
  assert.strictEqual(result[1].current, "26.8.1");
});

test("parseMiseList with scoped npm package", () => {
  const input = {
    "npm:@xai-official/grok": [
      {
        "version": "1.0.13",
        "requested_version": "latest",
        "install_path": "/home/chyld/.local/share/mise/installs/npm-@xai-official-grok/1.0.13",
        "source": {
          "type": "mise.toml",
          "path": "/home/chyld/.config/mise/config.toml"
        },
        "installed": true,
        "active": true
      }
    ]
  };
  
  const result = Model.parseMiseList(input);
  assert.strictEqual(result.length, 1);
  assert.strictEqual(result[0].name, "npm:@xai-official/grok");
  assert.strictEqual(result[0].current, "1.0.13");
});

test("parseMiseList with only installed but not active version", () => {
  const input = {
    "python": [
      {
        "version": "3.11.0",
        "requested_version": "3.11",
        "install_path": "/home/user/.local/share/mise/installs/python/3.11.0",
        "installed": true,
        "active": false
      }
    ]
  };
  
  const result = Model.parseMiseList(input);
  assert.strictEqual(result.length, 1);
  assert.strictEqual(result[0].name, "python");
  assert.strictEqual(result[0].current, "3.11.0");
});

test("parseMiseOutdated with empty input", () => {
  assert.deepStrictEqual(Model.parseMiseOutdated({}), {});
  assert.deepStrictEqual(Model.parseMiseOutdated(null), {});
});

test("parseMiseOutdated with outdated tools", () => {
  const input = {
    "python": {
      "requested": "3.11",
      "current": "3.11.0",
      "latest": "3.11.1"
    },
    "node": {
      "requested": "20",
      "current": "20.0.0",
      "latest": "20.1.0"
    }
  };
  
  const result = Model.parseMiseOutdated(input);
  assert.strictEqual(result.python.latest, "3.11.1");
  assert.strictEqual(result.node.latest, "20.1.0");
});

test("mergeToolData with no outdated tools", () => {
  const lsRows = [
    { name: "node", requested: "26.8.1", current: "26.8.1", latest: "", outdated: false }
  ];
  const outdatedMap = {};
  
  const result = Model.mergeToolData(lsRows, outdatedMap);
  assert.strictEqual(result.outdatedCount, 0);
  assert.strictEqual(result.rows.length, 1);
  assert.strictEqual(result.rows[0].outdated, false);
});

test("mergeToolData with outdated tools", () => {
  const lsRows = [
    { name: "python", requested: "3.11", current: "3.11.0", latest: "", outdated: false },
    { name: "node", requested: "20", current: "20.0.0", latest: "", outdated: false }
  ];
  const outdatedMap = {
    "python": { latest: "3.11.1" }
  };
  
  const result = Model.mergeToolData(lsRows, outdatedMap);
  assert.strictEqual(result.outdatedCount, 1);
  assert.strictEqual(result.rows.length, 2);
  assert.strictEqual(result.rows[0].name, "python");
  assert.strictEqual(result.rows[0].latest, "3.11.1");
  assert.strictEqual(result.rows[0].outdated, true);
  assert.strictEqual(result.rows[1].outdated, false);
});

test("buildModel integrates ls and outdated", () => {
  const lsJson = {
    "claude": [
      {
        "version": "2.1.257",
        "requested_version": "latest",
        "installed": true,
        "active": true
      }
    ],
    "node": [
      {
        "version": "26.8.1",
        "requested_version": "26.8.1",
        "installed": true,
        "active": true
      }
    ]
  };
  
  const outdatedJson = {
    "claude": {
      "requested": "latest",
      "current": "2.1.257",
      "latest": "2.1.300"
    }
  };
  
  const result = Model.buildModel(lsJson, outdatedJson);
  assert.strictEqual(result.outdatedCount, 1);
  assert.strictEqual(result.rows.length, 2);
  
  const claudeRow = result.rows.find(r => r.name === "claude");
  assert.strictEqual(claudeRow.outdated, true);
  assert.strictEqual(claudeRow.latest, "2.1.300");
  
  const nodeRow = result.rows.find(r => r.name === "node");
  assert.strictEqual(nodeRow.outdated, false);
});

test("buildModel with malformed JSON gracefully degrades", () => {
  const result = Model.buildModel(null, null);
  assert.strictEqual(result.outdatedCount, 0);
  assert.strictEqual(result.rows.length, 0);
});
