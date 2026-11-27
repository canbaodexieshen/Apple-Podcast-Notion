import { Transformer } from 'markmap-lib';
import { Markmap } from 'markmap-view';

const source = JSON.parse(document.getElementById('map-data').textContent);
// Only heading lines are accepted. Escape markup so model output cannot inject HTML.
const outline = source.split('\n').filter(line => /^#{1,4}\s/.test(line))
  .map(line => line.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'))
  .join('\n');
const {root} = new Transformer().transform(outline);
const map = Markmap.create(document.getElementById('map'), {
  color: ['#6d8eff', '#bc7ae8', '#49bbaa', '#e3a056', '#ed7e9c'],
  initialExpandLevel: 2, maxWidth: 240, paddingX: 16, spacingVertical: 12,
  duration: 250, autoFit: true,
}, root);
document.getElementById('fit').onclick = () => map.fit();
document.getElementById('in').onclick = () => map.rescale(1.25);
document.getElementById('out').onclick = () => map.rescale(.8);
let dark = matchMedia('(prefers-color-scheme: dark)').matches;
function theme() { document.documentElement.classList.toggle('dark', dark); }
document.getElementById('theme').onclick = () => { dark = !dark; theme(); };
theme();
window.addEventListener('resize', () => map.fit());
