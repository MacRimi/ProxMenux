// Offline source contract, not a pixel/layout test. Real-browser acceptance must
// separately measure the shipped SVG labels across widths, locales and themes.
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const { test } = require('node:test')
const app = path.resolve(__dirname, '../AppImage')
const ts = require(require.resolve('typescript', { paths: [app] }))

function descendants(node, predicate) {
  const found = []
  function visit(child) {
    if (predicate(child)) found.push(child)
    ts.forEachChild(child, visit)
  }
  visit(node)
  return found
}

function attribute(opening, name) {
  assert.ok(opening.attributes.properties.every(ts.isJsxAttribute), 'explicit JSX props required')
  const matches = opening.attributes.properties.filter(prop => prop.name.text === name)
  assert.ok(matches.length <= 1, `duplicate ${name} prop`)
  const value = matches[0]?.initializer
  return value && ts.isJsxExpression(value) ? value.expression : value
}

function property(object, name) {
  assert.ok(object && ts.isObjectLiteralExpression(object), 'explicit object required')
  assert.ok(object.properties.every(ts.isPropertyAssignment), 'explicit object properties required')
  const matches = object.properties.filter(prop => prop.name.text === name)
  assert.ok(matches.length <= 1, `duplicate ${name} property`)
  return matches[0]?.initializer
}

// Compare expression meaning at this small seam, ignoring whitespace/comments.
// Unsupported syntax fails closed instead of silently accepting a missing label.
function expression(node) {
  assert.ok(node, 'label expression must remain present')
  if (ts.isParenthesizedExpression(node)) return expression(node.expression)
  if (ts.isStringLiteral(node)) return node.text
  if (ts.isNumericLiteral(node)) return Number(node.text)
  if (ts.isIdentifier(node)) return { identifier: node.text }
  if (ts.isPrefixUnaryExpression(node) && node.operator === ts.SyntaxKind.MinusToken) {
    return -expression(node.operand)
  }
  if (ts.isCallExpression(node)) return { call: expression(node.expression), args: node.arguments.map(expression) }
  if (ts.isBinaryExpression(node)) {
    return { operator: ts.tokenToString(node.operatorToken.kind), left: expression(node.left), right: expression(node.right) }
  }
  if (ts.isConditionalExpression(node)) {
    return { condition: expression(node.condition), yes: expression(node.whenTrue), no: expression(node.whenFalse) }
  }
  if (ts.isObjectLiteralExpression(node)) {
    assert.ok(node.properties.every(ts.isPropertyAssignment), 'explicit label properties required')
    const names = node.properties.map(prop => prop.name.text)
    assert.equal(new Set(names).size, names.length, 'unique label properties required')
    return Object.fromEntries(node.properties.map(prop => [prop.name.text, expression(prop.initializer)]))
  }
  assert.fail(`unsupported contract expression: ${ts.SyntaxKind[node.kind]}`)
}

function charts(file, component, expectedCount) {
  const source = ts.createSourceFile(file, fs.readFileSync(path.join(app, 'components', file), 'utf8'), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
  assert.equal(source.parseDiagnostics.length, 0, `${file} must parse`)
  const imports = source.statements.filter(node => ts.isImportDeclaration(node) && node.moduleSpecifier.text === 'recharts')
  const bindings = imports.flatMap(node => node.importClause?.namedBindings?.elements || [])
  const localName = name => {
    const binding = bindings.find(node => (node.propertyName || node.name).text === name)
    assert.ok(binding, `${name} must come from recharts`)
    return binding.name.text
  }
  const [areaChartName, areaName, yAxisName] = ['AreaChart', 'Area', 'YAxis'].map(localName)
  const functions = source.statements.filter(node => ts.isFunctionDeclaration(node) && node.name?.text === component)
  assert.equal(functions.length, 1, `${component} must remain present`)
  assert.ok(functions[0].modifiers?.some(node => node.kind === ts.SyntaxKind.ExportKeyword), `${component} must remain exported`)
  const result = descendants(functions[0].body, node => ts.isJsxElement(node) && node.openingElement.tagName.getText(source) === areaChartName)
  assert.equal(result.length, expectedCount, `${component}: check every shipped AreaChart`)
  return result.map(chart => ({
    margin: attribute(chart.openingElement, 'margin'),
    keys: chart.children.filter(ts.isJsxSelfClosingElement).filter(node => node.tagName.getText(source) === areaName).map(node => expression(attribute(node, 'dataKey'))),
    axes: chart.children.filter(ts.isJsxSelfClosingElement).filter(node => node.tagName.getText(source) === yAxisName),
  }))
}

const nodeCharts = charts('node-metrics-charts.tsx', 'NodeMetricsCharts', 2)
const networkCharts = charts('network-traffic-chart.tsx', 'NetworkTrafficChart', 1)
function chartFor(charts, key, axisCount) {
  const matches = charts.filter(chart => chart.keys.includes(key))
  assert.equal(matches.length, 1, `one actual ${key} chart required`)
  assert.equal(matches[0].axes.length, axisCount, `${key}: labeled axes must remain`)
  return matches[0]
}
const cpu = chartFor(nodeCharts, 'cpu', 2)
const memory = chartFor(nodeCharts, 'memoryTotal', 1)
const network = chartFor(networkCharts, 'netIn', 1)
const identifier = name => ({ identifier: name })
const desktopLabel = (value, side) => ({ value, angle: side === 'left' ? -90 : 90, position: side === 'left' ? 'insideLeft' : 'insideRight', fill: 'currentColor' })
const mobileRule = label => ({ condition: identifier('isMobile'), yes: identifier('undefined'), no: label })
const contracts = [
  ['CPU %', cpu, 'left', mobileRule(desktopLabel('CPU %', 'left'))],
  ['CPU Load', cpu, 'right', mobileRule(desktopLabel({ call: identifier('t'), args: ['overview.loadAxis'] }, 'right'))],
  ['Memory GB', memory, 'left', mobileRule(desktopLabel('GB', 'left'))],
  ['Network GB/Gb', network, 'left', desktopLabel({ condition: { operator: '===', left: identifier('networkUnit'), right: 'Bits' }, yes: 'Gb', no: 'GB' }, 'left')],
]
for (const [name, chart, side, label] of contracts) {
  test(`${name}: label retained with >=8px internal ${side} gutter (source contract)`, () => {
    const axes = chart.axes.filter(axis => {
      const orientation = attribute(axis, 'orientation')
      return (orientation ? expression(orientation) : 'left') === side
    })
    assert.equal(axes.length, 1, `${name}: one ${side} YAxis required`)
    assert.deepEqual(expression(attribute(axes[0], 'label')), label, `${name}: preserve label, unit and mobile rule`)
    const gutterNode = property(chart.margin, side)
    const gutter = gutterNode ? expression(gutterNode) : 0
    assert.ok(typeof gutter === 'number' && gutter >= 8, `${name}: ${side} AreaChart margin must be >=8px; got ${JSON.stringify(gutter)}`)
  })
}
