var MAX_JSON_CHARS = 262144
var MAX_TOOLS = 64
var MAX_VERSIONS_PER_TOOL = 16
var MAX_STRING = 128
var MAX_DEPTH = 8
var MAX_NODES = 8192
var UNSAFE_CONTROLS = /[\u0000-\u001f\u007f-\u009f\u061c\u200e\u200f\u202a-\u202e\u2066-\u2069]/

function isObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value)
}

// Bound nesting before JSON.parse allocates the object graph. JSON.parse still
// owns syntax validation; this pass only counts brackets outside strings.
function parseJsonObject(text) {
  if (typeof text !== "string" || text.length > MAX_JSON_CHARS) return null
  var depth = 0, quoted = false, escaped = false
  for (var i = 0; i < text.length; i++) {
    var c = text.charAt(i)
    if (quoted) {
      if (escaped) escaped = false
      else if (c === "\\") escaped = true
      else if (c === '"') quoted = false
    } else if (c === '"') quoted = true
    else if (c === "{" || c === "[") { if (++depth > MAX_DEPTH) return null }
    else if (c === "}" || c === "]") depth--
  }
  try {
    var value = JSON.parse(text)
    return isObject(value) && boundedTree(value, 0, {count: 0}) ? value : null
  } catch (e) { return null }
}

function boundedTree(value, depth, budget) {
  if (++budget.count > MAX_NODES || depth > MAX_DEPTH) return false
  if (typeof value === "number") return isFinite(value)
  if (value === null || typeof value === "boolean") return true
  // Metadata such as installation paths is ignored, but remains bounded.
  if (typeof value === "string") return value.length <= 4096
  if (typeof value !== "object") return false
  for (var key in value) {
    if (!Object.prototype.hasOwnProperty.call(value, key)) continue
    if (key.length > 128 || !boundedTree(value[key], depth + 1, budget)) return false
  }
  return true
}

function validString(value, allowEmpty) {
  return typeof value === "string" && (allowEmpty || value.length > 0)
    && value.length <= MAX_STRING && !UNSAFE_CONTROLS.test(value)
}

function isSafeName(name) {
  return validString(name, false) && name !== "__proto__"
    && name !== "prototype" && name !== "constructor" && name.indexOf("__") === -1
}

function validRoot(value) {
  return isObject(value) && boundedTree(value, 0, {count: 0})
    && Object.keys(value).length <= MAX_TOOLS
}

function parseMiseList(value) {
  if (!validRoot(value)) return null
  var rows = []
  for (var name in value) {
    if (!Object.prototype.hasOwnProperty.call(value, name)) continue
    var versions = value[name]
    if (!isSafeName(name) || !Array.isArray(versions) || versions.length === 0
        || versions.length > MAX_VERSIONS_PER_TOOL) return null
    var active = null, installed = null
    for (var i = 0; i < versions.length; i++) {
      var entry = versions[i]
      if (!isObject(entry) || !validString(entry.version, false)
          || (entry.requested_version !== undefined && !validString(entry.requested_version, true))
          || (entry.active !== undefined && typeof entry.active !== "boolean")
          || (entry.installed !== undefined && typeof entry.installed !== "boolean")) return null
      if (!active && entry.active === true) active = entry
      if (!installed && entry.installed === true) installed = entry
    }
    var selected = active || installed
    if (!selected) continue
    rows.push({name: name, requested: selected.requested_version || "",
      current: selected.version, latest: "", outdated: false})
  }
  rows.sort(function(a, b) { return a.name.localeCompare(b.name) })
  return rows
}

function parseMiseOutdated(value) {
  if (!validRoot(value)) return null
  var map = Object.create(null)
  for (var name in value) {
    if (!Object.prototype.hasOwnProperty.call(value, name)) continue
    var entry = value[name]
    if (!isSafeName(name) || !isObject(entry) || !validString(entry.latest, false)
        || (entry.current !== undefined && !validString(entry.current, true))
        || (entry.requested !== undefined && !validString(entry.requested, true))) return null
    map[name] = {latest: entry.latest}
  }
  return map
}

function mergeToolData(rows, outdated) {
  if (rows === null || outdated === null) return null
  var count = 0
  var merged = rows.map(function(row) {
    var behind = Object.prototype.hasOwnProperty.call(outdated, row.name)
    if (behind) count++
    return {name: row.name, requested: row.requested, current: row.current,
      latest: behind ? outdated[row.name].latest : row.current, outdated: behind}
  })
  return {rows: merged, outdatedCount: count}
}

function buildModel(ls, outdated) {
  return mergeToolData(parseMiseList(ls), parseMiseOutdated(outdated))
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = {parseJsonObject: parseJsonObject, isSafeName: isSafeName,
    parseMiseList: parseMiseList, parseMiseOutdated: parseMiseOutdated,
    mergeToolData: mergeToolData, buildModel: buildModel}
}
