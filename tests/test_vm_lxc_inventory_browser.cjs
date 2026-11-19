// Run after npm run build in AppImage: node tests/test_vm_lxc_inventory_browser.cjs
// Set CHROMIUM_BIN if Chromium is not on PATH. Requests are intercepted before navigation.
const assert = require("node:assert/strict")
const fs = require("node:fs")
const os = require("node:os")
const path = require("node:path")
const { spawn } = require("node:child_process")

const app = path.resolve(__dirname, "../AppImage")
const output = path.join(app, "out")
const version = require(path.join(app, "package.json")).version
const origin = "http://inventory.fixture.invalid"
const profile = fs.mkdtempSync(path.join(os.tmpdir(), "vm-lxc-inventory-"))
const browser = spawn(process.env.CHROMIUM_BIN || "chromium", [
  "--headless", "--disable-gpu", "--disable-background-networking", "--no-first-run",
  "--remote-debugging-pipe", "--user-data-dir=" + profile,
  ...(process.env.CHROMIUM_NO_SANDBOX === "1" ? ["--no-sandbox"] : []),
], { stdio: ["ignore", "ignore", "ignore", "pipe", "pipe"] })
const pending = new Map()
const rejectedWrites = []
const errors = []
let sessionId
let id = 0
let buffer = ""

const guests = [
  { vmid: 100, type: "lxc", name: "demo-container", status: "running", update_check: { available: true, count: 2, packages: [] } },
  { vmid: 201, type: "qemu", name: "demo-stopped-vm", status: "stopped" },
  { vmid: 202, type: "qemu", name: "demo-running-vm", status: "running" },
].map(guest => ({ cpu: 0, mem: 0, maxmem: 1024, disk: 0, maxdisk: 1024, uptime: 0, ...guest }))

function send(method, params = {}) {
  return new Promise((resolve, reject) => {
    const message = { id: ++id, method, params, sessionId }
    pending.set(id, { resolve, reject })
    browser.stdio[3].write(JSON.stringify(message) + "\0")
  })
}

async function respond({ requestId, request }) {
  const url = new URL(request.url)
  const reply = (responseCode, value, contentType) => send("Fetch.fulfillRequest", {
    requestId, responseCode, body: Buffer.from(value).toString("base64"),
    responseHeaders: [{ name: "Content-Type", value: contentType }],
  })
  if (request.method !== "GET") {
    rejectedWrites.push([request.method, url.pathname])
    return reply(403, "", "text/plain")
  }
  if (url.origin !== origin) return reply(404, "", "text/plain")
  const guestId = /^\/api\/vms\/(\d+)$/.exec(url.pathname)?.[1]
  const guest = guests.find(item => String(item.vmid) === guestId)
  const data = {
    "/api/auth/status": { auth_configured: true, auth_enabled: true, authenticated: true },
    "/api/auth/me": { username: "fixture", authenticated: true, role: "admin" },
    "/api/health": { status: "OK", health: { status: "OK", details: {} } },
    "/api/system": { hostname: "fixture", platform: "pve", cpu_cores: 8, memory_total: 32, memory_used: 5, memory_usage: 16, load_average: [0, 0, 0] },
    "/api/system-info": { hostname: "fixture", uptime: "1d", product: "pve" },
    "/api/vms": guests,
    "/api/backups/storages": [],
  }[url.pathname] ?? (guest && { ...guest, config: {} })
  if (url.pathname.startsWith("/api/")) return reply(data ? 200 : 404, JSON.stringify(data ?? {}), "application/json")
  const file = path.join(output, url.pathname === "/" ? "index.html" : url.pathname)
  if (!fs.existsSync(file) || !fs.statSync(file).isFile()) return reply(404, "", "text/plain")
  const types = { ".html": "text/html", ".css": "text/css", ".js": "text/javascript", ".json": "application/json" }
  return reply(200, fs.readFileSync(file), types[path.extname(file)] || "application/octet-stream")
}

browser.stdio[3].on("error", () => {})
browser.stdio[4].on("error", () => {})
browser.on("error", error => { for (const reply of pending.values()) reply.reject(error) })
browser.on("exit", () => {
  for (const reply of pending.values()) reply.reject(Error("Chromium exited"))
  fs.rmSync(profile, { recursive: true, force: true })
})
browser.stdio[4].on("data", data => {
  buffer += data.toString()
  const messages = buffer.split("\0")
  buffer = messages.pop()
  for (const raw of messages) {
    const message = JSON.parse(raw)
    if (message.id) {
      const reply = pending.get(message.id)
      pending.delete(message.id)
      if (message.error) reply?.reject(Error(message.error.message))
      else reply?.resolve(message.result)
    } else if (message.method === "Fetch.requestPaused") {
      respond(message.params).catch(error => errors.push(error.message))
    } else if (message.method === "Runtime.exceptionThrown") {
      errors.push(message.params.exceptionDetails.text)
    }
  }
})

