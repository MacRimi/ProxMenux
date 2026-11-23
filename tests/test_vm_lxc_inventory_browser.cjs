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
  "--headless", "--disable-gpu", "--disable-renderer-backgrounding", "--disable-backgrounding-occluded-windows",
  "--disable-background-timer-throttling", "--disable-background-networking", "--no-first-run",
  "--remote-debugging-pipe", "--user-data-dir=" + profile,
  ...(process.env.CHROMIUM_NO_SANDBOX === "1" ? ["--no-sandbox"] : []),
], { stdio: ["ignore", "ignore", "ignore", "pipe", "pipe"] })
const browserClosed = new Promise(resolve => browser.once("close", resolve))
const pending = new Map()
const rejectedWrites = []
const errors = []
const lxcRequests = []
const firewallRequests = []
const firewallWrites = []
const firewallSettingsRequests = []
const firewallSettingsWrites = []
let wizardSwitchColors
let firewallEditor = false
let firewallSettingsEditor = false
let firewallSettingsEnabled = false
let firewallAddedInterface = false
let fixtureFirewallRules = [
  { pos: 0, action: "ACCEPT", type: "in", enabled: true, proto: "tcp", dport: "443", comment: "Web fixture" },
  { pos: 1, action: "web-access", type: "group", enabled: false },
  { pos: 2, action: "DROP", type: "out", enabled: true },
]
let firewallLogReply = 200
let firewallRulesReply = 200
let fixtureRuleRevision = "fixture-revision"
let legacyMoveResponse = false
let firewallHasLogs = false
const lxcBase = "/api/plain-lxc/v1/"
const lxcTemplate = "local:vztmpl/debian-13-standard_13_amd64.tar.zst"
const catalogTemplate = "ubuntu-24.04-standard_24.04_amd64.tar.zst"
const downloadedTemplate = "local:vztmpl/" + catalogTemplate
let lxcCreateStatus = "not_submitted"
let lxcDownloaded = false
let accessMode = "password"
let isAdmin = true
let sessionId
let id = 0
let buffer = ""

const guests = [
  { vmid: 100, type: "lxc", name: "demo-container-with-a-long-name", status: "running", cpu: 0.96, mem: 970, disk: 930,
    tags: "server;development;analytics;backup;vpn;web;queue;monitoring", ip: "192.0.2.100", uptime: 525600, netin: 36 * 1024 ** 3, netout: 9 * 1024 ** 3, diskread: 64 * 1024 ** 3, diskwrite: 8 * 1024 ** 3,
    update_check: { available: true, count: 2, packages: [] } },
  { vmid: 201, type: "qemu", name: "demo-cortendesk-windows-builder-test", status: "stopped", tags: "builder", uptime: 900, netin: 512 * 1024 ** 3 },
  { vmid: 202, type: "qemu", name: "demo-running-vm", status: "running", uptime: 42, netin: 0, netout: 72 * 1024 ** 3, diskread: null, diskwrite: 5 * 1024 ** 3 },
].map(guest => ({ node: "fixture", cpu: 0, mem: 0, maxmem: 1024, disk: 0, maxdisk: 1024, uptime: 0, ...guest }))

