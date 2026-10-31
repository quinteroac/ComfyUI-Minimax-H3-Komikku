# Minimax-H3-Komikku

This pack turns a MiniMax H3 reference-to-video multishot generation into a manga or comic page. You design the page first. Each panel becomes one hard-cut shot of the video, and each shot is turned back into its panel.

| Superheroes | Detective | Manga | Dark |
|---|---|---|---|
| ![Superheroes](docs/superheroes.jpg) | ![Detective](docs/detective.jpg) | ![Manga](docs/manga.jpg) | ![Dark](docs/dark.jpg) |

## Installation

Clone this repository into `ComfyUI/custom_nodes` and restart ComfyUI:

```bash
cd ComfyUI/custom_nodes
git clone https://github.com/quinteroac/ComfyUI-Minimax-H3-Komikku
```

## Nodes

### Komikku Page & Shots

The node is a page layout editor that opens fullscreen from the node.

- Page formats: manga B5/A5, US comic, A4, square, 16:9 or custom. Margin and gutter are adjustable, and the reading order can be manga (right to left) or comic (left to right).
- 15 layout templates, plus free drawing of rectangles and polygons, slanted cuts with the knife tool, and corner editing.
- **📄 Import page** copies the panel layout of an existing comic or manga page. The panels are numbered in reading order, and the page stays behind them as a reference with adjustable opacity.
  - When the ComfyUI-WeVisOne-VL nodes are installed with a [WeVisOne-VL-4B](https://huggingface.co/tencent/WeVisOne-VL-4B) model in `models/text_encoders`, the model finds the panels, even borderless ones and panels joined by art or balloons. It takes about 2 s a page once the model is loaded. Slanted cuts keep their shape from the gutters.
  - Without it, the panels are found in the browser from the gutters (white or black paper between panels). Art or balloons that cross a gutter can join two panels into one: fix them with the cut and corner tools.
- Panels are numbered. The number sets the shot order, and you can change it by hand or renumber in reading order.
- One prompt per panel. An optional length weight per shot sits under *Advanced options*.
- **✨ Enhance with CLIP** rewrites a shot into a richer H3 shot description. It uses the panel's aspect ratio and the neighbouring shots as context, and shows a proposal you can edit before applying.

Outputs:
- `prompt`: the H3 full-reference prompt. Cut timestamps are added automatically from `duration` and the shot weights.
- `panel_width` / `panel_height`: one value per panel, from its aspect on the page and `panel_megapixels`.
- `layout`: the page layout, for the compose node.

### Komikku Shot Frames

Finds the hard cuts of the multishot video and returns the middle frame of each shot, one per panel of the layout. The cuts are the largest frame-to-frame changes, so it always returns as many frames as the page has panels and needs no extra dependencies. `min_shot_frames` ignores cuts closer than that many frames.

### Komikku Fit Frame

This utility node is optional and bypassed in the example workflow. It center-crops each shot frame toward its panel's aspect ratio before the reframe model, so the model never fills more than `max_extend` times the frame. It removes content from the frame, so the example workflow instead generates the video at 1:1, which suits both wide and tall panels. A 21:9 strip made from a 9:16 frame comes back mirrored, with two moons; from a 1:1 frame it keeps one.

### Komikku Page Compose

The node composes the final page and has its own fullscreen editor. The layout comes from Komikku Page & Shots and is fixed in this editor. In the editor you can:

- Move and zoom each panel image inside its panel.
- Add lettering of 8 types: speech, thought, shout, whisper, box, caption, SFX and free text. Each has its own font, size, colors, border, outline, rotation, tail and vertical text option.
- Import RGB/RGBA images over a panel. They are clipped to the panel shape.
- Star imported images to keep them in a personal library.
- Install local TTF/OTF/WOFF/WOFF2 fonts.
- **✨ Improve** / **💡 Suggest** rewrite or write a line for the selected bubble, using its type, the panel's shot and the rest of the page's text.

Both editors' text assist runs the CLIP Loader wired to the node's optional `assist_clip` input. The example workflow wires the MOSS-Image Qwen3.5-9B encoder there. The input is lazy, so the model is only loaded when you use the assist, never when the workflow runs.

Run the workflow once to load the panel images into the editor. After you save, run it again: only the page is recomposed.

### Agent API

Agents and scripts can design and letter pages through `window.komikku` in the ComfyUI page. It provides templates, cuts and shots for the layout, plus framing, lettering with automatic bubble placement, renders and save for the composer. See [docs/AGENT_API.md](docs/AGENT_API.md).

[skills/komikku-pages](skills/komikku-pages) is an agent skill built on the API. It covers laying out the page, writing the shots, running the workflow and lettering, and drives a headless Chromium through `scripts/komikku.cjs`, which needs `playwright-core`. To install it for Claude Code, link it into your skills folder:

```bash
ln -s "$PWD/skills/komikku-pages" ~/.claude/skills/komikku-pages
```

Files the editors write:

| What | Where |
|---|---|
| Imported images and the lettering layer | `input/komikku/` |
| Installed fonts | `user/<user>/komikku_fonts/` |
| Image library (only starred images) | `user/<user>/komikku_library/` |

## Example workflows

### Simple

`example_workflows/Minimax-H3-Komikku-Simple.json` needs only this pack and core ComfyUI:

1. Komikku Page & Shots builds the H3 prompt from the page.
2. H3 ref2vid generates the multishot video from Picture 1 and saves it.
3. Komikku Shot Frames takes one frame per shot.
4. Komikku Page Compose crops each frame into its panel and letters the page.

Panels are cropped from the video frames, so the video is generated at 1:1 to fit both wide and tall panels.

### Full

`example_workflows/Minimax-H3-Komikku.json` runs the full pipeline:

1. H3 ref2vid multishot video at 0.5 MP.
2. Scene detection, one frame per shot.
3. FLUX 3 Klein reframes each frame to its panel's aspect ratio.
4. Optional MOSS-Image hi-res pass (up to 5 MP).
5. Page composition.

The four genre pages above come from `example_workflows/Komikku Superheroes.json`, `Komikku Detective.json`, `Komikku Manga.json` and `Komikku Dark.json`. Load your own character into Picture 1 before running them. The Manga example uses a manga screentone LoRA (`manga_tone_v2.safetensors`, trigger `manga-tone rendering`) on H3; clear it in the H3 Power Lora Loader if you don't have it.

It is laid out in color-coded groups:
- Models.
- References: up to 4 pictures.
- Page & Story: the layout editor.
- Controls: sliders, the seed and a MOSS hi-res on/off switch.
- Result.
- Processing.

Load your own reference images in *Picture 1–4*.

Custom nodes the workflow needs:
- [Comfyui-ZNGB-SceneDetect](https://github.com/zhinangubei/Comfyui-ZNGB-SceneDetect), which needs the `scenedetect` Python package.
- [ComfyUI-VideoHelperSuite](https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite).
- [ComfyUI-Pixaroma](https://github.com/pixaroma/ComfyUI-Pixaroma): sliders, seed, group switch and labels.
- [rgthree-comfy](https://github.com/rgthree/rgthree-comfy): *Any Switch*, which picks the hi-res panels or the Klein panels.
- [comfyui-obvpm](https://github.com/chanon/comfyui-obvpm): *Load Images & Compose*, the reference pictures.

Models it loads (each one is under its own license; check it before commercial use):
- MiniMax H3 ref2va, its video and audio VAEs and its Qwen3-VL text encoder, plus the taomate H3 3-step LoRA.
- FLUX 3 Klein with the Qwen3-VL 4B text encoder and the FLUX.2 VAE.
- MOSS-Image SFT with the Qwen3.5-9B encoder and the 8-step DMD LoRA.

## Acknowledgements

- **[ComfyUI-Pixaroma](https://github.com/pixaroma/ComfyUI-Pixaroma)** by pixaroma (MIT). The editors take a lot of inspiration from Pixaroma's Paint and Composer editors:
  - The compact node with an *Open editor* button and a page preview.
  - The fullscreen editor with side panels and collapsible sections.
  - Keeping ComfyUI's Ctrl+Z away from the graph while an editor is open, through `ComfyApp.maskeditor_is_opended`.

  No Pixaroma code is included. Thank you for the great UX reference.
- **[ComfyUI-MangaMakerStudio](https://github.com/quinteroac/ComfyUI-MangaMakerStudio)**. Reference for the page and lettering editor: bubble styles, tails, text that shrinks to fit its bubble, polygon panels and local font installation.
- **[Comfyui-ZNGB-SceneDetect](https://github.com/zhinangubei/Comfyui-ZNGB-SceneDetect)** (MIT) and **[PySceneDetect](https://github.com/Breakthrough/PySceneDetect)** (BSD-3-Clause) for shot detection in the example workflow.
- **[ComfyUI-VideoHelperSuite](https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite)** (GPL-3.0) for video loading and saving in the example workflow.
- **[comfyui-obvpm](https://github.com/chanon/comfyui-obvpm)** (GPL-3.0) for the reference loaders. The workflow layout also follows the OBVPM H3 timeline workflow.
- **[rgthree-comfy](https://github.com/rgthree/rgthree-comfy)** (MIT) for *Any Switch*.
- The Anima CharRef workflows (`anima_charref_snapref_posestudio_moss_upscale`) inspired the example workflow's layout: color-coded groups, a control panel and an on/off hi-res pass.
- **[ComfyUI](https://github.com/Comfy-Org/ComfyUI)** and its frontend (GPL-3.0), which provide the node API, the native MiniMax H3 nodes and the samplers this pack builds on.
- The MiniMax H3, FLUX 3 Klein, MOSS-Image and Qwen teams for the models used by the example workflow.

## License

MIT, see [LICENSE](LICENSE). This covers the nodes, the editors and the example workflow.

The pack does not include or relicense any third-party code, custom node or model weights. The example workflow only references them by name, and each keeps its own license. The pack runs inside ComfyUI, which is GPL-3.0.