async function evaluate(expression) {
  const { result, exceptionDetails } = await send("Runtime.evaluate", { expression, returnByValue: true })
  if (exceptionDetails) throw Error(exceptionDetails.exception?.description || exceptionDetails.text)
  return result.value
}
async function waitFor(expression) {
  for (let attempt = 0; attempt < 100; attempt++) {
    if (await evaluate(expression)) return
    await new Promise(resolve => setTimeout(resolve, 100))
  }
  throw Error("Timed out: " + expression)
}
const labelled = label => `document.querySelector(${JSON.stringify(`[aria-label="${label}"]`)})`
const groupButton = (group, label) => `[...${labelled(group)}?.querySelectorAll('button') ?? []].find(button => button.textContent.trim() === ${JSON.stringify(label)} || [...button.querySelectorAll('span')].some(span => span.textContent === ${JSON.stringify(label)}))`
const type = label => groupButton("Filter by guest type", label)
const status = label => groupButton("Filter virtual machines and containers", label)
const click = selector => evaluate(`(${selector}).click()`)
const visibleRows = () => evaluate("[...document.querySelectorAll('button[aria-expanded][aria-label]')].filter(button=>button.getClientRects().length).map(button=>button.getAttribute('aria-label')).filter(label=>/^(Expand|Collapse) demo-/.test(label)).sort()")

async function openInventory(tabLabel = "VMs & LXCs", filterLabel = "Filter by guest type") {
  const trigger = `[...document.querySelectorAll('[role=tab]')].find(button=>button.textContent.trim()===${JSON.stringify(tabLabel)})`
  await waitFor(`Boolean(${trigger})`)
  await evaluate(`(${trigger}).dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true}))`)
  await waitFor(`Boolean(${labelled(filterLabel)}?.getClientRects().length)`)
}

async function run() {
  const { targetId } = await send("Target.createTarget", { url: "about:blank" })
  sessionId = (await send("Target.attachToTarget", { targetId, flatten: true })).sessionId
  await send("Runtime.enable")
  await send("Page.enable")
  await send("Fetch.enable", { patterns: [{ urlPattern: "*" }] })
  await send("Emulation.setDeviceMetricsOverride", { width: 1440, height: 960, deviceScaleFactor: 1, mobile: false })
  await send("Page.addScriptToEvaluateOnNewDocument", { source: `
    if (!localStorage.getItem('proxmenux-ui-language')) localStorage.setItem('proxmenux-ui-language','en');
    localStorage.setItem('proxmenux-onboarding-seen','true');
    localStorage.setItem('proxmenux-last-seen-version',${JSON.stringify(version)});
    localStorage.setItem('proxmenux-auth-token','fixture');
  ` })
  await send("Page.navigate", { url: origin + "/" })
  await openInventory()

  assert.equal(new Set(await evaluate(`[${type("All types")},${type("VM")},${type("LXC")},${status("All")}].map(el=>el.getBoundingClientRect().height)`)).size, 1)
  await click(type("LXC"))
  await click(status("Updates"))
  assert.deepEqual(await visibleRows(), ["Expand demo-container"])
  await click(type("VM"))
  assert.ok(await evaluate(`(${status("Updates")}).disabled && (${status("Updates")}).getAttribute('aria-pressed') === 'false'`))
  await click(status("Stopped"))
  assert.deepEqual(await visibleRows(), ["Expand demo-stopped-vm"])
  await click(labelled("Expand visible"))
  await waitFor(`Boolean(${labelled("Collapse demo-stopped-vm")})`)

  await send("Page.reload")
  await openInventory()
  assert.equal(await evaluate(`(${type("VM")}).getAttribute('aria-pressed')`), "true")
  assert.deepEqual(await visibleRows(), ["Collapse demo-stopped-vm"])
  await click(type("All types"))
  await click(status("All"))
  assert.deepEqual(await visibleRows(), ["Collapse demo-stopped-vm", "Expand demo-container", "Expand demo-running-vm"])
  const details = `[...document.querySelectorAll('[aria-label="View details for demo-stopped-vm"]')].find(el => el.getClientRects().length)`
  await click(details)
  await waitFor("document.querySelector('[role=dialog] h2')?.textContent.includes('demo-stopped-vm')")
  assert.ok(await evaluate(`!${labelled("Expand demo-stopped-vm")}`))

  await evaluate("localStorage.setItem('proxmenux-ui-language', 'sk')")
  await send("Page.reload")
  await openInventory("VM a LXC", "Filtrovať podľa typu stroja")
  for (const width of [390, 320]) {
    await send("Emulation.setDeviceMetricsOverride", { width, height: 960, deviceScaleFactor: 1, mobile: false })
    const controls = await evaluate(`[...document.querySelectorAll('[aria-label="Filtrovať podľa typu stroja"] button, [aria-label="Filtrovať virtuálne stroje a kontajnery"] button')].map(button => {
      const rect = button.getBoundingClientRect();
      return {height:rect.height, insideViewport:rect.left>=0 && rect.right<=innerWidth};
    })`)
    assert.equal(controls.length, 7)
    assert.ok(controls.every(control => control.insideViewport && control.height === controls[0].height))
  }
  assert.deepEqual(rejectedWrites, [])
  assert.deepEqual(errors, [])
  console.log("VM/LXC inventory filters, saved selection, scoped expansion, original details and narrow Slovak controls passed")
}

const deadline = setTimeout(() => {
  console.error("Browser check timed out")
  process.exitCode = 1
  browser.kill()
}, 60000)
run().catch(error => { console.error(error); process.exitCode = 1 }).finally(() => {
  clearTimeout(deadline)
  browser.kill()
})
