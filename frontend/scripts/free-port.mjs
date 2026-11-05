#!/usr/bin/env node
// Stops whatever is serving a TCP port, so a dev server can start on it.
//
//   node scripts/free-port.mjs 5173
//
// On Windows two servers can bind one port and the older one keeps answering, so a
// forgotten server makes a fresh start look broken instead of failing to start.
import { execFileSync } from 'node:child_process'
import net from 'node:net'
import path from 'node:path'
import { setTimeout as sleep } from 'node:timers/promises'
import { ownerPids, parseLsof, parseNetstat, parsePort, parseProcessList, serverRoot } from './ports.mjs'

const HOSTS = ['127.0.0.1', '::1']
const CONNECT_TIMEOUT_MS = 500
const SETTLE_MS = 200 // lets the server accept, so our connection is listed with its process
const EXIT_TIMEOUT_MS = 5000
const COMMAND_TIMEOUT_MS = 15000
const POLL_MS = 100
const MAX_STOPS = 5 // several servers can share one port; each pass stops one
const MAX_UNEXPLAINED = 10 // a server that was just stopped can still answer for a moment
const FREE = 'free'
const STOPPED = 'stopped'
const UNEXPLAINED = 'unexplained'
const MAX_OUTPUT_BYTES = 32 * 1024 * 1024
const IS_WINDOWS = process.platform === 'win32'
const PROCESS_QUERY =
  '[Console]::OutputEncoding = [Text.Encoding]::UTF8; ' +
  'Get-CimInstance Win32_Process | Select-Object ProcessId,ParentProcessId,Name,CommandLine | ConvertTo-Json -Compress'

// Windows tools by full path, so a file of the same name in this folder is never run instead
const SYSTEM32 = path.join(process.env.SystemRoot ?? 'C:\\Windows', 'System32')
const NETSTAT = path.join(SYSTEM32, 'netstat.exe')
const TASKKILL = path.join(SYSTEM32, 'taskkill.exe')
const POWERSHELL = path.join(SYSTEM32, 'WindowsPowerShell', 'v1.0', 'powershell.exe')

const run = (command, args) =>
  execFileSync(command, args, {
    encoding: 'utf8',
    maxBuffer: MAX_OUTPUT_BYTES,
    stdio: ['ignore', 'pipe', 'pipe'],
    timeout: COMMAND_TIMEOUT_MS,
    windowsHide: true,
  })

/** Why a command failed, in its own words when it gave any. */
const reasonOf = error => String(error.stderr ?? '').trim().split('\n')[0] || error.message.split('\n')[0]

// A test connection to a free port can, rarely, connect to itself and name us as the owner
const isOurs = pid => pid === process.pid || pid === process.ppid

const say = text => process.stdout.write(`${text}\n`)
const warn = text => process.stderr.write(`${text}\n`)

/** A connected socket, or null when nothing answers on that address. */
const connect = (host, port) =>
  new Promise(resolve => {
    const socket = net.connect({ host, port, timeout: CONNECT_TIMEOUT_MS })
    const giveUp = () => {
      socket.destroy()
      resolve(null)
    }
    socket.on('error', giveUp).once('timeout', giveUp)
    socket.once('connect', () => {
      socket.setTimeout(0)
      resolve(socket)
    })
  })

const openConnections = async port =>
  (await Promise.all(HOSTS.map(host => connect(host, port)))).filter(socket => socket !== null)

function listProcesses() {
  try {
    return parseProcessList(run(POWERSHELL, ['-NoProfile', '-NonInteractive', '-Command', PROCESS_QUERY]))
  } catch (error) {
    warn(`Could not list processes (${reasonOf(error)}); stopping only the process that answered.`)
    return []
  }
}

function windowsOwners(port, probePorts) {
  const pids = ownerPids(parseNetstat(run(NETSTAT, ['-ano'])), port, probePorts).filter(pid => !isOurs(pid))
  if (pids.length === 0) return []
  const processes = listProcesses()
  const names = new Map(processes.map(({ pid, name }) => [pid, name]))
  const roots = [...new Set(pids.map(pid => serverRoot(pid, processes)))]
  return roots.map(pid => ({ pid, name: names.get(pid) || 'a process' }))
}

function nameOf(pid) {
  try {
    return run('ps', ['-p', String(pid), '-o', 'comm=']).trim() || 'a process'
  } catch {
    return 'a process'
  }
}

function posixOwners(port) {
  try {
    const pids = parseLsof(run('lsof', ['-nP', '-t', `-iTCP:${port}`, '-sTCP:LISTEN']))
    return pids.filter(pid => !isOurs(pid)).map(pid => ({ pid, name: nameOf(pid) }))
  } catch (error) {
    if (error.code === 'ENOENT') throw new Error('lsof is needed to find what holds the port, and it is not installed.')
    return [] // lsof exits with an error when it finds nothing
  }
}

function isAlive(pid) {
  try {
    process.kill(pid, 0)
    return true
  } catch (error) {
    return error.code === 'EPERM'
  }
}

async function hasExited(pid) {
  const deadline = Date.now() + EXIT_TIMEOUT_MS
  while (isAlive(pid)) {
    if (Date.now() > deadline) return false
    await sleep(POLL_MS)
  }
  return true
}

function kill(pid, force) {
  try {
    if (IS_WINDOWS) run(TASKKILL, ['/PID', String(pid), '/T', '/F'])
    else process.kill(pid, force ? 'SIGKILL' : 'SIGTERM')
  } catch (error) {
    if (isAlive(pid)) throw new Error(`Could not stop pid ${pid}: ${reasonOf(error)}`)
  }
}

async function stop({ pid, name }, port) {
  say(`Port ${port} is in use by ${name} (pid ${pid}). Stopping it.`)
  kill(pid, false)
  if (await hasExited(pid)) return
  kill(pid, true)
  // A process that still shows up may be one its parent has not collected yet, with the
  // port already released: the next pass checks the port itself
  await hasExited(pid)
}

/** One pass: stops the servers answering on the port now, and says what it found. */
async function freeOnce(port) {
  const sockets = await openConnections(port)
  if (sockets.length === 0) return FREE
  try {
    await sleep(SETTLE_MS)
    const probePorts = sockets.map(socket => socket.localPort)
    const owners = IS_WINDOWS ? windowsOwners(port, probePorts) : posixOwners(port)
    for (const owner of owners) await stop(owner, port)
    return owners.length > 0 ? STOPPED : UNEXPLAINED
  } finally {
    sockets.forEach(socket => socket.destroy())
  }
}

async function freePort(port) {
  let stops = 0
  let unexplained = 0
  while (stops < MAX_STOPS && unexplained < MAX_UNEXPLAINED) {
    const outcome = await freeOnce(port)
    if (outcome === FREE) return
    if (outcome === STOPPED) {
      stops += 1
      unexplained = 0
    } else {
      unexplained += 1
      await sleep(POLL_MS)
    }
  }
  const reason = stops < MAX_STOPS ? 'what holds it could not be found' : 'something keeps taking it back'
  throw new Error(`Port ${port} is in use and ${reason}. Stop it by hand, then start again.`)
}

try {
  await freePort(parsePort(process.argv[2]))
} catch (error) {
  warn(error.message)
  process.exitCode = 1
}
