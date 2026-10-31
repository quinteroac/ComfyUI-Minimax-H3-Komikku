#!/usr/bin/env node
// Drives the Komikku editors' window.komikku API from the command line in a headless Chromium.
// Commands run in order, in one browser session:
//   load <workflow.json>   load a workflow (UI format) into the ComfyUI page, with every seed set to fixed
//   refs                   list the reference pictures: each "Picture N" node and the images it holds
//   ref <n> <img>[,<img>]  upload local images and make them Picture n ("none" empties it)
//   eval <steps.js>        run the file as the body of an async function in the page: `komikku`, `app` and
//                          `keep(name, dataUrl)` (saves an image to the out folder) are in scope; the return value is printed
//   run                    queue the workflow, wait for Komikku Page Compose and save the page as <out>/page_<n>.png
//   save <workflow.json>   write the current workflow, with the edits and the last run's panels, back to a file
// Options: --server http://127.0.0.1:8188, --out <folder> (default ./komikku_out).
// Env: KOMIKKU_PLAYWRIGHT (path to playwright-core or playwright), KOMIKKU_CHROMIUM (browser executable).
const fs = require("fs");
const os = require("os");
const path = require("path");

function loadPlaywright() {
    for (const name of [process.env.KOMIKKU_PLAYWRIGHT, "playwright-core", "playwright"].filter(Boolean)) {
        try { return require(name); } catch { /* try the next one */ }
    }
    throw new Error("playwright-core not found: `npm i -g playwright-core` or set KOMIKKU_PLAYWRIGHT to its folder");
}

// Any Chromium Playwright has downloaded, when the installed playwright-core expects another revision.
function findChromium() {
    if (process.env.KOMIKKU_CHROMIUM) return process.env.KOMIKKU_CHROMIUM;
    const cache = path.join(os.homedir(), ".cache", "ms-playwright");
    if (!fs.existsSync(cache)) return undefined;
    for (const dir of fs.readdirSync(cache).filter((d) => d.startsWith("chromium")).sort().reverse()) {
        for (const sub of fs.readdirSync(path.join(cache, dir))) {
            for (const exe of ["chrome-headless-shell", "chrome"]) {
                const p = path.join(cache, dir, sub, exe);
                if (fs.existsSync(p)) return p;
            }
        }
    }
    return undefined;
}