function send(method, params = {}, targetSession = sessionId) {
  return new Promise((resolve, reject) => {
    const message = { id: ++id, method, params }
    if (targetSession) message.sessionId = targetSession
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
  if (url.origin === origin && url.pathname.startsWith(lxcBase)) {
    const action = url.pathname.slice(lxcBase.length)
    const body = request.postData && JSON.parse(request.postData)
    lxcRequests.push({ action, method: request.method, body })
    const json = value => reply(200, JSON.stringify(value), "application/json")
    if (action === "context" && request.method === "GET") return json({
      node: "fixture", architecture: "amd64", next_vmid: lxcCreateStatus === "succeeded" ? 242 : 241,
      templates: lxcDownloaded ? [lxcTemplate, downloadedTemplate] : [lxcTemplate],
      catalog: [catalogTemplate], catalog_state: "available", template_storages: ["local"],
      storages: ["local-lvm"], bridges: { vmbr0: { vlan_supported: true } }, limits: { cores: 8, ram_mib: 8192 },
      capabilities: { mount_points: 256, devices: 32 }, hardware: [], hardware_errors: false,
      defaults: { rootfs: { size_gib: 8 }, cpu: { cores: 1 }, memory: { ram_mib: 512, swap_mib: 512 },
        nesting: true, onboot: false, start_after_create: false, prepare_system: false },
    })
    if (action === "plan" && request.method === "POST") return json({
      summary: { ...body.spec, dns: { nameservers: [], search_domains: [] } },
      warnings: ["no_network"], check: "checked-plan", receipt: "same-operation",
    })
    if (action === "download/plan" && request.method === "POST") {
      return json({ check: "checked-download", receipt: "same-download" })
    }
    if (action === "download" && request.method === "POST") {
      lxcDownloaded = true
      return send("Fetch.failRequest", { requestId, errorReason: "ConnectionReset" })
    }
    if (action === "create" && request.method === "POST") {
      lxcCreateStatus = "running"
      return send("Fetch.failRequest", { requestId, errorReason: "ConnectionReset" })
    }
    if (action === "status" && request.method === "GET") {
      const receipt = Object.entries(request.headers)
        .find(([key]) => key.toLowerCase() === "x-proxmenux-lxc-receipt")?.[1]
      if (receipt === "same-download") {
        return json({ action: "download_template", volume_id: downloadedTemplate,
          status: lxcDownloaded ? "succeeded" : "awaiting", phase: "download", task_warnings: false })
      }
      assert.equal(receipt, "same-operation")
      return json({ action: "create", vmid: 241, status: lxcCreateStatus,
        phase: "create", task_warnings: false })
    }
  }
  if (url.origin === origin && url.pathname === "/api/vms/202/firewall/rules" && firewallEditor &&
      ["POST", "PUT", "PATCH", "DELETE"].includes(request.method)) {
    const payload = JSON.parse(request.postData)
    firewallWrites.push({ method: request.method, payload })
    const result = { vmid: 202, node: "fixture", type: "qemu" }
    if (request.method === "POST") {
      const { direction, action, protocol, dport, comment, log } = payload.rule
      fixtureFirewallRules = [{ pos: 0, type: direction.toLowerCase(), action, proto: protocol, dport,
        comment, log, enabled: payload.enabled }, ...fixtureFirewallRules.map(row => ({ ...row, pos: row.pos + 1 }))]
      return reply(201, JSON.stringify({ ...result, created: true }), "application/json")
    }
    if (request.method === "DELETE") {
      fixtureFirewallRules = fixtureFirewallRules.filter(row => row.pos !== payload.pos)
        .map((row, pos) => ({ ...row, pos }))
      return reply(200, JSON.stringify({ ...result, deleted: true }), "application/json")
    }
    if (request.method === "PATCH" && Object.hasOwn(payload, "to")) {
      assert.equal(payload.revision, fixtureRuleRevision)
      const [rule] = fixtureFirewallRules.splice(payload.pos, 1)
      fixtureFirewallRules.splice(payload.to, 0, rule)
      fixtureFirewallRules = fixtureFirewallRules.map((item, pos) => ({ ...item, pos }))
      fixtureRuleRevision = `fixture-revision-${firewallWrites.length}`
      await new Promise(resolve => setTimeout(resolve, 450))
      const rules_snapshot = legacyMoveResponse ? undefined : {
        rules: fixtureFirewallRules, add_rule_revision: fixtureRuleRevision,
        editable_rule_positions: [0], writable_rule_positions: fixtureFirewallRules.map(item => item.pos),
      }
      return reply(200, JSON.stringify({ ...result, moved: true, rules_snapshot }), "application/json")
    }
    if (request.method === "PATCH") fixtureFirewallRules[payload.pos].enabled = payload.enabled
    else Object.assign(fixtureFirewallRules[payload.pos], { comment: payload.rule.comment, log: payload.rule.log })
    return reply(200, JSON.stringify({ ...result, updated: true }), "application/json")
  }
  if (url.origin === origin && url.pathname === "/api/vms/100/firewall/settings" && firewallSettingsEditor) {
    const identity = { vmid: 100, node: "fixture", type: "lxc" }
    const json = data => reply(200, JSON.stringify({ ...identity, ...data }), "application/json")
    if (request.method === "GET") {
      firewallSettingsRequests.push(url.searchParams.get("network"))
      assert.equal(url.searchParams.get("type"), "lxc")
      assert.equal(url.searchParams.get("node"), identity.node)
      return json({ revision: "settings-revision", interfaces: [], bridges: ["vmbr0"],
        settings: { enabled: firewallSettingsEnabled, policy_in: "DROP", policy_out: "ACCEPT",
          log_level_in: "nolog", log_level_out: "nolog" } })
    }
    assert.equal(request.method, "PUT")
    const payload = JSON.parse(request.postData)
    firewallSettingsWrites.push(payload)
    firewallSettingsEnabled = payload.options.enabled ?? firewallSettingsEnabled
    if (payload.network) firewallAddedInterface = true
    return json({ saved: true, pending: payload.network ? ["net0"] : [], interface: payload.network ? "net0" : null })
  }
  if (request.method !== "GET") {
    rejectedWrites.push([request.method, url.pathname])
    return reply(403, "", "text/plain")
  }
  if (url.origin !== origin) return reply(404, "", "text/plain")
  const firewall = /^\/api\/vms\/(\d+)\/firewall\/(status|rules|log)$/.exec(url.pathname)
  if (firewall) {
    const [, vmid, section] = firewall
    const guest = guests.find(item => String(item.vmid) === vmid)
    assert.equal(url.searchParams.get("node"), guest.node)
    assert.equal(url.searchParams.get("type"), guest.type)
    firewallRequests.push({ vmid, section, method: request.method })
    const json = (status, data) => reply(status, JSON.stringify(data), "application/json")
    if (section === "log" && firewallLogReply !== 200) return json(firewallLogReply, { error: "firewall_read_failed" })
    if (section === "rules" && firewallRulesReply === 403) return json(403, { error: "permission_denied" })
    const lxc = guest.type === "lxc"
    const data = {
      status: { status: lxc ? "disabled" : "partial", cluster_enabled: true, guest_enabled: !lxc,
        backend: "iptables", service: "running", log_levels: { in: "nolog", out: "nolog" },
        interfaces: [{ name: "net0", flag: true, coverage: lxc ? "disabled" : "configured", pending: null },
                     { name: "net1", flag: false, coverage: "disabled", pending: "change", pending_flag: true }] },
      rules: { rules: lxc ? [] : fixtureFirewallRules,
        add_rule_revision: firewallEditor && vmid === "202" ? fixtureRuleRevision : null,
        editable_rule_positions: firewallEditor && vmid === "202" ? [0] : [],
        writable_rule_positions: firewallEditor && vmid === "202" ? fixtureFirewallRules.map(rule => rule.pos) : [] },
      log: { logs: firewallHasLogs ? Array.from({ length: 70 }, (_, index) =>
        ({ n: index + 1, t: `${vmid} ${index % 3 === 0 ? 4 : index % 3 === 1 ? 6 : 3} tap${vmid}i0-IN DROP firewall sample ${index + 1}` })) : [] },
    }[section]
    if (section === "status" && lxc && firewallSettingsEditor) Object.assign(data, {
      can_configure: true, guest_enabled: firewallSettingsEnabled,
      status: firewallSettingsEnabled ? "noInterfaces" : "disabled",
      interfaces: firewallAddedInterface ? [{name: "net0", flag: null, coverage: "absent", pending: "add", pending_flag: true}] : [],
    })
    return json(200, { vmid: guest.vmid, type: guest.type, node: guest.node, ...data })
  }
  const guestId = /^\/api\/vms\/(\d+)$/.exec(url.pathname)?.[1]
  const guest = guests.find(item => String(item.vmid) === guestId)
  const data = {
    "/api/auth/status": { auth_configured: true, auth_enabled: accessMode !== "open", authenticated: true,
      access_mode: accessMode, capabilities: { admin: isAdmin } },
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
  pending.clear()
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

const firewallDialog = "document.querySelector('[role=dialog]')"
const firewallText = value => `${firewallDialog}?.textContent.includes(${JSON.stringify(value)})`
const firewallPanel = `${firewallDialog}.querySelector('[role=tabpanel]:not([hidden])')`
async function guestDetailFrame() {
  return evaluate(`(() => {
    const dialog = ${firewallDialog};
    return [dialog, ...Array.from(dialog.children).slice(0, 4)].map(element => {
      const { x, y, width, height } = element.getBoundingClientRect();
      return { x, y, width, height };
    });
  })()`)
}

async function openGuestDetailTab(label) {
  const tab = `[...${firewallDialog}.children[1].querySelectorAll('button')].find(button =>
    button.querySelector('span')?.textContent.trim() === ${JSON.stringify(label)})`
  await click(tab)
  await waitFor(`!(${tab}).classList.contains('border-transparent')`)
  await waitFor(`${firewallDialog}.getAnimations().length === 0`)
}

async function firewallGeometry() {
  return evaluate(`(() => {
    const dialog = ${firewallDialog};
    const tabs = dialog.querySelector('[role=tablist]');
    const selected = tabs.querySelector('[aria-selected="true"]');
    const inactive = tabs.querySelector('[aria-selected="false"]');
    const tabRects = [...tabs.children].map(tab => tab.getBoundingClientRect());
    const body = dialog.children[2];
    const padding = getComputedStyle(body);
    const bodyWidth = body.clientWidth - parseFloat(padding.paddingLeft) - parseFloat(padding.paddingRight);
    return {
      fullWidth: Math.abs(tabs.getBoundingClientRect().width - bodyWidth) < 1,
      equalTabs: tabRects.every(rect => Math.abs(rect.width - tabRects[0].width) < 1 && rect.height === tabRects[0].height),
      tintedActive: getComputedStyle(selected).backgroundColor !== getComputedStyle(inactive).backgroundColor,
    };
  })()`)
}
async function openFirewallSection(label) {
  const tab = `[...${firewallDialog}.querySelectorAll('[role=tab]')].find(el=>el.textContent.trim()===${JSON.stringify(label)})`
  await waitFor(`Boolean(${tab})`)
  await evaluate(`(${tab}).dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true}))`)
}

async function verifyGuestFirewall() {
  const button = label => `[...${firewallDialog}.querySelectorAll('button')].find(el=>el.textContent.trim()===${JSON.stringify(label)})`
  await click(labelled("View details for demo-running-vm"))
  await waitFor(`Boolean(${labelled("Firewall")})`)
  assert.deepEqual(firewallRequests, [], "Firewall must be lazy")
  await waitFor(`${firewallDialog}.getAnimations().length === 0`)
  const vmFrame = await guestDetailFrame()
  await click(labelled("Firewall"))
  await waitFor(firewallText("Firewall on some interfaces"))
  await waitFor(firewallText("Pending change · firewall On"))
  await waitFor(`${firewallDialog}.getAnimations().length === 0`)
  assert.deepEqual(await guestDetailFrame(), vmFrame, "Opening Firewall must keep the entire VM detail frame")
  assert.ok(await evaluate(firewallText("Overview")))
  const geometry = await firewallGeometry()
  assert.ok(geometry.equalTabs && geometry.fullWidth && geometry.tintedActive)
  assert.ok(await evaluate(`(() => {
    const rects = [...(${firewallPanel}).querySelector('dl').children].map(card => card.getBoundingClientRect());
    return rects.every(rect => Math.abs(rect.width - rects[0].width) < 1 && rect.height === rects[0].height);
  })()`))
  assert.equal(await evaluate(firewallText("Firewall on the interface · Off")), false)
  assert.deepEqual(firewallRequests.map(call => call.section), ["status"])
  await openFirewallSection("Rules")
  await waitFor(firewallText("web-access"))
  assert.deepEqual(await firewallGeometry(), geometry)
  const rules = await evaluate(`[...${firewallDialog}.querySelectorAll('[role=tabpanel]:not([hidden]) ol li')].map(el=>el.textContent)`)
  assert.match(rules[0], /Incoming.*Allow.*443/)
  assert.match(rules[1], /Group.*web-access.*Disabled/)
  assert.match(rules[2], /Outgoing.*Drop/)
  assert.equal(await evaluate(`Boolean(${button("Add rule")})`), false)
  assert.deepEqual(firewallWrites, [])
  firewallEditor = true
  await click(button("Refresh"))
  await waitFor(`Boolean(${button("Add rule")})`)
  await click(button("Add rule"))
  await waitFor(firewallText("Proxmox adds an enabled rule"))
  assert.equal(await evaluate(`${button("Add rule")}.disabled`), true)
  await click(button("HTTPS"))
  const chooseRuleLogLevel = async level => {
    const trigger = labelled("Rule log level")
    await evaluate(`(${trigger}).dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true}))`)
    const option = `[...document.querySelectorAll('[role=option]')].find(item => item.textContent.trim() === ${JSON.stringify(level)})`
    await waitFor(`Boolean(${option})`)
    await click(option)
  }
  await chooseRuleLogLevel("info")
  await click(button("Add rule"))
  await waitFor(firewallText("The rule was added and enabled."))
  assert.equal(firewallWrites.length, 1)
  const { payload } = firewallWrites[0]
  assert.deepEqual({ ...payload, rule: { ...payload.rule, comment: "" } }, {
    node: "fixture", type: "qemu", revision: "fixture-revision", enabled: true,
    rule: { direction: "IN", action: "ACCEPT", protocol: "tcp", dport: "443", source: "", iface: "", comment: "", log: "info" },
  })
  const firstRule = `(${firewallPanel}).querySelector('ol li button[aria-expanded]')`
  await waitFor(`Boolean(${button("Add rule")})`)
  await click(firstRule)
  await waitFor(`Boolean(${button("Edit")})`)
  await click(button("Edit"))
  await waitFor(firewallText("The rule stays enabled."))
  const saveRule = button("Save changes")
  const comment = `[...(${firstRule}).closest('li').querySelectorAll('input')].at(-1)`
  const initialComment = await evaluate(`${comment}.value`)
  const changeComment = value => evaluate(`(() => {
    const input = [...(${firstRule}).closest('li').querySelectorAll('input')].at(-1);
    Object.getOwnPropertyDescriptor(Object.getPrototypeOf(input), 'value').set.call(input, ${JSON.stringify(value)});
    input.dispatchEvent(new Event('input', { bubbles: true }));
  })()`)
  assert.equal(await evaluate(`${saveRule}.disabled`), true)
  await changeComment("Updated HTTPS")
  await waitFor(`!${saveRule}.disabled`)
  await changeComment(` ${initialComment} `)
  await waitFor(`${saveRule}.disabled`)
  await click(saveRule)
  assert.equal(firewallWrites.length, 1, "Saving an unchanged rule must not send a write")
  await changeComment("Updated HTTPS")
  await waitFor(`!${saveRule}.disabled`)
  await chooseRuleLogLevel("warning")
  await click(saveRule)
  await waitFor(firewallText("Rule changes were saved."))
  await waitFor(firewallText("Updated HTTPS"))
  assert.equal(firewallWrites.length, 2)
  assert.equal(firewallWrites[1].method, "PUT")
  assert.equal(firewallWrites[1].payload.pos, 0)
  assert.equal(firewallWrites[1].payload.rule.dport, "443")
  assert.equal(firewallWrites[1].payload.rule.comment, "Updated HTTPS")
  assert.equal(firewallWrites[1].payload.rule.log, "warning")
  assert.equal("enabled" in firewallWrites[1].payload, false)
  const confirm = label => `[...Array.from(document.querySelectorAll('[role=dialog]')).at(-1).querySelectorAll('button')].find(el => el.textContent.trim() === ${JSON.stringify(label)})`
  const expectTemporaryNotice = async message => {
    const notice = firewallText(message)
    await waitFor(notice)
    const shownAt = Date.now()
    await waitFor(`!(${notice})`)
    const elapsed = Date.now() - shownAt
    assert.ok(elapsed >= 2000 && elapsed < 4000, `Expected a 2.5 second confirmation, got ${elapsed} ms: ${message}`)
  }
  await waitFor(`Boolean(${button("Disable")})`)
  await click(button("Disable"))
  await waitFor(`document.querySelectorAll('[role=dialog]').length === 2`)
  await click(confirm("Cancel"))
  await waitFor(`document.querySelectorAll('[role=dialog]').length === 1`)
  assert.equal(firewallWrites.length, 2)
  await click(button("Disable"))
  await waitFor(`document.querySelectorAll('[role=dialog]').length === 2`)
  await click(confirm("Disable"))
  await expectTemporaryNotice("The rule was disabled.")
  await waitFor(`Boolean(${button("Enable")})`)
  await click(button("Enable"))
  await waitFor(`document.querySelectorAll('[role=dialog]').length === 2`)
  await click(confirm("Enable"))
  await expectTemporaryNotice("The rule was enabled.")
  await waitFor(`Boolean(${button("Delete")})`)
  await click(button("Delete"))
  await waitFor(`document.querySelectorAll('[role=dialog]').length === 2`)
  await click(confirm("Delete"))
  await expectTemporaryNotice("The rule was deleted.")
  await waitFor(`!(${firewallText("Updated HTTPS")})`)
  assert.deepEqual(firewallWrites.slice(2).map(({ method, payload }) => [method, payload.pos, payload.enabled]),
    [["PATCH", 0, false], ["PATCH", 0, true], ["DELETE", 0, undefined]])
  fixtureFirewallRules = [
    { pos: 0, type: "in", action: "DROP", proto: "tcp", source: "0.0.0.0/0", enabled: true },
    { pos: 1, type: "in", action: "ACCEPT", proto: "tcp", dport: "22", enabled: true },
    { pos: 2, type: "in", action: "ACCEPT", proto: "icmp", enabled: true },
    { pos: 3, type: "in", action: "ACCEPT", proto: "tcp", dport: "443", enabled: true },
  ]
  await click(button("Refresh"))
  await waitFor(firewallText("0.0.0.0/0"))
  await send("Emulation.setDeviceMetricsOverride", { width: 320, height: 740, deviceScaleFactor: 1, mobile: false })
  await waitFor("innerWidth === 320")
  await click(firstRule)
  const moveMenu = labelled("Move")
  const option = label => `[...document.querySelectorAll('[role=menuitem]')].find(item => item.textContent.trim() === ${JSON.stringify(label)})`
  const openMoveMenu = async () => {
    await evaluate(`(${moveMenu}).focus()`)
    await send("Input.dispatchKeyEvent", { type: "keyDown", key: "Enter", code: "Enter", windowsVirtualKeyCode: 13 })
    await send("Input.dispatchKeyEvent", { type: "keyUp", key: "Enter", code: "Enter", windowsVirtualKeyCode: 13 })
  }
  const chooseMoveOption = async label => {
    const item = option(label)
    await waitFor(`Boolean(${item})`)
    await evaluate(`(${item}).focus()`)
    await send("Input.dispatchKeyEvent", { type: "keyDown", key: "Enter", code: "Enter", windowsVirtualKeyCode: 13 })
    await send("Input.dispatchKeyEvent", { type: "keyUp", key: "Enter", code: "Enter", windowsVirtualKeyCode: 13 })
  }
  assert.ok(await evaluate(`(() => {
    const bar = (${moveMenu}).parentElement;
    const items = [...bar.querySelectorAll('button')];
    return items.length === 4 && items.every(item => item.offsetTop === items[0].offsetTop &&
      getComputedStyle(item).whiteSpace === 'nowrap' && item.getBoundingClientRect().left >= bar.getBoundingClientRect().left &&
      item.getBoundingClientRect().right <= bar.getBoundingClientRect().right);
  })()`))
  await openMoveMenu()
  await waitFor(`Boolean(${option("Move to end")})`)
  assert.ok(await evaluate(`${option("Move to start")}.hasAttribute('data-disabled') &&
    ${option("Move up")}.hasAttribute('data-disabled') && !${option("Move down")}.hasAttribute('data-disabled')`))
  await chooseMoveOption("Move to end")
  await waitFor(`[...document.querySelectorAll('[role=dialog]')].some(dialog => dialog.textContent.includes('Move from position 1 to 4.'))`)
  assert.equal(firewallWrites.length, 5, "A pending move must not change rules")
  await click(confirm("Cancel"))
  await waitFor(`document.querySelectorAll('[role=dialog]').length === 1`)
  assert.equal(firewallWrites.length, 5)
  await openMoveMenu()
  await chooseMoveOption("Move to end")
  await waitFor(`Boolean(${confirm("Move rule")})`)
  const ruleReads = () => firewallRequests.filter(request => request.vmid === "202" && request.section === "rules").length
  const readsBeforeMove = ruleReads()
  await click(confirm("Move rule"))
  await waitFor(`${confirm("Moving rule…")}?.disabled === true`)
  await waitFor(firewallText("Firewall rule was moved."))
  assert.equal(ruleReads(), readsBeforeMove, "Verified move must render from PATCH without another GET")
  assert.deepEqual(firewallWrites[5], { method: "PATCH", payload: {
    node: "fixture", type: "qemu", revision: "fixture-revision", pos: 0, to: 3,
  } })
  await send("Emulation.setDeviceMetricsOverride", { width: 1440, height: 960, deviceScaleFactor: 1, mobile: false })
  await waitFor("innerWidth === 1440")
  const lastGrip = labelled("Drag rule 4 or open move actions")
  await waitFor(`Boolean(${lastGrip})`)
  await click(lastGrip)
  await openMoveMenu()
  await waitFor(`Boolean(${option("Move to start")})`)
  assert.ok(await evaluate(`!${option("Move to start")}.hasAttribute('data-disabled') &&
    ${option("Move to end")}.hasAttribute('data-disabled')`))
  await chooseMoveOption("Move to start")
  await waitFor(`[...document.querySelectorAll('[role=dialog]')].some(dialog => dialog.textContent.includes('Move from position 4 to 1.'))`)
  await click(confirm("Cancel"))
  await waitFor(`document.querySelectorAll('[role=dialog]').length === 1`)
  await evaluate(`(() => {
    const grip = ${lastGrip};
    const target = (${firstRule}).parentElement;
    const dataTransfer = new DataTransfer();
    const clientY = target.getBoundingClientRect().top + 1;
    grip.dispatchEvent(new DragEvent("dragstart", { bubbles: true, dataTransfer }));
    target.dispatchEvent(new DragEvent("dragover", { bubbles: true, dataTransfer, clientY }));
    target.dispatchEvent(new DragEvent("drop", { bubbles: true, dataTransfer, clientY }));
    grip.dispatchEvent(new DragEvent("dragend", { bubbles: true, dataTransfer }));
  })()`)
  await waitFor(`Boolean(${confirm("Move rule")})`)
  assert.equal(firewallWrites.length, 6, "Dragging must open confirmation before writing")
  legacyMoveResponse = true
  await click(confirm("Move rule"))
  await waitFor(firewallText("Firewall rule was moved."))
  assert.deepEqual(firewallWrites[6], { method: "PATCH", payload: {
    node: "fixture", type: "qemu", revision: "fixture-revision-6", pos: 3, to: 0,
  } })
  await waitFor(`Boolean(${lastGrip}) && (${firstRule}).textContent.includes('0.0.0.0/0')`)
  assert.equal(ruleReads(), readsBeforeMove + 1, "Legacy move response must refresh once")
  console.log("Guest firewall rules: move with verified response and no extra GET, cancel, drag and legacy refresh")
  firewallEditor = false
  firewallRulesReply = 403
  await click(button("Refresh"))
  await waitFor(firewallText("You do not have permission"))
  assert.equal(await evaluate(firewallText("0.0.0.0/0")), false)
  firewallRulesReply = 200
  await openFirewallSection("Logs")
  await waitFor(firewallText("No firewall events recorded yet."))
  await waitFor(firewallText("Default policies do not log."))
  assert.deepEqual(await firewallGeometry(), geometry)
  assert.equal(await evaluate(firewallText("Proxmox matches records by VMID.")), false)
  firewallLogReply = 502
  await click(button("Refresh"))
  await waitFor(firewallText("Could not read firewall data from Proxmox."))
  await waitFor(firewallText("Showing the last successful reading."))
  firewallLogReply = 200
  firewallHasLogs = true
  await click(button("Refresh"))
  await waitFor(firewallText("DROP firewall sample 70"))
  assert.ok(await evaluate(firewallText("Proxmox matches records by VMID.")))
  const levelFilter = `[...document.querySelectorAll('button[aria-haspopup=menu]')].find(item => item.textContent.startsWith('Filter by log level'))`
  const logLevelOption = label => `[...document.querySelectorAll('[role=menuitemcheckbox]')].find(item => item.textContent.trim() === ${JSON.stringify(label)})`
  const logRow = number => `[...(${firewallPanel}).querySelectorAll('pre span')].some(item => item.textContent.trim().endsWith('sample ' + ${number}))`
  await evaluate(`(${levelFilter}).dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true}))`)
  await waitFor(`Boolean(${logLevelOption("warning")})`)
  await click(logLevelOption("warning"))
  await waitFor(`${logRow(1)} && !${logRow(2)} && !${logRow(3)}`)
  await click(logLevelOption("info"))
  await waitFor(`${logRow(1)} && ${logRow(2)} && !${logRow(3)}`)
  await click(logLevelOption("warning"))
  await click(logLevelOption("info"))
  await click(logLevelOption("debug"))
  await waitFor(firewallText("No records match the selected levels."))
  const allLevels = `[...document.querySelectorAll('[role=menuitem]')].find(item => item.textContent.trim() === 'All levels')`
  await click(allLevels)
  await waitFor(`${logRow(1)} && ${logRow(2)} && ${logRow(3)}`)
  assert.ok(await evaluate(`(() => {
    const panel = ${firewallPanel};
    const list = panel.querySelector('pre');
    const scroll = panel.parentElement;
    const tabTop = ${firewallDialog}.querySelector('[role=tablist]').getBoundingClientRect().top;
    scroll.scrollTop = scroll.scrollHeight;
    return scroll.scrollTop > 0 && list.scrollHeight === list.clientHeight
      && ${firewallDialog}.querySelector('[role=tablist]').getBoundingClientRect().top === tabTop;
  })()`))
  await openFirewallSection("Overview")
  await waitFor(firewallText("Firewall on some interfaces"))
  assert.equal(await evaluate(`(${firewallPanel}).parentElement.scrollTop`), 0)
  firewallHasLogs = false
  await openGuestDetailTab("Backups")
  assert.deepEqual(await guestDetailFrame(), vmFrame)
  await send("Input.dispatchKeyEvent", { type: "rawKeyDown", key: "Escape", code: "Escape", windowsVirtualKeyCode: 27 })
  await waitFor(`!${firewallDialog}`)

  await send("Emulation.setDeviceMetricsOverride", { width: 1692, height: 1420, deviceScaleFactor: 1, mobile: false })
  await waitFor("innerWidth === 1692 && innerHeight === 1420")
  await click(labelled("View details for demo-container-with-a-long-name"))
  await waitFor(`Boolean(${labelled("Firewall")})`)
  await waitFor(`${firewallDialog}.getAnimations().length === 0`)
  const lxcFrame = await guestDetailFrame()
  for (const tab of ["App", "Updates", "Backups", "Firewall", "Status"]) {
    await openGuestDetailTab(tab)
    assert.deepEqual(await guestDetailFrame(), lxcFrame, `LXC detail frame changed on ${tab}`)
  }
  await send("Input.dispatchKeyEvent", { type: "rawKeyDown", key: "Escape", code: "Escape", windowsVirtualKeyCode: 27 })
  await waitFor(`!${firewallDialog}`)
  await send("Emulation.setDeviceMetricsOverride", { width: 1440, height: 960, deviceScaleFactor: 1, mobile: false })
  console.log("Guest detail: stable dialog, header, main tabs, content and footer across VM and LXC sections")
}

async function verifyGuestFirewallSettings() {
  firewallSettingsEditor = true
  const settings = "[...document.querySelectorAll('[role=dialog]')].at(-1)"
  const title = label => `${settings}?.querySelector('h2')?.textContent === ${JSON.stringify(label)}`
  const button = (label, dialog = firewallDialog) =>
    `[...${dialog}.querySelectorAll('button')].find(el => el.textContent.trim() === ${JSON.stringify(label)})`
  const switches = `${settings}.querySelectorAll('[role=switch]')`
  const switchStates = `[...${switches}].map(control => [control.getAttribute('aria-checked'), control.previousElementSibling.textContent.trim()])`
  await click(labelled("View details for demo-container-with-a-long-name"))
  await click(labelled("Firewall"))
  await waitFor(firewallText("No network interfaces are configured."))
  assert.deepEqual(firewallSettingsRequests, [])
  await click(button("Configure firewall"))
  await waitFor(title("Configure firewall"))
  await waitFor(`Boolean(${settings}?.querySelector('[role=switch]'))`)
  assert.equal(await evaluate(`${button("Save", settings)}.disabled`), true)
  await click(`${settings}.querySelector('[role=switch]')`)
  assert.deepEqual(await evaluate(switchStates), [["true", "On"]])
  await click(button("Add network interface", settings))
  await waitFor(title("Add network interface"))
  await waitFor(`Boolean(${labelled("Network bridge")})`)
  assert.deepEqual(await evaluate(switchStates), [["true", "On"], ["false", "Off"]])
  assert.deepEqual(await evaluate(`[...${switches}].map(control => getComputedStyle(control).backgroundColor)`), wizardSwitchColors)
  assert.ok(await evaluate(`(() => {
    const bridge = ${labelled("Network bridge")}.getBoundingClientRect();
    const vlan = ${settings}.querySelector('input[inputmode=numeric]').getBoundingClientRect();
    return Math.abs(bridge.top - vlan.top) < 1 && Math.abs(bridge.height - vlan.height) < 1;
  })()`))
  await click(`${switches}[1]`)
  await waitFor(`${switches}[1]?.getAttribute('aria-checked') === "true"`)
  assert.deepEqual(await evaluate(switchStates), [["true", "On"], ["true", "On"]])
  await click(button("Cancel", settings))
  await waitFor(title("Configure firewall"))
  assert.deepEqual(await evaluate(switchStates), [["true", "On"]])
  assert.deepEqual(firewallSettingsWrites, [], "Opening and cancelling the NIC form must not save either draft")
  assert.ok(await evaluate(`${button("Save", settings)}.classList.contains("border-green-500/30")`))
  await click(button("Save", settings))
  await waitFor(firewallText("Firewall settings saved."))
  const shownAt = Date.now()
  const missing = "This guest has no active network interface"
  await waitFor(firewallText(missing))
  assert.deepEqual(firewallSettingsWrites[0], { node: "fixture", type: "lxc", revision: "settings-revision",
    options: { enabled: true }, interfaces: {} })
  await waitFor(`!(${firewallText("Firewall settings saved.")})`)
  assert.ok(Date.now() - shownAt < 4000, "Settings confirmation should clear after 2.5 seconds")
  await openFirewallSection("Rules")
  await waitFor(firewallText(missing))
  await openFirewallSection("Logs")
  await waitFor(firewallText("No firewall events recorded yet."))
  await waitFor(firewallText(missing))
  assert.equal(await evaluate(firewallText("Default policies do not log.")), false)
  await openFirewallSection("Overview")

  await send("Emulation.setDeviceMetricsOverride", { width: 320, height: 740, deviceScaleFactor: 1, mobile: false })
  await waitFor("innerWidth === 320")
  await click(button("Add network interface"))
  await waitFor(title("Add network interface"))
  await waitFor(`Boolean(${labelled("Network bridge")})`)
  await waitFor(`${settings}.getAnimations().length === 0`)
  assert.ok(await evaluate(`(() => {
    const dialog = ${settings};
    const box = dialog.getBoundingClientRect();
    return box.left >= 0 && box.right <= innerWidth && dialog.scrollWidth <= dialog.clientWidth + 1;
  })()`))
  assert.equal(await evaluate(`${button("Add network interface", settings)}.disabled`), true)
  assert.ok(await evaluate(`${button("Add network interface", settings)}.classList.contains("bg-muted")`))
  await evaluate(`(${labelled("Network bridge")}).dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true}))`)
  const bridgeOption = "[...document.querySelectorAll('[role=option]')].find(el=>el.textContent==='vmbr0')"
  await waitFor(`Boolean(${bridgeOption})`)
  await click(bridgeOption)
  await waitFor(`!${button("Add network interface", settings)}.disabled`)
  assert.ok(await evaluate(`${button("Add network interface", settings)}.classList.contains("bg-orange-600")`))
  await click(button("Add network interface", settings))
  await waitFor(firewallText("Changes to net0 are pending."))
  await waitFor(firewallText("Pending addition · firewall On"))
  assert.deepEqual(firewallSettingsWrites[1], { node: "fixture", type: "lxc", revision: "settings-revision", options: {},
    network: { bridge: "vmbr0", vlan: null, firewall: true, mode: "dhcp", ip: "", gateway: "" } })
  assert.deepEqual(firewallSettingsRequests, [null, "1", "1"])
  await send("Input.dispatchKeyEvent", { type: "rawKeyDown", key: "Escape", code: "Escape", windowsVirtualKeyCode: 27 })
  await waitFor(`!${firewallDialog}`)
  await send("Emulation.setDeviceMetricsOverride", { width: 1440, height: 960, deviceScaleFactor: 1, mobile: false })
  firewallSettingsEditor = false
  console.log("Guest firewall settings: transient save confirmation, direct NIC form, draft preserved on cancel, visible switch states, DHCP and pending NIC")
}

async function verifyPlainLxcWizard() {
  const button = (label, scope = "document") =>
    `[...${scope}.querySelectorAll('button')].find(el => el.textContent.trim() === ${JSON.stringify(label)})`
  const dialog = "document.querySelector('[role=dialog]')"
  const control = (label, selector) =>
    `[...${dialog}.querySelectorAll('label')].find(el => el.firstElementChild?.textContent === ${JSON.stringify(label)})?.querySelector('${selector}')`
  async function fill(label, selector, value) {
    await evaluate(`(() => {
      const input = ${control(label, selector)};
      Object.getOwnPropertyDescriptor(Object.getPrototypeOf(input), 'value').set.call(input, ${JSON.stringify(value)});
      input.dispatchEvent(new Event(input.tagName === 'SELECT' ? 'change' : 'input', {bubbles:true}));
    })()`)
  }
  async function advance(label) {
    const next = button(label, dialog)
    await waitFor(`Boolean(${next})`)
    await click(next)
  }
  async function assertDialogFits() {
    assert.ok(await evaluate(`(() => {
      const panel = ${dialog}; const bounds = panel.getBoundingClientRect();
      return bounds.left >= 0 && bounds.right <= innerWidth && panel.scrollWidth <= panel.clientWidth + 1;
    })()`))
  }
  for (const submit of [false, true]) {
    if (submit) {
      await send("Emulation.setDeviceMetricsOverride", { width: 390, height: 812, deviceScaleFactor: 1, mobile: true })
      await waitFor("innerWidth === 390")
    }
    await click(button("Create LXC"))
    await waitFor(`Boolean(${dialog} && ${control("System template", "select")})`)
    await assertDialogFits()
    if (!submit) {
      wizardSwitchColors = await evaluate(`["true", "false"].map(state =>
        getComputedStyle(${dialog}.querySelector('[role=switch][aria-checked=' + state + ']')).backgroundColor)`)
      assert.notEqual(...wizardSwitchColors)
    }
    if (submit) {
      await fill("Container hostname", "input", "chosen-name")
      await advance("Download an official template")
      await waitFor(`Boolean(${button(catalogTemplate, dialog)})`)
      await click(button(catalogTemplate, dialog))
      await waitFor(`!(${button("Confirm download", dialog)}).disabled`)
      await assertDialogFits()
      await evaluate(`(() => { const download = ${button("Confirm download", dialog)}; download.click(); download.click(); })()`)
      // A finished download returns to System with that template chosen.
      await waitFor(`${control("System template", "select")}?.value === ${JSON.stringify(downloadedTemplate)}`)
      assert.equal(await evaluate(`${control("Container hostname", "input")}.value`), "chosen-name")
    } else {
      await advance("Download an official template")
      await waitFor(`Boolean(${button(catalogTemplate, dialog)})`)
      await click(button(catalogTemplate, dialog))
      await advance("Download an official template")
      assert.equal(lxcRequests.filter(call => call.action.startsWith("download")).length, 0)
      await fill("System template", "select", lxcTemplate)
    }
    await advance("Next")
    await fill("Root password", "input", "fixture-root-password")
    await fill("Confirm root password", "input", "fixture-root-password")
    await advance("Next")
    await advance("Next")
    await fill("Network bridge", "select", "")
    await advance("Next")
    // Review checks the plan on its own; its warnings are notices that the
    // confirmation accepts.
    const confirm = button("Confirm creation", dialog)
    await waitFor(`Boolean(${confirm})`)
    assert.ok(await evaluate(`${dialog}.textContent.includes('The container will have no network interface.')`))
    assert.equal(await evaluate(`(${confirm}).disabled`), false)
    if (!submit) {
      await advance("Cancel")
      await waitFor(`!${dialog}`)
      assert.equal(lxcRequests.filter(call => call.action === "create").length, 0)
      continue
    }
    await evaluate(`(() => { const confirm = ${confirm}; confirm.click(); confirm.click(); })()`)
    // The view follows each native task: the request reached Proxmox and the
    // container is being created.
    await waitFor(`${dialog}?.textContent.includes('Create the container') && !${dialog}.textContent.includes('Confirm creation')`)
    assert.ok(await evaluate(`${dialog}.textContent.includes('LXC 241 · chosen-name')`))
  }
  await advance("Close")
  await waitFor(`!${dialog}`)
  await send("Page.reload")
  await openInventory()
  await click(button("Create LXC"))
  await waitFor(`${dialog}?.textContent.includes('LXC 241') && ${dialog}.textContent.includes('Create the container')`)
  assert.equal(lxcRequests.filter(call => call.action === "create").length, 1)
  lxcCreateStatus = "succeeded"
  await waitFor(`${dialog}?.textContent.includes('Container created.')`)
  const receiptKey = "proxmenux.plainLxc.operation.v1"
  const successfulReceipt = await evaluate(`sessionStorage.getItem(${JSON.stringify(receiptKey)})`)
  assert.ok(successfulReceipt, "Keep an unacknowledged success recoverable")
  await advance("Close")
  await waitFor(`!${dialog}`)
  async function assertFreshWizard() {
    const statusChecks = lxcRequests.filter(call => call.action === "status").length
    await click(button("Create LXC"))
    await waitFor(`Boolean(${dialog} && ${control("System template", "select")})`)
    assert.equal(await evaluate(`${control("Container ID (VMID)", "input")}.value`), "242")
    // The hidden native select of the Monitor's Select shows its first option;
    // what the user sees is the trigger, still asking for a template.
    assert.equal(await evaluate(`${control("System template", "[role=combobox]")}.textContent`), "Select a template")
    assert.equal(await evaluate(`${control("Container hostname", "input")}.value`), "")
    assert.equal(lxcRequests.filter(call => call.action === "status").length, statusChecks)
    await advance("Cancel")
    await waitFor(`!${dialog}`)
  }
  await assertFreshWizard()
  // Revisit the same completed receipt to exercise the other dialog dismissal path.
  await evaluate(`sessionStorage.setItem(${JSON.stringify(receiptKey)}, ${JSON.stringify(successfulReceipt)})`)
  await click(button("Create LXC"))
  await waitFor(`${dialog}?.textContent.includes('Container created.')`)
  await send("Input.dispatchKeyEvent", { type: "keyDown", key: "Escape", code: "Escape", windowsVirtualKeyCode: 27 })
  await send("Input.dispatchKeyEvent", { type: "keyUp", key: "Escape", code: "Escape", windowsVirtualKeyCode: 27 })
  await waitFor(`!${dialog}`)
  await assertFreshWizard()
  const plans = lxcRequests.filter(call => call.action === "plan")
  assert.equal(plans.length, 2)
  assert.equal(plans[1].body.spec.template.volume_id, downloadedTemplate)
  assert.ok(plans.every(call => call.body.spec.network === null && !JSON.stringify(call).includes("fixture-root-password")))
  assert.deepEqual(lxcRequests.filter(call => call.action === "create").map(call => call.body), [{
    check: "checked-plan", confirmed: true, accepted_warnings: ["no_network"], password: "fixture-root-password",
  }])
  assert.deepEqual(lxcRequests.filter(call => call.action === "download/plan").map(call => call.body), [{
    node: "fixture", catalog_id: catalogTemplate, template_storage: "local",
  }])
  assert.deepEqual(lxcRequests.filter(call => call.action === "download").map(call => call.body), [{
    check: "checked-download", confirmed: true,
  }])
  assert.ok(lxcRequests.filter(call => call.action === "status" && call.method === "GET").length >= 2)
  accessMode = "open"
  await send("Page.reload")
  await openInventory()
  assert.equal(await evaluate(`Boolean(${button("Create LXC")})`), true)
  accessMode = "proxmox"
  await send("Page.reload")
  await openInventory()
  assert.equal(await evaluate(`Boolean(${button("Create LXC")})`), true)
  isAdmin = false
  await send("Page.reload")
  await openInventory()
  assert.equal(await evaluate(`Boolean(${button("Create LXC")})`), false)
  accessMode = "read_only"
  await send("Page.reload")
  await openInventory()
  assert.equal(await evaluate(`Boolean(${button("Create LXC")})`), false)
  isAdmin = true
  accessMode = "password"
  await send("Emulation.setDeviceMetricsOverride", { width: 1440, height: 960, deviceScaleFactor: 1, mobile: false })
  await send("Page.reload")
  await openInventory()
  console.log("Plain LXC wizard: desktop, mobile, admin gating, downloads, duplicate clicks, recovery while running, and a fresh form after closing success")
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
  await verifyPlainLxcWizard()
  await verifyGuestFirewall()
  await verifyGuestFirewallSettings()
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
  await waitFor(`${firewallDialog}.getAnimations().length === 0`)
  const phoneFrame = await guestDetailFrame()
  await click(labelled("Firewall"))
  await waitFor(firewallText("Firewall pre tento stroj je vypnutý"))
  await waitFor(`${firewallDialog}.getAnimations().length === 0`)
  assert.deepEqual(await guestDetailFrame(), phoneFrame, "Firewall must keep the mobile detail frame")
  assert.ok(await evaluate(firewallText("Firewall na rozhraní · Zapnutý")))
  const firewallPhone = await firewallGeometry()
  assert.ok(firewallPhone.equalTabs && firewallPhone.fullWidth && firewallPhone.tintedActive)
  assert.equal(await evaluate(firewallText("web-access")), false)
  await openFirewallSection("Pravidlá")
  await waitFor(firewallText("Tento stroj nemá vlastné pravidlá firewallu."))
  assert.deepEqual(await firewallGeometry(), firewallPhone)
  await openFirewallSection("Záznamy")
  await waitFor(firewallText("Firewall je vypnutý, nové záznamy nepribúdajú."))
  assert.deepEqual(await firewallGeometry(), firewallPhone)
  assert.ok(await evaluate(`(() => {
    const dialog = ${firewallDialog};
    const panel = dialog.querySelector('[role=tabpanel]:not([hidden])');
    const bounds = panel.getBoundingClientRect();
    return bounds.left >= 0 && bounds.right <= innerWidth && panel.scrollWidth <= panel.clientWidth + 1;
  })()`))
  assert.ok(firewallRequests.every(call => call.method === "GET"))
  assert.deepEqual([...new Set(firewallRequests.map(call => call.vmid))].sort(), ["100", "202"])
  await openGuestDetailTab("Stav")
  assert.deepEqual(await guestDetailFrame(), phoneFrame)
  console.log("Firewall: VM status, rule order, ACL refusal, mocked active add and inline edit, empty logs and Slovak LXC log view")
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
async function cleanup() {
  clearTimeout(deadline)
  const forceClose = setTimeout(() => browser.kill("SIGKILL"), 5000)
  try {
    if (browser.exitCode === null && browser.signalCode === null) {
      // Let Chromium finish writing the profile before removing it.
      void send("Browser.close", {}, null).catch(() => browser.kill())
    }
    await browserClosed
    // Helper processes can outlive the browser for a moment; a temporary
    // profile left behind does not fail the check.
    await fs.promises.rm(profile, { recursive: true, force: true, maxRetries: 5, retryDelay: 100 }).catch(() => {})
  } finally {
    clearTimeout(forceClose)
  }
}

run()
  .catch(error => { console.error(error); process.exitCode = 1 })
  .finally(cleanup)
  .catch(error => { console.error(error); process.exitCode = 1 })
