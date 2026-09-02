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
  const empty = Model.parseMiseOutdated({});
  assert.strictEqual(Object.getPrototypeOf(empty), null);
  assert.strictEqual(Object.keys(empty).length, 0);
  const fromNull = Model.parseMiseOutdated(null);
  assert.strictEqual(Object.getPrototypeOf(fromNull), null);
  assert.strictEqual(Object.keys(fromNull).length, 0);
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

test("parseMiseOutdated ignores proto and unsafe keys", () => {
  const protoKey = "_" + "_proto_" + "_";
  const input = {};
  Object.defineProperty(input, protoKey, { value: { latest: "hacked" }, enumerable: true, configurable: true, writable: true });
  input.prototype = { latest: "x" };
  input.constructor = { latest: "y" };
  input.node = { latest: "1.0.0" };
  input["foo" + "_" + "_bar"] = { latest: "z" };
  const result = Model.parseMiseOutdated(input);
  assert.strictEqual(Object.getPrototypeOf(result), null);
  assert.strictEqual(result.node.latest, "1.0.0");
  assert.strictEqual(Object.prototype.hasOwnProperty.call(result, protoKey), false);
  assert.strictEqual(result[protoKey], undefined);
  assert.strictEqual(result.prototype, undefined);
  assert.strictEqual(result.constructor, undefined);
  assert.strictEqual(result["foo" + "_" + "_bar"], undefined);
});

test("parseMiseList truncates more than 64 tools", () => {
  const input = {};
  for (let i = 0; i < 80; i++) {
    const n = "t" + String(i).padStart(2, "0");
    input[n] = [{ version: "1.0.0", requested_version: "1", installed: true, active: true }];
  }
  const result = Model.parseMiseList(input);
  assert.strictEqual(result.length, 64);
});

test("parseJsonObject rejects oversize and non-objects", () => {
  assert.strictEqual(Model.parseJsonObject("x".repeat(262145)), null);
  assert.strictEqual(Model.parseJsonObject(null), null);
  assert.strictEqual(Model.parseJsonObject(123), null);
  assert.strictEqual(Model.parseJsonObject("[1,2]"), null);
  assert.strictEqual(Model.parseJsonObject("null"), null);
  assert.strictEqual(Model.parseJsonObject("true"), null);
  assert.deepStrictEqual(Model.parseJsonObject('{"a":1}'), { a: 1 });
});

test("closed schema ignores extra fields", () => {
  const list = Model.parseMiseList({
    node: [{
      version: "1.0.0",
      requested_version: "latest",
      installed: true,
      active: true,
      install_path: "/secret",
      extra: "nope"
    }]
  });
  assert.strictEqual(list.length, 1);
  assert.deepStrictEqual(Object.keys(list[0]).sort(), ["current", "latest", "name", "outdated", "requested"]);
  assert.strictEqual(list[0].current, "1.0.0");
  assert.strictEqual(list[0].install_path, undefined);
  const od = Model.parseMiseOutdated({
    node: { latest: "2.0.0", current: "1.0.0", requested: "latest", extra: "nope" }
  });
  assert.deepStrictEqual(Object.keys(od.node), ["latest"]);
  assert.strictEqual(od.node.latest, "2.0.0");
});

