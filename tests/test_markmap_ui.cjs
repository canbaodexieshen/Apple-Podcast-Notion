const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

test('Markmap uses a bundled renderer, escaped headings, zoom and theme controls', () => {
  const source=fs.readFileSync(path.join(__dirname,'../web/mindmap.js'),'utf8').replace(/^import .*;$/gm,'');
  const nodes=Object.fromEntries(['map-data','map','fit','in','out','theme'].map(id=>[id,{}]));
  nodes['map-data'].textContent=JSON.stringify('# Topic\n## <img src=x>\nparagraph must not appear');
  let transformed, options, dark;
  const calls=[];
  const context={
    Transformer:class {transform(s){transformed=s;return {root:{}};}},
    Markmap:{create(svg,opts){options=opts;return {fit(){calls.push('fit')},rescale(x){calls.push(x)}}}},
    document:{getElementById(id){return nodes[id]},documentElement:{classList:{toggle(name,value){dark=value}}}},
    matchMedia(){return {matches:false}},window:{addEventListener(){}}
  };
  vm.runInNewContext(source,context);
  assert.match(transformed,/&lt;img/);
  assert.doesNotMatch(transformed,/paragraph/);
  assert.equal(options.initialExpandLevel,2);
  nodes.in.onclick();nodes.out.onclick();nodes.fit.onclick();nodes.theme.onclick();
  assert.deepEqual(calls,[1.25,.8,'fit']);
  assert.equal(dark,true);
});
