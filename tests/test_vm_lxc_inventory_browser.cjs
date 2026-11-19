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
  { vmid: 100, type: "lxc", name: "demo-container-with-a-long-name", status: "running", cpu: 0.96, mem: 970, disk: 930,
    tags: "server;development;analytics;backup;vpn;web;queue;monitoring",
    update_check: { available: true, count: 2, packages: [] } },
  { vmid: 201, type: "qemu", name: "demo-cortendesk-windows-builder-test", status: "stopped", tags: "builder" },
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

async function tap(selector) {
  const point = await evaluate(`(() => {
    const target = (${selector});
    target.scrollIntoView({block:"center"});
    const rect = target.getBoundingClientRect();
    const x = rect.left + rect.width / 2, y = rect.top + rect.height / 2;
    if (!target.contains(document.elementFromPoint(x, y))) throw Error("Tap target is obscured");
    return {x, y};
  })()`)
  await send("Input.dispatchTouchEvent", { type: "touchStart", touchPoints: [point] })
  await send("Input.dispatchTouchEvent", { type: "touchEnd", touchPoints: [] })
}

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
  assert.deepEqual(await visibleRows(), ["Expand demo-container-with-a-long-name"])
  await click(type("VM"))
  assert.ok(await evaluate(`(${status("Updates")}).disabled && (${status("Updates")}).getAttribute('aria-pressed') === 'false'`))
  await click(status("Stopped"))
  assert.deepEqual(await visibleRows(), ["Expand demo-cortendesk-windows-builder-test"])
  await click(labelled("Expand visible"))
  await waitFor(`Boolean(${labelled("Collapse demo-cortendesk-windows-builder-test")})`)

  await send("Page.reload")
  await openInventory()
  assert.equal(await evaluate(`(${type("VM")}).getAttribute('aria-pressed')`), "true")
  assert.deepEqual(await visibleRows(), ["Collapse demo-cortendesk-windows-builder-test"])
  await click(type("All types"))
  await click(status("All"))
  assert.deepEqual(await visibleRows(), ["Collapse demo-cortendesk-windows-builder-test", "Expand demo-container-with-a-long-name", "Expand demo-running-vm"])
  const details = `[...document.querySelectorAll('[aria-label="View details for demo-cortendesk-windows-builder-test"]')].find(el => el.getClientRects().length)`
  await click(details)
  await waitFor("document.querySelector('[role=dialog] h2')?.textContent.includes('demo-cortendesk-windows-builder-test')")
  assert.ok(await evaluate(`!${labelled("Expand demo-cortendesk-windows-builder-test")}`))

  await evaluate("localStorage.setItem('proxmenux-ui-language', 'sk')")
  await send("Page.reload")
  await openInventory("VM a LXC", "Filtrovať podľa typu stroja")
  await click("[...document.querySelectorAll('button[aria-expanded=false]')].find(button => button.getAttribute('aria-label')?.endsWith('demo-container-with-a-long-name'))")
  await click("[...document.querySelectorAll('button[aria-expanded=false]')].find(button => button.getAttribute('aria-label')?.endsWith('demo-running-vm'))")
  for (const [width, tablet] of [[1194, true], [1024, true], [1440, false]]) {
    await send("Emulation.setDeviceMetricsOverride", { width, height: 834, deviceScaleFactor: 1, mobile: false })
    const types = labelled("Filtrovať podľa typu stroja")
    await waitFor(`(${types}.parentElement.dataset.layout === 'tablet') === ${tablet}`)
    const layout = await evaluate(`(() => {
      const types = ${types};
      const toolbar = types.parentElement;
      const search = toolbar.querySelector('input');
      const status = ${labelled("Filtrovať virtuálne stroje a kontajnery")};
      const actions = [...toolbar.children].find(element => element !== types && element !== status && element.contains(search) === false);
      const center = element => { const rect = element.getBoundingClientRect(); return rect.top + rect.height / 2; };
      return {
        order: [...types.querySelectorAll('button')].map(button => button.textContent.trim()),
        leftToRight: types.getBoundingClientRect().right <= status.getBoundingClientRect().left,
        buttonCenters: [...toolbar.querySelectorAll('[role=group] button')].map(center),
        searchAbove: search.getBoundingClientRect().bottom <= types.getBoundingClientRect().top,
        searchFullWidth: search.getBoundingClientRect().width === toolbar.getBoundingClientRect().width,
        actionsLast: toolbar.lastElementChild === actions,
        rightEdge: Math.abs(actions.getBoundingClientRect().right - toolbar.getBoundingClientRect().right),
        searchCenter: center(search)
      };
    })()`)
    assert.deepEqual(layout.order, ["Všetky typy", "LXC", "VM"])
    assert.ok(layout.leftToRight && layout.buttonCenters.length === 10)
    const centers = tablet ? layout.buttonCenters : [...layout.buttonCenters, layout.searchCenter]
    assert.ok(Math.max(...centers) - Math.min(...centers) < 2, `Toolbar wrapped at ${width}: ${JSON.stringify(layout)}`)
    if (tablet) assert.ok(layout.searchAbove && layout.searchFullWidth && layout.actionsLast && layout.rightEdge < 1)
    else assert.ok(!layout.searchAbove && !layout.actionsLast)
  }
  await send("Emulation.setTouchEmulationEnabled", { enabled: true, maxTouchPoints: 1 })
  for (const width of [402, 390, 320]) {
    await send("Emulation.setDeviceMetricsOverride", { width, height: 812, deviceScaleFactor: 1, mobile: true })
    const controls = await evaluate(`[...document.querySelectorAll('[aria-label="Filtrovať podľa typu stroja"] button, [aria-label="Filtrovať virtuálne stroje a kontajnery"] button')].map(button => {
      const rect = button.getBoundingClientRect();
      return {label:button.textContent.trim(), height:rect.height, insideViewport:rect.left>=0 && rect.right<=innerWidth};
    })`)
    assert.equal(controls.length, 7)
    assert.deepEqual(controls.slice(0, 3).map(control => control.label), ["Všetky typy", "LXC", "VM"])
    assert.ok(controls.every(control => control.insideViewport && control.height === controls[0].height))
    const layout = await evaluate(`(() => {
      const visible = (e) => e.getClientRects().length > 0;
      const cards = [...document.querySelectorAll('[data-collapse-guest]')].filter(visible).map((heading) => {
        const card = heading.parentElement;
        const metrics = card.querySelector('button[aria-haspopup="dialog"]');
        const bounds = card.getBoundingClientRect();
        const list = card.closest('[id]').parentElement.parentElement;
        const listBounds = list.getBoundingClientRect();
        const inside = (element) => {
          const rect = element.getBoundingClientRect();
          return rect.left >= bounds.left && rect.right <= bounds.right;
        };
        const name = heading.querySelector('.truncate');
        return { name: name.textContent, cardFits: bounds.left >= listBounds.left && bounds.right <= listBounds.right + 1 && listBounds.right <= innerWidth
            && list.scrollWidth <= list.clientWidth + 1,
          controlsFit: bounds.width >= 1 && inside(heading) && inside(metrics) && metrics.getBoundingClientRect().height >= 44,
          nameFits: inside(name) && name.clientWidth >= 16 && getComputedStyle(name).textOverflow === "ellipsis",
          nameTruncated: name.scrollWidth > name.clientWidth };
      });
      return { viewport: innerWidth, scroll: document.documentElement.scrollWidth, cards };
    })()`)
    assert.ok(layout.cards.length === guests.length && layout.cards.every(card => card.cardFits && card.controlsFit && card.nameFits)
      && guests.slice(0, 2).every(guest => layout.cards.some(card => card.name === guest.name && card.nameTruncated))
      && layout.viewport === width, `Mobile card overflow at ${width}: ${JSON.stringify(layout)}`)
  }
  await send("Emulation.setDeviceMetricsOverride", { width: 402, height: 812, deviceScaleFactor: 1, mobile: true })
  const mobileGuest = "[...document.querySelectorAll('[data-collapse-guest]')].find(button => button.getClientRects().length && button.getAttribute('aria-label').endsWith('demo-container-with-a-long-name'))"
  await tap(`(${mobileGuest}).parentElement.querySelector('button[aria-haspopup=dialog]')`)
  await waitFor("document.querySelector('[role=dialog] h2')?.textContent.includes('demo-container-with-a-long-name')")
  await send("Input.dispatchKeyEvent", { type: "rawKeyDown", key: "Escape", code: "Escape", windowsVirtualKeyCode: 27 })
  await waitFor("!document.querySelector('[role=dialog]')")
  await new Promise(resolve => setTimeout(resolve, 350))
  await tap(mobileGuest)
  await waitFor(`!(${mobileGuest})`)
  assert.deepEqual(rejectedWrites, [])
  assert.deepEqual(errors, [])
  console.log("VM/LXC filters, saved selection, scoped expansion, original details, tablet toolbar and mobile cards passed")
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
