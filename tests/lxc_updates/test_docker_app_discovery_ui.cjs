// Real panel interactions with inert API fixtures; no guest or registration.
const assert = require('node:assert/strict')
const {fixture, text} = require('./test_native_app_discovery_ui.cjs')
const candidate = {
  vmid:101,slug:'docker-'+'b'.repeat(24),discovery_id:'docker-'+'b'.repeat(24),
  source:'docker_metadata',name:'Uncatalogued web app',default_ports:[8080],
  installed_version:null,tracking_suggestion:null,
  evidence:[{kind:'docker_container',value:'web-1'},{kind:'docker_image',value:'example/web:7'}],
}
async function main() {
  const f = fixture({nativeCandidate:null,dockerCandidate:candidate})
  f.render(); await f.settle()
  assert.equal(f.calls.filter(c=>c.method==='POST').length,0)
  await f.button('searchApplications').props.onClick(); f.render()
  assert.equal(f.calls.filter(c=>c.url.endsWith('/docker-discovery')&&c.method==='POST').length,1)
  assert.ok(text(f.tree()).includes('example/web:7'))
  assert.ok(text(f.tree()).includes('dockerEndpointReview'))
  assert.ok(text(f.tree()).includes('nativeVersionUnknown'))
  await f.button('registerButton').props.onClick(); f.render()
  f.button('cancelButton').props.onClick(); f.render()
  assert.equal(f.calls.filter(c=>/\/apps$/.test(c.url)&&c.method==='POST').length,0)
  await f.button('registerButton').props.onClick(); f.render()
  await f.button('saveButton').props.onClick(); f.render()
  const saved=JSON.parse(f.calls.find(c=>/\/apps$/.test(c.url)&&c.method==='POST').body)
  assert.equal(saved.discovery_id,candidate.discovery_id)
  assert.equal(saved.update_method,'none')
  assert.ok(!saved.repo && !saved.helper_slug && !saved.update_command)
  for (const status of ['error','partial','busy']) {
    const failed=fixture({nativeCandidate:null,dockerCandidate:candidate})
    failed.render(); await failed.settle(); failed.setDockerStatus(status)
    await failed.button('searchApplications').props.onClick(); failed.render()
    assert.ok(text(failed.tree()).includes(status==='partial'?'dockerScanPartial':'dockerScanFailed'))
    assert.ok(!text(failed.tree()).includes('noApplicationsDetected'))
  }
  const changed=fixture({nativeCandidate:null,dockerCandidate:candidate})
  changed.render(); await changed.settle(); changed.holdDocker()
  const pending=changed.button('searchApplications').props.onClick()
  await changed.settle(); changed.render({vmid:102,initialData:{sidecar:{apps:[]},suggestions:{extras:[],port_suggestions:[]}}})
  changed.resolveDocker(); await pending; changed.render()
  assert.ok(!text(changed.tree()).includes(candidate.name),'late Docker result never crosses CT')
  const oci=fixture({nativeCandidate:null,dockerCandidate:candidate})
  oci.render({vmid:101,oci:{instance:true},initialData:{sidecar:{apps:[]},suggestions:{oci_instance:{template_id:'image-demo'},port_suggestions:[]}}})
  await oci.settle(); await oci.button('refreshData').props.onClick()
  assert.equal(oci.calls.filter(c=>c.url.endsWith('/docker-discovery')&&c.method==='POST').length,0)
  console.log('PASS Docker Find: explicit scan, generic evidence, Cancel/Save, failure/partial, CT switch, OCI no-scan')
}
main().catch(error=>{console.error(error);process.exitCode=1})
