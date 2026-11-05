// Pure helpers for finding the process that holds a TCP port. Nothing here touches the system.

const MAX_PORT = 65535

/** The port as a number; throws when the text cannot be a port. */
export function parsePort(text) {
  const port = /^\d{1,5}$/.test(text ?? '') ? Number(text) : 0
  if (port < 1 || port > MAX_PORT) throw new Error(`Not a port number: ${text}`)
  return port
}

const portOf = address => Number(address.slice(address.lastIndexOf(':') + 1))

/** The TCP rows of `netstat -ano` (Windows). */
export function parseNetstat(output) {
  return output.split(/\r?\n/).flatMap(line => {
    const [protocol, local, remote, state, pid, ...extra] = line.trim().split(/\s+/)
    if (protocol !== 'TCP' || pid === undefined || extra.length > 0) return []
    return [{ localPort: portOf(local), remotePort: portOf(remote), state, pid: Number(pid) }]
  })
}

/**
 * The processes serving a port: its listeners, plus whoever accepted the test connections
 * we opened from `probePorts`. Listeners are not always listed, an accepted connection is.
 */
export function ownerPids(rows, port, probePorts) {
  const pids = rows
    .filter(row => row.localPort === port && row.pid > 0)
    .filter(row => row.state === 'LISTENING' || probePorts.includes(row.remotePort))
    .map(row => row.pid)
  return [...new Set(pids)]
}

/** The output of `Get-CimInstance Win32_Process | ConvertTo-Json`: one object or a list. */
export function parseProcessList(json) {
  if (!json.trim()) return []
  return [JSON.parse(json)].flat().map(process => ({
    pid: process.ProcessId,
    parentPid: process.ParentProcessId,
    name: process.Name ?? '',
    commandLine: process.CommandLine ?? '',
  }))
}

// A Python worker started by a supervisor (uvicorn --reload) names that supervisor here
const SPAWNED_BY = /multiprocessing.*\bparent_pid=(\d+)/
const isPython = process => /^python/i.test(process.name)

/**
 * The process to stop so the port is really released. A reload worker only accepts
 * connections; its supervisor holds the port and would keep it after the worker dies.
 */
export function serverRoot(pid, processes) {
  const byPid = new Map(processes.map(process => [process.pid, process]))

  const climb = (current, seen) => {
    const process = byPid.get(current)
    const supervisor = byPid.get(Number(process?.commandLine.match(SPAWNED_BY)?.[1]))
    const isSupervisor =
      supervisor !== undefined &&
      supervisor.pid === process.parentPid &&
      isPython(supervisor) &&
      !seen.includes(supervisor.pid)
    return isSupervisor ? climb(supervisor.pid, [...seen, current]) : current
  }

  return climb(pid, [])
}

/** The process ids printed by `lsof -t` (macOS, Linux), once each. */
export function parseLsof(output) {
  const pids = output
    .split(/\r?\n/)
    .map(line => Number(line.trim()))
    .filter(pid => Number.isInteger(pid) && pid > 0)
  return [...new Set(pids)]
}
