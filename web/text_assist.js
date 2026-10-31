import { api } from "../../scripts/api.js";

// Text assist for the page editors: runs the CLIP Loader wired to a node's `assist_clip` input through TextGenerate
// as a tiny prompt of its own on the local queue, then hands the generated text back for review.

const CSS = `
.kmk-assist { display: flex; flex-direction: column; gap: 6px; }
.kmk-assist-row { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.kmk-assist-row .h3pe-btn { height: 30px; }
.kmk-assist-status { color: var(--pe-muted); font-size: 11px; flex: 1; min-width: 0; }
.kmk-assist-status.err { color: var(--pe-warn); }
.kmk-proposal { border: 1px solid var(--pe-blue); border-radius: 8px; background: rgba(63,208,230,.07); padding: 8px; display: flex; flex-direction: column; gap: 6px; }
.kmk-proposal textarea { min-height: 70px; flex: 0 0 auto; }
.kmk-proposal-title { color: var(--pe-blue); font-size: 11px; font-weight: 600; }
`;

function installCss() {
    if (document.getElementById("kmk-assist-style")) return;
    const style = document.createElement("style");
    style.id = "kmk-assist-style";
    style.textContent = CSS;
    document.head.appendChild(style);
}

// The loader settings of the CLIP Loader linked to `assist_clip`, or null when nothing usable is wired.
export function assistLoader(node) {
    const slot = node.inputs?.findIndex((i) => i.name === "assist_clip");
    const source = slot >= 0 ? node.getInputNode?.(slot) : null;
    const value = (name) => source?.widgets?.find((w) => w.name === name)?.value;
    if (!value("clip_name") || !value("type")) return null;
    return { clip_name: value("clip_name"), type: value("type"), device: value("device") ?? "default" };
}

function clean(text) {
    return text.replace(/<think>[\s\S]*?<\/think>/g, "").trim().replace(/^["“'`]+|["”'`]+$/g, "").trim();
}

export async function generateText(loader, system, prompt, creative = false) {
    const sampling = creative
        ? { sampling_mode: "on", "sampling_mode.temperature": 0.8, "sampling_mode.top_k": 64, "sampling_mode.top_p": 0.95, "sampling_mode.min_p": 0.05,
            "sampling_mode.repetition_penalty": 1.05, "sampling_mode.seed": Math.floor(Math.random() * 2 ** 31) }
        : { sampling_mode: "off" };
    const graph = {
        "1": { class_type: "CLIPLoader", inputs: loader },
        "2": { class_type: "TextGenerate", inputs: { clip: ["1", 0], prompt, system_prompt: system, max_length: 400, thinking: false, use_default_template: true, mtp: "auto", ...sampling } },
        "3": { class_type: "PreviewAny", inputs: { source: ["2", 0] } },
    };
    return clean(await runPrompt(graph, "3"));
}

// Queues an API-format graph on the local server and resolves with the text shown by its PreviewAny node `output`.
export async function runPrompt(graph, output) {
    const res = await api.fetchApi("/prompt", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ prompt: graph, client_id: api.clientId ?? api.initialClientId }) });
    const data = await res.json();
    if (!res.ok) throw new Error(data?.error?.message ?? `queue failed (${res.status})`);
    const id = data.prompt_id;
    return new Promise((resolve, reject) => {
        const done = (fn, value) => { api.removeEventListener("executed", onExecuted); api.removeEventListener("execution_error", onError); clearTimeout(timer); fn(value); };
        const onExecuted = ({ detail }) => { if (detail?.prompt_id === id && String(detail.node) === output) done(resolve, String(detail.output?.text?.[0] ?? "")); };
        const onError = ({ detail }) => { if (detail?.prompt_id === id) done(reject, new Error(detail.exception_message ?? "generation failed")); };
        const timer = setTimeout(() => done(reject, new Error("timed out after 10 minutes")), 600000);
        api.addEventListener("executed", onExecuted);
        api.addEventListener("execution_error", onError);
    });
}

// Buttons, a status line and a reviewable proposal (Apply / Discard). `el` and `button` come from the editors.
export function assistPanel(node, el, button, actions, onApply) {
    installCss();
    const root = el("div", "kmk-assist");
    const row = el("div", "kmk-assist-row");
    const status = el("div", "kmk-assist-status");
    const proposal = el("div");
    const buttons = actions.map(({ label, title, run }) => button(label, title, async () => {
        const loader = assistLoader(node);
        if (!loader) {
            status.className = "kmk-assist-status err";
            status.textContent = "Wire a CLIP Loader (e.g. the MOSS-Image text encoder) to this node's assist_clip input.";
            return;
        }
        buttons.forEach((b) => { b.disabled = true; });
        status.className = "kmk-assist-status";
        status.textContent = `Writing with ${loader.clip_name.split("/").pop()}… (first use loads the model)`;
        try {
            const text = await run(loader);
            status.textContent = "";
            show(text);
        } catch (err) {
            status.className = "kmk-assist-status err";
            status.textContent = `Could not generate: ${err.message}`;
        } finally {
            buttons.forEach((b) => { b.disabled = false; });
        }
    }, "outline"));
    const show = (text) => {
        if (!text) { status.textContent = "The model returned no text; try again."; return; }
        const box = el("div", "kmk-proposal");
        const area = el("textarea");
        area.value = text;
        const act = el("div", "kmk-assist-row");
        act.append(button("Apply", "Replace the text with this proposal", () => { onApply(area.value); proposal.replaceChildren(); }, "primary"),
            button("Discard", "Keep the current text", () => proposal.replaceChildren(), "outline"));
        box.append(el("div", "kmk-proposal-title", "Proposal (edit it before applying if you like)"), area, act);
        proposal.replaceChildren(box);
    };
    row.append(...buttons, status);
    root.append(row, proposal);
    return root;
}
