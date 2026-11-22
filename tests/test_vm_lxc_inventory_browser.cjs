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
    tags: "server;development;analytics;backup;vpn;web;queue;monitoring", ip: "192.0.2.100", uptime: 525600, netin: 36 * 1024 ** 3, netout: 9 * 1024 ** 3, diskread: 64 * 1024 ** 3, diskwrite: 8 * 1024 ** 3,
    update_check: { available: true, count: 2, packages: [] } },
  { vmid: 201, type: "qemu", name: "demo-cortendesk-windows-builder-test", status: "stopped", tags: "builder", uptime: 900, netin: 512 * 1024 ** 3 },
  { vmid: 202, type: "qemu", name: "demo-running-vm", status: "running", uptime: 42, netin: 0, netout: 72 * 1024 ** 3, diskread: null, diskwrite: 5 * 1024 ** 3 },
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
  // Chromium's helper processes can still be writing to the profile when the
  // browser exits; a temporary profile left behind does not fail the check.
  try {
    fs.rmSync(profile, { recursive: true, force: true, maxRetries: 5, retryDelay: 100 })
  } catch {}
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
// A compact row is a button and an open card a div; both open the guest details.
const guestTargets = prefix => `[...document.querySelectorAll('[aria-haspopup=dialog][aria-label^=${JSON.stringify(prefix)}]')].filter(el=>el.getClientRects().length)`
const visibleRows = (prefix = "View details for ") => evaluate(`${guestTargets(prefix)}.map(el=>(el.tagName==='BUTTON' ? 'Row ' : 'Card ')+el.getAttribute('aria-label').slice(${JSON.stringify(prefix)}.length)).filter(label=>/ demo-/.test(label)).sort()`)

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
  await waitFor("Boolean(localStorage.getItem('proxmenux.vmListLayout.v1'))")
  const initialSettings = await evaluate("JSON.parse(localStorage.getItem('proxmenux.vmListLayout.v1'))")

  assert.equal(new Set(await evaluate(`[${type("All types")},${type("VM")},${type("LXC")},${status("All")}].map(el=>el.getBoundingClientRect().height)`)).size, 1)
  await click(type("LXC"))
  await click(status("Updates"))
  assert.deepEqual(await visibleRows(), ["Row demo-container-with-a-long-name"])
  await click(type("VM"))
  assert.ok(await evaluate(`(${status("Updates")}).disabled && (${status("Updates")}).getAttribute('aria-pressed') === 'false'`))
  await click(status("Stopped"))
  assert.deepEqual(await visibleRows(), ["Row demo-cortendesk-windows-builder-test"])
  await click(labelled("Expand visible"))
  await waitFor(`${guestTargets("View details for ")}.some(el=>el.tagName!=='BUTTON')`)
  // Every visible guest is open: the standard view has no columns to choose.
  assert.ok(await evaluate(`(${labelled("Column settings")}).disabled && !document.querySelector('[data-sort-column]')?.getClientRects().length`))

  await send("Page.reload")
  await openInventory()
  assert.equal(await evaluate(`(${type("VM")}).getAttribute('aria-pressed')`), "true")
  assert.deepEqual(await visibleRows(), ["Card demo-cortendesk-windows-builder-test"])
  await click(type("All types"))
  await click(status("All"))
  assert.deepEqual(await visibleRows(), ["Card demo-cortendesk-windows-builder-test", "Row demo-container-with-a-long-name", "Row demo-running-vm"])
  // A mixed list is not the standard view: its columns can be chosen.
  assert.ok(await evaluate(`!(${labelled("Column settings")}).disabled`))
  const details = `[...document.querySelectorAll('[aria-label="View details for demo-cortendesk-windows-builder-test"]')].find(el => el.getClientRects().length)`
  await click(details)
  await waitFor("document.querySelector('[role=dialog] h2')?.textContent.includes('demo-cortendesk-windows-builder-test')")
  await send("Input.dispatchKeyEvent", { type: "rawKeyDown", key: "Escape", code: "Escape", windowsVirtualKeyCode: 27 })
  await waitFor("!document.querySelector('[role=dialog]')")
  // A compact row opens the details too; it does not open a card.
  await click(`[...document.querySelectorAll('button[aria-label="View details for demo-running-vm"]')].find(el => el.getClientRects().length)`)
  await waitFor("document.querySelector('[role=dialog] h2')?.textContent.includes('demo-running-vm')")
  assert.deepEqual(await visibleRows(), ["Card demo-cortendesk-windows-builder-test", "Row demo-container-with-a-long-name", "Row demo-running-vm"])

  await evaluate("localStorage.setItem('proxmenux-ui-language', 'sk')")
  await send("Page.reload")
  await openInventory("VM a LXC", "Filtrovať podľa typu stroja")
  await click(labelled("Rozbaliť všetky"))
  const skOpen = "Zobraziť informácie o stroji "
  // The page runs the full width of the window: at 1194 px the toolbar has
  // room for its desktop row, and the tablet layout begins below that.
  for (const [width, tablet] of [[1194, false], [1024, true], [1440, false]]) {
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
      const cards = [...document.querySelectorAll('div[role=button][aria-haspopup=dialog]')].filter(visible).map((card) => {
        const bounds = card.getBoundingClientRect();
        const list = card.closest('[role=region]');
        const listBounds = list.getBoundingClientRect();
        const inside = (element) => {
          const rect = element.getBoundingClientRect();
          return rect.left >= bounds.left && rect.right <= bounds.right;
        };
        const name = card.querySelector('.truncate');
        return { name: name.textContent, cardFits: bounds.left >= listBounds.left && bounds.right <= listBounds.right + 1 && listBounds.right <= innerWidth
            && list.scrollWidth <= list.clientWidth + 1,
          controlsFit: bounds.height >= 44,
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
  const mobileGuest = `${guestTargets(skOpen)}.find(el => el.getAttribute('aria-label').endsWith('demo-container-with-a-long-name'))`
  await tap(mobileGuest)
  await waitFor("document.querySelector('[role=dialog] h2')?.textContent.includes('demo-container-with-a-long-name')")
  await send("Input.dispatchKeyEvent", { type: "rawKeyDown", key: "Escape", code: "Escape", windowsVirtualKeyCode: 27 })
  await waitFor("!document.querySelector('[role=dialog]')")
  await new Promise(resolve => setTimeout(resolve, 350))
  await send("Emulation.setTouchEmulationEnabled", { enabled: false })
  await send("Emulation.setDeviceMetricsOverride", { width: 1440, height: 960, deviceScaleFactor: 1, mobile: false })
  const currentLayout = () => evaluate("JSON.parse(localStorage.getItem('proxmenux.vmListLayout.v1'))")
  const added = ["state", "tags", "uptime", "net", "io"]
  assert.ok(added.every(column => (initialSettings.hidden).includes(column)))

  const legacy = { order: ["type","name","cpu","ip","memory","disk","updates"], hidden: ["ip"],
    widths: { type: 112 }, sort: { column: "cpu", direction: "desc" }, expanded: false, exceptions: ["qemu:201"] }
  await evaluate(`localStorage.setItem('proxmenux.vmListLayout.v1', ${JSON.stringify(JSON.stringify(legacy))})`)
  await send("Page.reload")
  await openInventory("VM a LXC", "Filtrovať podľa typu stroja")
  await waitFor("JSON.parse(localStorage.getItem('proxmenux.vmListLayout.v1')).order.length===12")
  const migrated = await currentLayout()
  assert.deepEqual(migrated.order, [...legacy.order, ...added])
  assert.deepEqual(new Set(migrated.hidden), new Set([...legacy.hidden, ...added]))
  assert.deepEqual(migrated.widths, legacy.widths)
  assert.deepEqual(migrated.sort, legacy.sort)
  assert.deepEqual(migrated.exceptions, legacy.exceptions)

  const settings = labelled("Nastavenie stĺpcov")
  const input = title => `[...document.querySelectorAll('fieldset label')].find(el=>el.textContent.trim()===${JSON.stringify(title)})?.querySelector('input')`
  const sortButton = column => `document.querySelector('[data-sort-column="${column}"]')`
  const region = "document.querySelector('[role=region][aria-label=\"Virtuálne stroje a kontajnery\"]')"
  const headers = () => evaluate("[...document.querySelectorAll('[data-sort-column]')].map(e=>e.dataset.sortColumn)")
  const compact = name => `document.querySelector(${JSON.stringify(`button[aria-label="${skOpen}${name}"]`)})`
  const card = name => `[...document.querySelectorAll(${JSON.stringify(`div[role=button][aria-label="${skOpen}${name}"]`)})].find(el=>el.getClientRects().length)`
  const listOrder = () => evaluate(`[...(${region}).querySelectorAll('button[aria-haspopup=dialog][aria-label]')].map(el=>el.getAttribute('aria-label')).filter(label=>label.startsWith(${JSON.stringify(skOpen + "demo-")})).map(label=>label.slice(${JSON.stringify(skOpen)}.length))`)
  const cell = (name, column) => `(() => {
    const heading = ${sortButton(column)};
    const columnIndex = [...heading.parentElement.parentElement.children].indexOf(heading.parentElement);
    return [...(${compact(name)}).children].filter(el => el.id)[columnIndex];
  })()`
  const readCell = (name, column) => evaluate(`(${cell(name,column)}).textContent`)
  const testLxc = "demo-container-with-a-long-name"
  const stoppedVm = "demo-cortendesk-windows-builder-test"
  const runningVm = "demo-running-vm"
  await click(labelled("Zbaliť všetky"))
  await click(settings)
  for (const label of ["Stav", "Značky", "Doba behu", "Sieť I/O", "Disk I/O"]) {
    assert.ok(await evaluate(`!(${input(label)}).checked`))
    await click(input(label))
  }
  assert.equal((await headers()).length,11)
  assert.match(await readCell(testLxc,"uptime"), /^6 d 2 h$/)
  assert.equal(await readCell(stoppedVm,"uptime"), "—")
  assert.equal(await readCell(runningVm,"uptime"), "< 1 min")
  assert.equal(await readCell(stoppedVm,"net"), "—")
  assert.match(await readCell(runningVm,"io"), /↓\s+—.*↑\s+5 GB/)
  assert.match(await readCell(runningVm,"net"), /↓\s+0 B.*↑\s+72 GB/)
  assert.match(await readCell(testLxc,"net"), /↓\s+36 GB.*↑\s+9 GB/)
  const fills=(name,column)=>evaluate(`[...(${cell(name,column)}).querySelectorAll('span[style*="width"]')].map(e=>e.style.width)`)
  assert.deepEqual(await fills(testLxc,"net"), ["50%", "12.5%"])
  assert.deepEqual(await fills(testLxc,"io"), ["100%", "12.5%"])
  await click(groupButton("Filtrovať podľa typu stroja", "LXC"))
  assert.deepEqual(await fills(testLxc,"net"), ["50%", "12.5%"])
  await click(groupButton("Filtrovať podľa typu stroja", "Všetky typy"))
  const setUnit = value => evaluate(`localStorage.setItem('proxmenux-network-unit',${JSON.stringify(value)}); window.dispatchEvent(new Event('networkUnitChanged'))`)
  await setUnit("Bits")
  await waitFor(`(${cell(testLxc,"net")}).textContent.includes('309.24 Gb')`)
  assert.match(await readCell(testLxc,"io"), /64 GB/)
  await setUnit("Bytes")
  const dotStyle = clickTarget => evaluate(`[...(${clickTarget}).querySelectorAll('span[style*="background-color"]')].map(e=>getComputedStyle(e).backgroundColor)`)
  const tagColors = await dotStyle(cell(testLxc,"tags"))
  assert.equal(tagColors.length, 8)
  assert.equal(await readCell(testLxc,"tags"), "")
  assert.equal(await readCell(runningVm,"tags"), "")
  await click(labelled("Rozbaliť všetky"))
  assert.deepEqual(await dotStyle(card(testLxc)), tagColors)
  await click(labelled("Zbaliť všetky"))

  await click(sortButton("net"))
  assert.deepEqual(await listOrder(), [runningVm, testLxc, stoppedVm])
  await click(sortButton("uptime"))
  assert.deepEqual(await listOrder(), [testLxc, runningVm, stoppedVm])
  const netIndex = (await headers()).indexOf("net")
  await evaluate(`(${sortButton("net")}).dispatchEvent(new KeyboardEvent('keydown', {key:'ArrowLeft', shiftKey:true, bubbles:true, cancelable:true}))`)
  assert.equal((await headers()).indexOf("net"),netIndex-1)
  await evaluate(`(${sortButton("net")}).parentElement.querySelector('[aria-keyshortcuts="ArrowLeft ArrowRight"]').dispatchEvent(new KeyboardEvent('keydown', {key:'ArrowRight',bubbles:true,cancelable:true}))`)
  const resized=await currentLayout()
  assert.equal(resized.widths.net,160)
  await click(input("Sieť I/O"))
  assert.ok(!(await headers()).includes("net"))
  await click(input("Sieť I/O"))
  const customized=await currentLayout()
  await send("Page.reload")
  await openInventory("VM a LXC", "Filtrovať podľa typu stroja")
  await waitFor(`Boolean(${sortButton("net")})`)
  assert.deepEqual(await currentLayout(),customized)
  assert.equal(await evaluate(`(${sortButton("net")}).parentElement.getBoundingClientRect().width`),160)
  await click(settings)
  await click(input("IP adresa"))
  await click(settings)
  assert.equal((await headers()).length,12)

  for (const width of [1194,1024,834,768]) {
    await send("Emulation.setDeviceMetricsOverride", { width, height: 834, deviceScaleFactor: 1, mobile: false })
    await waitFor(`innerWidth===${width}`)
    const frame = await evaluate(`(() => {
      const viewport = ${region};
      const row = ${compact(testLxc)};
      const heading = ${sortButton("net")};
      const transfer = ${cell(testLxc,"net")};
      const edge = viewport.getBoundingClientRect().right;
      const aligned = Math.abs(heading.parentElement.getBoundingClientRect().x-transfer.getBoundingClientRect().x)<1;
      return {viewportFits:edge<=innerWidth, canScroll:viewport.scrollWidth>viewport.clientWidth, aligned, height:row.offsetHeight};
    })()`)
    assert.ok(frame.viewportFits && frame.canScroll && frame.aligned && frame.height===36,`Tablet layout ${width}: ${JSON.stringify(frame)}`)
    console.log("Tablet width",width, "the wide list scrolls within its panel")
  }
  await evaluate(`(${region}).scrollLeft=(${region}).scrollWidth;`)
  // One open card among compact rows: open the LXC alone through the type filter.
  await click(groupButton("Filtrovať podľa typu stroja", "LXC"))
  await click(labelled("Rozbaliť zobrazené"))
  await click(groupButton("Filtrovať podľa typu stroja", "Všetky typy"))
  assert.ok(await evaluate(`(() => {
    const bounds=(${region}).getBoundingClientRect();
    const open=(${card(testLxc)}).getBoundingClientRect();
    return open.left >= bounds.left-1 && open.right<=bounds.right+1;
  })()`))

  await send("Emulation.setTouchEmulationEnabled", { enabled:true, maxTouchPoints:1 })
  for (const width of [402,390,320]) {
    await send("Emulation.setDeviceMetricsOverride", { width, height: 812, deviceScaleFactor: 1, mobile: true })
    await waitFor(`innerWidth===${width}`)
    // The phone layout follows the viewport on the next render.
    await waitFor(`(${region}).dataset.phone === "true"`)
    const frame = await evaluate(`(() => {
      const viewport=${region};
      const row=${compact(stoppedVm)};
      const open=${card(testLxc)};
      return {
        noNestedScroll:viewport.scrollWidth<=viewport.clientWidth+1,
        rowHeight:row.getBoundingClientRect().height,
        rowFits:row.getBoundingClientRect().right<=innerWidth,
        cardFits:open.getBoundingClientRect().right<=innerWidth,
        phoneColumns:[...row.children].filter(el=>el.id).length
      };
    })()`)
    // A phone shows the name and its own columns: CPU, memory and disk by default.
    assert.deepEqual(frame,{noNestedScroll:true,rowHeight:44,rowFits:true,cardFits:true,phoneColumns:4})
    console.log("Mobile width",width,"fits with the phone columns")
  }
  await click(settings)
  assert.ok(await evaluate(`(() => {
    const picker=document.getElementById((${settings}).getAttribute('aria-controls'));
    return !picker.hidden && picker.querySelectorAll('input[type=checkbox]').length===11
      && picker.scrollWidth<=picker.clientWidth+1 && picker.getBoundingClientRect().right<=innerWidth;
  })()`))
  await click(settings)
  await tap(card(testLxc))
  await waitFor("document.querySelector('[role=dialog] h2')?.textContent.includes('demo-container-with-a-long-name')")
  assert.match(await evaluate("document.querySelector('[role=dialog]').textContent"), /Sieť I\/O/)
  console.log("Optional metrics, legacy settings, tag colors, transfer scales, sorting and persisted column settings passed")
  assert.deepEqual(rejectedWrites, [])
  assert.deepEqual(errors, [])
  console.log("VM/LXC filters, saved selection, scoped expansion, rows and cards opening the details, tablet toolbar and mobile cards passed")
}

const deadline = setTimeout(() => {
  console.error("Browser check timed out")
  process.exitCode = 1
  browser.kill()
}, 120000)
run().catch(error => { console.error(error); process.exitCode = 1 }).finally(() => {
  clearTimeout(deadline)
  browser.kill()
})
