const assert = require("assert")
const fs = require("fs")
const path = require("path")
const ts = require("../../node_modules/typescript")

const sourcePath = path.join(__dirname, "../../lib/vm-search.ts")
const source = fs.readFileSync(sourcePath, "utf8")
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2017 },
}).outputText
const moduleShim = { exports: {} }
new Function("exports", "require", "module", "__filename", "__dirname", compiled)(
  moduleShim.exports,
  require,
  moduleShim,
  sourcePath,
  path.dirname(sourcePath),
)

const { matchesVmSearch, normalizeVmSearchValue } = moduleShim.exports
const synonyms = { lxc: "container", qemu: "virtual machine" }

const multiIpLxc = {
  vmid: 301,
  name: "database",
  type: "lxc",
  ip: "10.100.100.219",
  ips: ["10.100.100.219", "10.100.100.220"],
}

assert.equal(
  matchesVmSearch(multiIpLxc, [normalizeVmSearchValue("10.100.100.220")], synonyms),
  true,
  "A secondary LXC IP must be searchable",
)
assert.equal(
  matchesVmSearch(multiIpLxc, [normalizeVmSearchValue("10.100.100.218")], synonyms),
  false,
  "Unrelated IPs must not match",
)

console.log("VM IP search tests passed")
