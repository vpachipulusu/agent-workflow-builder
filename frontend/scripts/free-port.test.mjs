import { spawn, spawnSync } from 'node:child_process'
import net from 'node:net'
import { fileURLToPath } from 'node:url'
import { afterEach, describe, expect, it } from 'vitest'

const SCRIPT = fileURLToPath(new URL('./free-port.mjs', import.meta.url))
const HOST = '127.0.0.1'

const freePort = port => spawnSync(process.execPath, [SCRIPT, String(port)], { encoding: 'utf8' })

const unusedPort = () =>
  new Promise(resolve => {
    const server = net.createServer().listen(0, HOST, () => {
      const { port } = server.address()
      server.close(() => resolve(port))
    })
  })

const accepts = port =>
  new Promise(resolve => {
    const socket = net.connect({ host: HOST, port })
    socket.once('connect', () => resolve(true)).once('error', () => resolve(false))
    socket.once('close', () => socket.destroy())
  }).then(open => open)

/** A stand-in for a forgotten dev server: a separate process listening on the port. */
const startServer = port =>
  new Promise((resolve, reject) => {
    const code = `require('node:net').createServer(s => s.resume()).listen(${port}, '${HOST}', () => console.log('up'))`
    const child = spawn(process.execPath, ['-e', code], { stdio: ['ignore', 'pipe', 'inherit'] })
    child.stdout.once('data', () => resolve(child))
    child.once('error', reject)
  })

const exited = child =>
  new Promise(resolve => (child.exitCode !== null || child.signalCode !== null ? resolve() : child.once('exit', resolve)))

describe('free-port', () => {
  const children = []
  afterEach(() => children.splice(0).forEach(child => child.kill()))

  it('does nothing when the port is free', async () => {
    const result = freePort(await unusedPort())

    expect(result.status).toBe(0)
    expect(result.stdout).toBe('')
  })

  it('stops the process that holds the port', async () => {
    const port = await unusedPort()
    const server = await startServer(port)
    children.push(server)

    const result = freePort(port)
    await exited(server)

    expect(result.status).toBe(0)
    expect(result.stdout).toContain(`Port ${port} is in use`)
    expect(result.stdout).toContain(`pid ${server.pid}`)
    expect(await accepts(port)).toBe(false)
  }, 30_000)

  it('refuses a port that is not a number', () => {
    const result = freePort('abc')

    expect(result.status).toBe(1)
    expect(result.stderr).toMatch(/port/i)
  })
})
