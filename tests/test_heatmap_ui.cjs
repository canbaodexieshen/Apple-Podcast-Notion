const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const html = fs.readFileSync(path.join(__dirname, "../web/index.html"), "utf8");
const script = html.split("<script>")[1].split("</script>")[0];

class Element {
    constructor() {
        this.options = [];
        this.children = [];
        this.listeners = {};
        this.attributes = [];
        this.className = "";
        this.localName = "svg";
    }
    add(option) { this.options.push(option); }
    addEventListener(name, listener) { this.listeners[name] = listener; }
    replaceChildren(...children) {
        this.children = children;
        if (this.isSelect) this.options = children;
    }
    querySelectorAll() { return []; }
    setAttribute(name, value) { this[name] = value; }
    async dispatch(name, event = {}) {
        if (this.listeners[name]) await this.listeners[name](event);
    }
}

async function openPage(query) {
    const elements = Object.fromEntries(
        ["heatmap-content", "year-select", "theme-toggle"].map(id => [id, new Element()])
    );
    elements["year-select"].isSelect = true;
    const classes = new Set();
    const location = {href: "https://example.github.io/duolingo-notion/" + query, search: query};
    const requests = [];
    const media = {matches: false, addEventListener(name, listener) { this.listener = listener; }};
    const context = {
        URL,
        URLSearchParams,
        AbortController,
        Option: function(text, value) { this.textContent = text; this.value = value; },
        navigator: {userAgent: "Desktop", platform: "Win32", maxTouchPoints: 0},
        location,
        history: {replaceState(state, title, url) { location.href = String(url); }},
        window: {matchMedia() { return media; }},
        document: {
            getElementById(id) { return elements[id]; },
            body: {classList: {
                add(name) { classes.add(name); },
                remove(name) { classes.delete(name); },
                contains(name) { return classes.has(name); },
            }},
            createElement() { return new Element(); },
            importNode(node) { return node; },
        },
        DOMParser: class {
            parseFromString(markup) {
                const svg = new Element();
                svg.markup = markup;
                return {documentElement: svg, querySelector() { return null; }};
            }
        },
        async fetch(url) {
            requests.push(url);
            return {
                ok: true,
                json: async () => ({current: 2026, years: [2026, 2025, 2024]}),
                text: async () => "<svg>" + url + "</svg>",
            };
        },
    };
    vm.runInNewContext(script, context);
    await new Promise(resolve => setImmediate(resolve));
    return {elements, classes, location, requests, media};
}

test("year query, historical files, all-year summary and dark mode share Read-notion paths", async () => {
    const page = await openPage("?year=2025&theme=dark");
    assert.equal(page.elements["year-select"].value, "2025");
    assert.ok(page.classes.has("dark-mode"));
    assert.match(page.elements["heatmap-content"].children[0].markup, /old_heatmap\/2025.svg/);
    const selector = page.elements["year-select"];
    selector.value = "current";
    await selector.dispatch("change");
    await new Promise(resolve => setImmediate(resolve));
    assert.match(page.elements["heatmap-content"].children[0].markup, /study_heatmap\/main.svg/);
    assert.equal(new URL(page.location.href).searchParams.get("year"), "2026");
    selector.value = "all";
    await selector.dispatch("change");
    await new Promise(resolve => setImmediate(resolve));
    assert.match(page.elements["heatmap-content"].children[0].markup, />heatmap.svg</);
    await page.elements["theme-toggle"].dispatch("click");
    assert.ok(!page.classes.has("dark-mode"));
    assert.equal(new URL(page.location.href).searchParams.get("theme"), "light");
    page.media.listener({matches: true});
    assert.ok(!page.classes.has("dark-mode"));
});

test("reference image parameter and explicit light theme remain supported", async () => {
    const page = await openPage("?image=heatmap-2026.svg&theme=light");
    assert.ok(page.requests.includes("heatmap-2026.svg"));
    assert.ok(!page.classes.has("dark-mode"));
    assert.equal(page.elements["year-select"].disabled, false);
});
