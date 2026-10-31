# Agent API

The two editors can be scripted from the ComfyUI page through `window.komikku`, so an agent or a script can design a page and letter it without clicking. The API edits the same JSON the editors save. The result opens in the editors and runs like a hand-made page.

It runs in the browser that has the workflow open, for example a headless Chromium driven by Playwright. The bubbles are drawn with the same canvas renderer the editor uses.

Conventions:
- Panels are numbered from 1 in shot order, as in the editors.
- Page positions are fractions of the page (0 to 1).
- Positions inside a panel (`speaker`, `at`) are fractions of the panel's box.
- Calls fail with a clear error while that node's editor is open.

## Page layout

`komikku.layout(nodeId?)` returns the first *Komikku Page & Shots* node, or the one with that id. Each edit returns `describe()`.

| Call | What it does |
|---|---|
| `describe()` | Page, margin, gutter, direction and template. Each panel's number, aspect (`"16:9"`), shape, box, time span, weight and prompt. |
| `page({format, width, height, margin, gutter, direction})` | Sets the page format: a name from `komikku.pages()` or `width`/`height` in mm. `direction` is `"rtl"` (manga) or `"ltr"` (comic). A page still on its template is rebuilt. |
| `template(id)` | Applies a template from `komikku.templates()`. The shots are kept in order. |
| `split(n, "x" \| "y", {at, slant})` | Cuts panel `n`: `"x"` gives side-by-side panels, `"y"` stacked ones. `at` is the cut position across the panel (0.5 by default). `slant` tilts the cut in page fractions. |
| `cut([x, y], [x, y])` | Knife cut: cuts every panel the segment crosses. |
| `addPanel([x, y, w, h] \| [[x, y], ...], prompt?)` | Adds a rect or polygon panel. |
| `remove(n)`, `reorder([3, 1, 2, ...])`, `renumber()` | Removes a panel, sets a new shot order, or renumbers in reading order. |
| `shot(n, prompt, weight?)`, `shots([...])` | Writes one shot, or every shot in order. A shot is a string or `{prompt, weight}`. |
| `importPage(url \| "komikku/page.png" \| Blob)` | Copies the panel layout of an existing page, like **📄 Import page**. |
| `preview(width?)` | PNG data URL of the layout with shot numbers and aspects. Panels without a prompt are red. |

## Page compose

`komikku.compose(nodeId?)` returns the first *Komikku Page Compose* node. The layout comes from the linked Page & Shots node. Run the workflow once before lettering, so the API knows the panel images.

| Call | What it does |
|---|---|
| `describe()` | Whether the workflow has run and the lettering is saved. Each panel's box, aspect, framing and shot. Each text's id, panel, type, text, box and tail. |
| `frame(n, {zoom, dx, dy})` | Frames panel `n`'s image. `zoom` is over the cover scale (1 fills the panel, 0.5–4). `dx`/`dy` shift the image in fractions of the panel. |
| `await addText(n, type, text, {speaker, at, ...style})` | Adds lettering to panel `n` and returns `{id, box}`. `type` is one of `komikku.textTypes()`. `speaker` is where the tail points, such as the speaking mouth. Without `at`, the bubble is sized to the text and placed where the panel art is least busy: away from other lettering and from the speaker, toward the top and the start of the reading direction. `style` overrides any text field (`size`, `font`, `vertical`, `fill`, `rotation`…). |
| `updateText(id, props)`, `removeText(id)`, `clearTexts()` | Edits lettering. Position fields are in page fractions. |
| `await render(width?)` | JPEG data URL of the page as composed from the last run's panels, with the lettering. |
| `await save()` | Renders and uploads the lettering layer. Run the workflow afterwards for the final page. A text edit after `save()` drops the layer until the next `save()`. |

## Example

```js
const L = komikku.layout();
L.page({ format: "Manga B5", direction: "rtl" });
L.template("manga-5");
L.split(3, "x", { slant: 0.05 });
L.shots(["Wide establishing shot of ...", "Medium shot of <Subject 1> ...", /* one per panel */]);
// run the workflow, then:
const C = komikku.compose();
await C.addText(3, "speech", "Hello? Is someone there?", { speaker: [0.5, 0.55] });
await C.addText(4, "sfx", "MEOW");
const page = await C.render();   // look at it, adjust with updateText / frame
await C.save();                  // run the workflow again for the final page
```

From Playwright, run each call through `page.evaluate`, and queue the workflow with `app.queuePrompt(0)`.

## Stored JSON

The layout widget stores:

```json
{ "page": {"name": "Manga B5", "width": 182, "height": 257}, "margin": 10, "gutter": 4, "direction": "rtl", "preset": "manga-5",
  "panels": [{"x": 0.05, "y": 0.04, "w": 0.9, "h": 0.3, "polygon": [[0.05, 0.04], ...], "prompt": "...", "weight": 1}],
  "reference": {"image": "komikku/layout_ref_x.png", "opacity": 0.5} }
```

- `page` sizes, `margin` and `gutter` are in mm.
- `polygon` is only present on free-form panels; `x`, `y`, `w`, `h` are its bounding box.
- `reference` is editor-only.

The composition widget stores:

```json
{ "panels": [{"zoom": 1, "dx": 0, "dy": 0}], "overlays": [{"id": "...", "panel": 0, "image": "komikku/x.png", "x": 0, "y": 0, "w": 0, "h": 0, "opacity": 1}],
  "texts": [{"id": "...", "type": "speech", "text": "...", "x": 0, "y": 0, "w": 0.3, "h": 0.12, "tail": {"x": 0, "y": 0}, "size": 34, "font": "Comic", ...}],
  "lettering": "komikku/lettering_12_x.png" }
```

- Overlays use a 0-based `panel` index.
- Text `size` is in pixels per 1000 px of page width.
- `lettering` is the rendered layer the backend pastes over the page.
