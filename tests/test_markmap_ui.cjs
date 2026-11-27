const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

test('Markmap uses a bundled renderer, escaped headings, zoom and theme controls', async () => {
  const source=fs.readFileSync(path.join(__dirname,'../web/mindmap.js'),'utf8').replace(/^import .*;$/gm,'');
  const nodes=Object.fromEntries(['map-data','map','fit','in','out','theme'].map(id=>[id,{}]));
  nodes['map-data'].textContent=JSON.stringify('# Topic\n## <img src=x>\nparagraph must not appear');
  nodes.map.getBoundingClientRect=()=>({width:1000,height:800});
  let transformed, options, dark;
  const calls=[];
  const context={
    Transformer:class {transform(s){transformed=s;return {root:{}};}},
    deriveOptions(opts){return {...opts, color: () => opts.color[0]}},
    Markmap:{create(svg,opts){options=opts;return {setData(){return Promise.resolve()},renderData(){return Promise.resolve()},fit(){calls.push('fit');return Promise.resolve()},rescale(x){calls.push(x)}}}},
    document:{fonts:{ready:Promise.resolve()},getElementById(id){return nodes[id]},documentElement:{classList:{toggle(name,value){dark=value}}}},
    ResizeObserver:class {observe(){}},requestAnimationFrame(){return 1},cancelAnimationFrame(){},
    matchMedia(){return {matches:false}},window:{addEventListener(){}}
  };
  vm.runInNewContext(source,context);
  await context.window.podcastMindmap.ready;
  calls.length=0;
  assert.match(transformed,/&lt;img/);
  assert.doesNotMatch(transformed,/paragraph/);
  assert.equal(options.initialExpandLevel,-1);
  assert.equal(typeof options.color,'function');
  nodes.in.onclick();nodes.out.onclick();await nodes.fit.onclick();nodes.theme.onclick();
  assert.deepEqual(calls,[1.25,.8,'fit']);
  assert.equal(dark,true);
});
