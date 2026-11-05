import { describe, expect, it } from 'vitest'
import { ownerPids, parseLsof, parseNetstat, parsePort, parseProcessList, serverRoot } from './ports.mjs'

const NETSTAT = `
Active Connections

  Proto  Local Address          Foreign Address        State           PID
  TCP    0.0.0.0:135            0.0.0.0:0              LISTENING       1480
  TCP    127.0.0.1:8000         0.0.0.0:0              LISTENING       4100
  TCP    127.0.0.1:8000         127.0.0.1:62649        ESTABLISHED     59092
  TCP    127.0.0.1:62649        127.0.0.1:8000         ESTABLISHED     777
  TCP    127.0.0.1:8000         127.0.0.1:50249        TIME_WAIT       0
  TCP    [::1]:5174             [::1]:62650            ESTABLISHED     98704
  UDP    0.0.0.0:5353           *:*                                    2200
`

describe('parsePort', () => {
  it('accepts a port number', () => {
    expect(parsePort('5173')).toBe(5173)
  })

  it('refuses anything that is not a usable port', () => {
    for (const bad of [undefined, '', 'abc', '0', '65536', '80.5', '-1', '8000; rm -rf'])
      expect(() => parsePort(bad)).toThrow(/port/i)
  })
})

describe('parseNetstat', () => {
  it('reads the TCP rows and skips headings and UDP', () => {
    const rows = parseNetstat(NETSTAT)

    expect(rows).toHaveLength(6)
    expect(rows[1]).toEqual({ localPort: 8000, remotePort: 0, state: 'LISTENING', pid: 4100 })
    expect(rows[5]).toEqual({ localPort: 5174, remotePort: 62650, state: 'ESTABLISHED', pid: 98704 })
  })
})

describe('ownerPids', () => {
  const rows = parseNetstat(NETSTAT)

  it('finds the listener and the process that accepted our test connection', () => {
    expect(ownerPids(rows, 8000, [62649])).toEqual([4100, 59092])
  })

  it('finds the owner from the test connection alone when no listener is listed', () => {
    expect(ownerPids(rows, 5174, [62650])).toEqual([98704])
  })

  it('ignores our own end of the connection and rows without a process', () => {
    expect(ownerPids(rows, 8000, [50249])).toEqual([4100])
    expect(ownerPids(rows, 62649, [])).toEqual([])
  })
})

describe('parseProcessList', () => {
  it('reads a list of processes', () => {
    const json = JSON.stringify([
      { ProcessId: 1, ParentProcessId: 0, Name: 'a.exe', CommandLine: null },
      { ProcessId: 2, ParentProcessId: 1, Name: 'b.exe', CommandLine: 'b --x' },
    ])

    expect(parseProcessList(json)).toEqual([
      { pid: 1, parentPid: 0, name: 'a.exe', commandLine: '' },
      { pid: 2, parentPid: 1, name: 'b.exe', commandLine: 'b --x' },
    ])
  })

  it('reads a single process, which PowerShell does not wrap in a list', () => {
    const json = JSON.stringify({ ProcessId: 7, ParentProcessId: 1, Name: 'c.exe', CommandLine: 'c' })

    expect(parseProcessList(json)).toEqual([{ pid: 7, parentPid: 1, name: 'c.exe', commandLine: 'c' }])
  })

  it('returns nothing for empty output', () => {
    expect(parseProcessList('')).toEqual([])
  })
})

describe('serverRoot', () => {
  const worker = (pid, parentPid, claimedParent = parentPid) => ({
    pid,
    parentPid,
    name: 'python.exe',
    commandLine: `python.exe -c "from multiprocessing.spawn import spawn_main; spawn_main(parent_pid=${claimedParent}, pipe_handle=7)" --multiprocessing-fork`,
  })
  const shell = { pid: 10, parentPid: 1, name: 'powershell.exe', commandLine: 'powershell.exe' }
  const launcher = { pid: 20, parentPid: 10, name: 'uvicorn.exe', commandLine: 'uvicorn.exe main:app --reload' }
  const supervisor = { pid: 30, parentPid: 20, name: 'python.exe', commandLine: 'python.exe uvicorn.exe main:app --reload' }

  it('goes up from a reload worker to the supervisor that holds the port', () => {
    expect(serverRoot(40, [shell, launcher, supervisor, worker(40, 30)])).toBe(30)
  })

  it('leaves a server that has no supervisor alone', () => {
    const vite = { pid: 50, parentPid: 10, name: 'node.exe', commandLine: 'node vite.js' }

    expect(serverRoot(50, [shell, vite])).toBe(50)
  })

  it('does not go up when the parent is gone or is not the one the worker names', () => {
    expect(serverRoot(40, [shell, worker(40, 30)])).toBe(40)
    expect(serverRoot(40, [shell, supervisor, worker(40, 30, 999)])).toBe(40)
  })

  it('does not go up into a process that is not Python', () => {
    const reused = { pid: 30, parentPid: 1, name: 'explorer.exe', commandLine: 'explorer.exe' }

    expect(serverRoot(40, [reused, worker(40, 30)])).toBe(40)
  })

  it('returns the process itself when it is not in the list', () => {
    expect(serverRoot(123, [shell])).toBe(123)
  })
})

describe('parseLsof', () => {
  it('reads one process id per line, once each', () => {
    expect(parseLsof('4100\n59092\n4100\n')).toEqual([4100, 59092])
  })

  it('returns nothing when nothing is listening', () => {
    expect(parseLsof('')).toEqual([])
  })
})
