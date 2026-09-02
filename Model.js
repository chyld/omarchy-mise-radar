function parseMiseList(lsJson) {
  if (!lsJson || typeof lsJson !== "object") return []

  var rows = []
  for (var toolName in lsJson) {
    if (!Object.prototype.hasOwnProperty.call(lsJson, toolName)) continue
    var versions = lsJson[toolName]
    if (!(versions instanceof Array)) continue

    var activeVersion = null
    var i
    for (i = 0; i < versions.length; i++) {
      if (versions[i] && versions[i].active === true) {
        activeVersion = versions[i]
        break
      }
    }
    if (!activeVersion) {
      for (i = 0; i < versions.length; i++) {
        if (versions[i] && versions[i].installed === true) {
          activeVersion = versions[i]
          break
        }
      }
    }
    if (!activeVersion) continue

    rows.push({
      name: toolName,
      requested: String(activeVersion.requested_version || ""),
      current: String(activeVersion.version || ""),
      latest: "",
      outdated: false
    })
  }

  rows.sort(function(a, b) { return a.name.localeCompare(b.name) })
  return rows
}

function parseMiseOutdated(outdatedJson) {
  if (!outdatedJson || typeof outdatedJson !== "object") return {}

  var map = {}
  for (var toolName in outdatedJson) {
    if (!Object.prototype.hasOwnProperty.call(outdatedJson, toolName)) continue
    var info = outdatedJson[toolName]
    if (!info || typeof info !== "object") continue
    map[toolName] = { latest: String(info.latest || "") }
  }
  return map
}

function mergeToolData(lsRows, outdatedMap) {
  var outdatedCount = 0
  for (var key in outdatedMap) {
    if (Object.prototype.hasOwnProperty.call(outdatedMap, key)) outdatedCount++
  }

  var merged = []
  for (var i = 0; i < lsRows.length; i++) {
    var row = lsRows[i]
    var outdatedInfo = outdatedMap[row.name]
    if (outdatedInfo) {
      merged.push({
        name: row.name,
        requested: row.requested,
        current: row.current,
        latest: outdatedInfo.latest,
        outdated: true
      })
    } else {
      merged.push({
        name: row.name,
        requested: row.requested,
        current: row.current,
        latest: row.current,
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
    parseMiseList: parseMiseList,
    parseMiseOutdated: parseMiseOutdated,
    mergeToolData: mergeToolData,
    buildModel: buildModel
  }
}
