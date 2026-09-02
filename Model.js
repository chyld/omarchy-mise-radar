var MAX_JSON_CHARS = 262144
var MAX_TOOLS = 64
var MAX_VERSIONS_PER_TOOL = 16
var MAX_STRING = 128

function parseJsonObject(text) {
  if (typeof text !== "string") return null
  if (text.length > MAX_JSON_CHARS) return null
  var parsed
  try {
    parsed = JSON.parse(text)
  } catch (e) {
    return null
  }
  if (!parsed || typeof parsed !== "object" || parsed instanceof Array) return null
  return parsed
}

function isSafeName(name) {
  if (typeof name !== "string") return false
  if (name.length < 1 || name.length > MAX_STRING) return false
  if (name === "__proto__" || name === "prototype" || name === "constructor") return false
  if (name.indexOf("__") !== -1) return false
  return true
}

function clipString(value) {
  if (value === null || value === undefined) return ""
  var s = typeof value === "string" ? value : String(value)
  if (s.length > MAX_STRING) return s.substring(0, MAX_STRING)
  return s
}

function parseMiseList(lsJson) {
  if (!lsJson || typeof lsJson !== "object" || lsJson instanceof Array) return []

  var rows = []
  var toolCount = 0
  for (var toolName in lsJson) {
    if (!Object.prototype.hasOwnProperty.call(lsJson, toolName)) continue
    if (!isSafeName(toolName)) continue
    if (toolCount >= MAX_TOOLS) break
    var versions = lsJson[toolName]
    if (!(versions instanceof Array)) continue

    var limit = versions.length
    if (limit > MAX_VERSIONS_PER_TOOL) limit = MAX_VERSIONS_PER_TOOL

    var activeVersion = null
    var i
    for (i = 0; i < limit; i++) {
      var candidate = versions[i]
      if (!candidate || typeof candidate !== "object") continue
      if (candidate.active === true) {
        activeVersion = candidate
        break
      }
    }
    if (!activeVersion) {
      for (i = 0; i < limit; i++) {
        var installed = versions[i]
        if (!installed || typeof installed !== "object") continue
        if (installed.installed === true) {
          activeVersion = installed
          break
        }
      }
    }
    if (!activeVersion) continue

    toolCount += 1
    rows.push({
      name: clipString(toolName),
      requested: clipString(activeVersion.requested_version || ""),
      current: clipString(activeVersion.version || ""),
      latest: "",
      outdated: false
    })
  }

  rows.sort(function(a, b) { return a.name.localeCompare(b.name) })
  return rows
}

function parseMiseOutdated(outdatedJson) {
  var map = Object.create(null)
  if (!outdatedJson || typeof outdatedJson !== "object" || outdatedJson instanceof Array) return map

  var count = 0
  for (var toolName in outdatedJson) {
    if (!Object.prototype.hasOwnProperty.call(outdatedJson, toolName)) continue
    if (!isSafeName(toolName)) continue
    if (count >= MAX_TOOLS) break
    var info = outdatedJson[toolName]
    if (!info || typeof info !== "object" || info instanceof Array) continue
    map[toolName] = { latest: clipString(info.latest || "") }
    count += 1
  }
  return map
}

function mergeToolData(lsRows, outdatedMap) {
  if (!lsRows) lsRows = []
  if (!outdatedMap) outdatedMap = Object.create(null)

  var merged = []
  var outdatedCount = 0
  var i
  for (i = 0; i < lsRows.length; i++) {
    var row = lsRows[i] || {}
    var name = clipString(row.name || "")
    var requested = clipString(row.requested || "")
    var current = clipString(row.current || "")
    var outdatedInfo = outdatedMap[name]
    if (outdatedInfo) {
      outdatedCount += 1
      merged.push({
        name: name,
        requested: requested,
        current: current,
        latest: clipString(outdatedInfo.latest || ""),
        outdated: true
      })
    } else {
      merged.push({
        name: name,
        requested: requested,
        current: current,
        latest: current,
        outdated: false
      })
    }
  }

  return { rows: merged, outdatedCount: outdatedCount }
}

function buildModel(lsJson, outdatedJson) {
  return mergeToolData(parseMiseList(lsJson), parseMiseOutdated(outdatedJson))
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = {
    parseJsonObject: parseJsonObject,
    isSafeName: isSafeName,
    clipString: clipString,
    parseMiseList: parseMiseList,
    parseMiseOutdated: parseMiseOutdated,
    mergeToolData: mergeToolData,
    buildModel: buildModel
  }
}
