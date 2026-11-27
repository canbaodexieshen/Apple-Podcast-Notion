"""Offline real-browser rendering of all expanded Markmap nodes, without clipping."""
import os
import re
from playwright.sync_api import sync_playwright


def screenshot(html):
    with sync_playwright() as p:
        channel=os.getenv('MINDMAP_BROWSER_CHANNEL')
        browser=p.chromium.launch(headless=True,**({'channel':channel} if channel else {}))
        try:
            page=browser.new_page(viewport={'width':1600,'height':1000},device_scale_factor=1)
            errors=[]
            page.on('pageerror',lambda e:errors.append(str(e)))
            page.route('**/*',lambda route:route.abort())
            page.set_content(html,wait_until='load')
            page.wait_for_function('window.podcastMindmap && document.querySelector(".markmap-node")')
            bounds=page.evaluate('window.podcastMindmap.snapshot()')
            width,height=bounds['width'],bounds['height']
            if not 1<=width<=30000 or not 1<=height<=30000 or width*height>80_000_000:
                raise ValueError('Expanded mindmap exceeds safe image dimensions; no partial cover saved')
            page.set_viewport_size({'width':max(width,400),'height':max(height,400)})
            # Geometry and every node must be settled before capturing foreignObject text.
            page.evaluate('() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))')
            clipped=page.evaluate('''() => {
                const svg=document.getElementById('map').getBoundingClientRect();
                return [...document.querySelectorAll('.markmap-foreign')].some(node => {
                    const r=node.getBoundingClientRect();
                    const text=node.firstChild.firstChild.getBoundingClientRect();
                    return r.left<svg.left || r.top<svg.top || r.right>svg.right || r.bottom>svg.bottom ||
                        text.width>r.width+1 || text.height>r.height+1;
                });
            }''')
            expected=page.evaluate('JSON.parse(document.getElementById("map-data").textContent)')
            if bounds['nodes']<len(re.findall(r'^#{1,4}\s',expected,re.M)) or errors or clipped:
                raise ValueError('Markmap rendering failed or did not expand all outline nodes')
            png=page.locator('#map').screenshot(type='png',animations='disabled')
            return png, bounds
        finally:
            browser.close()