async function main() {
    const args = process.argv.slice(2);
    const option = (name, fallback) => {
        const i = args.indexOf(name);
        return i < 0 ? fallback : args.splice(i, 2)[1];
    };
    const server = option("--server", "http://127.0.0.1:8188");
    const out = path.resolve(option("--out", "komikku_out"));
    fs.mkdirSync(out, { recursive: true });

    const { chromium } = loadPlaywright();
    const browser = await chromium.launch({ executablePath: findChromium() });
    const page = await browser.newPage({ viewport: { width: 1600, height: 950 } });
    page.on("pageerror", (e) => console.error(`page error: ${e.message}`));
    await page.goto(server, { waitUntil: "networkidle" });
    await page.waitForFunction(() => window.app?.graph && window.komikku, null, { timeout: 90000 });
    // Reference pictures are the workflow nodes titled "Picture N": Load Image, or obvpm Load Images & Compose (several images).
    await page.evaluate(() => {
        window.pictures = () => app.graph.nodes.filter((node) => /^Picture \d+$/.test(node.title ?? ""))
            .map((node) => ({ n: Number(node.title.split(" ")[1]), node })).sort((a, b) => a.n - b.n);
        window.pictureImages = (node) => {
            const w = node.widgets.find((x) => x.name === "image" || x.name === "layers");
            if (w.name === "image") return node.mode === 4 ? [] : [w.value];
            return JSON.parse(w.value || "[]").map((l) => (typeof l === "string" ? l : l.image));
        };
        // A missing Picture N becomes a Load Image wired to the H3 node's next free reference image slot.
        const addPicture = (n) => {
            const h3 = app.graph.nodes.find((x) => x.comfyClass === "MiniMaxH3ReferenceToVideo");
            const slot = h3?.inputs.findIndex((i) => i.name === `ref_images.ref_image_${n - 1}`) ?? -1;
            if (slot < 0 || h3.inputs[slot].link != null) {
                throw new Error(`no "Picture ${n}" node and no free H3 reference slot for it: the workflow has Pictures ${pictures().map((p) => p.n).join(", ") || "none"}`);
            }
            const last = pictures().at(-1)?.node;
            const node = LiteGraph.createNode("LoadImage");
            app.graph.add(node);
            node.title = `Picture ${n}`;
            node.pos = last ? [last.pos[0], last.pos[1] + 340] : [h3.pos[0] - 400, h3.pos[1]];
            node.connect(0, h3, slot);
            return node;
        };
        window.setPicture = (n, names) => {
            const node = pictures().find((p) => p.n === n)?.node ?? (names.length ? addPicture(n) : null);
            if (!node) return { n, images: [] };
            const w = node.widgets.find((x) => x.name === "image" || x.name === "layers");
            if (w.name === "layers") w.value = JSON.stringify(names.map((image) => ({ image })));
            else if (names.length > 1) throw new Error(`Picture ${n} is a Load Image node and takes one image`);
            else if (names.length) { w.value = names[0]; node.mode = 0; } else node.mode = 4;
            app.graph.change?.();
            return { n, images: pictureImages(node) };
        };
    });
    await page.exposeFunction("__komikkuKeep", (name, dataUrl) => {
        const file = path.join(out, name);
        fs.writeFileSync(file, Buffer.from(dataUrl.split(",")[1], "base64"));
        return file;
    });
    let runs = 0;
    try {
        while (args.length) {
            const cmd = args.shift();
            if (cmd === "load") {
                const wf = JSON.parse(fs.readFileSync(args.shift(), "utf8"));
                // Seeds stay fixed: a randomized seed would regenerate the video on the lettering run, under bubbles placed for the old one.
                await page.evaluate(async (wf) => {
                    await app.loadGraphData(wf);
                    for (const node of app.graph.nodes) for (const w of node.widgets ?? []) if (w.name === "control_after_generate") w.value = "fixed";
                }, wf);
                await page.waitForTimeout(1500);
                console.log("loaded");
            } else if (cmd === "refs") {
                console.log(JSON.stringify(await page.evaluate(() => pictures().map(({ n, node }) => ({ n, images: pictureImages(node) }))), null, 1));
            } else if (cmd === "ref") {
                const n = Number(args.shift()), files = args.shift();
                const names = [];
                for (const file of files === "none" ? [] : files.split(",")) {
                    const body = new FormData();
                    body.append("image", new Blob([fs.readFileSync(file)]), path.basename(file));
                    body.append("subfolder", "komikku");
                    body.append("type", "input");
                    body.append("overwrite", "true");
                    const res = await fetch(`${server}/upload/image`, { method: "POST", body });
                    if (!res.ok) throw new Error(`upload of ${file} failed (${res.status})`);
                    const data = await res.json();
                    names.push(data.subfolder ? `${data.subfolder}/${data.name}` : data.name);
                }
                console.log(JSON.stringify(await page.evaluate(({ n, names }) => setPicture(n, names), { n, names })));
            } else if (cmd === "eval") {
                const body = fs.readFileSync(args.shift(), "utf8");
                const result = await page.evaluate(async (body) => {
                    const keep = (name, dataUrl) => window.__komikkuKeep(name, dataUrl);
                    return await new Function("komikku", "app", "keep", `return (async () => {\n${body}\n})();`)(window.komikku, window.app, keep);
                }, body);
                console.log(JSON.stringify(result ?? null, null, 1));
            } else if (cmd === "run") {
                const t0 = Date.now();
                const result = await page.evaluate(async () => {
                    const { api } = await import("/scripts/api.js");
                    const node = app.graph.nodes.find((n) => n.comfyClass === "KomikkuPageCompose");
                    if (!node) throw new Error("no Komikku Page Compose node in the workflow");
                    // A run where nothing changed is all cached and sends no new page: keep the previous one.
                    const previous = node.properties.komikku_page;
                    node.properties.komikku_page = null;
                    return await new Promise((resolve) => {
                        const fail = (e) => resolve({ error: `${e.detail?.node_type ?? ""}: ${e.detail?.exception_message ?? "execution failed"}` });
                        api.addEventListener("execution_error", fail, { once: true });
                        api.addEventListener("execution_success", () => setTimeout(() => resolve({ page: node.properties.komikku_page ?? previous }), 1500), { once: true });
                        const timer = setInterval(() => {
                            if (node.properties.komikku_page) { clearInterval(timer); resolve({ page: node.properties.komikku_page }); }
                        }, 2000);
                        app.queuePrompt(0).then((ok) => { if (ok === false) resolve({ error: "the workflow did not queue: check missing nodes or inputs" }); });
                    });
                });
                if (result.error) throw new Error(result.error);
                if (!result.page) throw new Error("the run finished without a composed page: is Komikku Page Compose connected to an output?");
                const ref = result.page;
                const res = await fetch(`${server}/view?filename=${encodeURIComponent(ref.filename)}&subfolder=${encodeURIComponent(ref.subfolder ?? "")}&type=${ref.type}`);
                const file = path.join(out, `page_${++runs}.png`);
                fs.writeFileSync(file, Buffer.from(await res.arrayBuffer()));
                console.log(`run done in ${Math.round((Date.now() - t0) / 1000)}s: ${file}`);
            } else if (cmd === "save") {
                const file = args.shift();
                fs.writeFileSync(file, JSON.stringify(await page.evaluate(() => app.graph.serialize()), null, 1));
                console.log(`saved ${file}`);
            } else {
                throw new Error(`unknown command "${cmd}": use load, eval, run or save`);
            }
        }
    } finally {
        await browser.close();
    }
}

main().catch((e) => { console.error(e.message); process.exit(1); });
