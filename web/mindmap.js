import { Transformer } from 'markmap-lib';
import { Markmap, deriveOptions } from 'markmap-view';

const source = JSON.parse(document.getElementById('map-data').textContent);
// Only heading lines are accepted. Escape markup so model output cannot inject HTML.
const outline = source.split('\n').filter(line => /^#{1,4}\s/.test(line))
  .map(line => line.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'))
  .join('\n');
const {root} = new Transformer().transform(outline);
const map = Markmap.create(document.getElementById('map'), deriveOptions({
  color: ['#6d8eff', '#bc7ae8', '#49bbaa', '#e3a056', '#ed7e9c'],
  initialExpandLevel: 2, maxWidth: 240, paddingX: 16, spacingVertical: 12,
  duration: 250, autoFit: true,
}));
const ready = map.setData(root).then(() => map.fit());
let capturing = false;

// The exporter waits for real layout, expands every node, then captures at 1:1.
window.podcastMindmap = {
  async snapshot() {
    await ready;
    capturing = true;
    await document.fonts.ready;
    const complete = new Transformer().transform(outline).root;
    await map.setData(complete, {initialExpandLevel: -1, duration: 0, autoFit: false});
    // D3 schedules even zero-duration transitions on its next animation frame.
    // Let the renderer's ResizeObserver measure newly expanded text first.
    await new Promise(resolve => setTimeout(resolve, 150));
    await map.renderData();
    await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    const bounds = map.g.node().getBBox();
    const width = Math.ceil(bounds.width + 96), height = Math.ceil(bounds.height + 96);
    const svg = document.getElementById('map');
    document.documentElement.classList.remove('dark');
    document.querySelector('header').style.display = 'none';
    document.querySelector('footer').style.display = 'none';
    svg.style.width = `${width}px`; svg.style.height = `${height}px`;
    svg.style.minHeight = '0'; svg.style.display = 'block';
    svg.setAttribute('width', width); svg.setAttribute('height', height);
    svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
    map.g.attr('transform', `translate(${48 - bounds.x},${48 - bounds.y})`);
    return {width, height, nodes: document.querySelectorAll('.markmap-node').length};
  },
};
document.getElementById('fit').onclick = () => map.fit();
document.getElementById('in').onclick = () => map.rescale(1.25);
document.getElementById('out').onclick = () => map.rescale(.8);
let dark = matchMedia('(prefers-color-scheme: dark)').matches;
function theme() { document.documentElement.classList.toggle('dark', dark); }
document.getElementById('theme').onclick = () => { dark = !dark; theme(); };
theme();
window.addEventListener('resize', () => { if (!capturing) map.fit(); });
ready.catch(() => {
  const message = document.createElement('p');
  message.textContent = '脑图渲染失败，请重新同步后重试。';
  document.body.appendChild(message);
});
