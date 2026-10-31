---
name: komikku-pages
description: Design, generate and letter manga/comic pages with the Minimax-H3-Komikku ComfyUI nodes through their window.komikku agent API. Always starts with a brief from the user: reference images, story, panel count and look. Use when asked to lay out a comic or manga page, write its shots, run the Komikku workflow, or add speech bubbles, captions and SFX to a Komikku page.
---

# Komikku pages

The Komikku pack turns a MiniMax H3 multishot video into a comic page. **Komikku Page & Shots** holds the layout, with one panel per shot. **Komikku Page Compose** frames the panel images and letters the page. Both are scripted through `window.komikku` in the ComfyUI page. `scripts/komikku.cjs` runs that API from the shell in a headless Chromium.

The full API and the stored JSON are in the pack's `docs/AGENT_API.md`, at `ComfyUI/custom_nodes/ComfyUI-Minimax-H3-Komikku/docs/AGENT_API.md`. Read it before the first call.

## Running the API

```bash
node scripts/komikku.cjs --out <folder> load <workflow.json> ref 1 <character.png> eval <steps.js> [run] [eval <more.js>] save <workflow.json>
```

- **`refs`** lists the reference pictures: each `Picture N` node and the images it holds.
- **`ref <n> <img>[,<img>]`** uploads local images to `input/komikku` and makes them Picture n. `none` empties the slot. A missing Picture n, such as Picture 2 in the Simple workflow, is added as a Load Image wired to the next H3 reference slot, so number the Pictures without gaps.

- **Commands** run in order in one browser session, so a `run` between two `eval`s letters the panels it just generated.
- **`eval`** runs a file as the body of an async function, with `komikku`, `app` and `keep(name, dataUrl)` in scope. `keep` saves an image into `--out`, and the function's return value is printed as JSON.
- **`run`** queues the workflow and waits; a full run takes about 4 minutes. It saves the page as `<out>/page_<n>.png`. Run it in the background.
- **`load`** sets every seed to *fixed*, so the lettering run reuses the panels you lettered. For a new take of the video, change the seed on purpose: `app.graph.nodes.find((n) => n.type === "RandomNoise").widgets[0].value = 123`.
- **`save`** writes the workflow with your edits and the last run's panels. `load` that file in the next call to continue.

Requirements:
- ComfyUI running, by default at `http://127.0.0.1:8188` (`--server` to change it).
- `playwright-core` with a Chromium. Set `KOMIKKU_PLAYWRIGHT` to the module folder and `KOMIKKU_CHROMIUM` to the browser if they are not found.

Work on a copy of the user's workflow, in the out folder. Never overwrite the files in `user/default/workflows` unless the user asks. Start from `example_workflows/Minimax-H3-Komikku-Simple.json` or a workflow the user names.

## Workflow

0. **Get the brief first, before anything else.** The workflow's references, story fields, layout and shots belong to a previous page or to the example: never reuse them as the user's page. Ask in one message for whatever the user has not already given:
   - **References:** the images and what each one is (a character, a location, an object, a style). The user can give them, or ask you to create them; offer that when they have none. See *Creating references* below.
   - **Story:** what happens on the page: the beat or scene, who is in it, and how it ends. The page is a single scene of a few seconds of video, not a chapter.
   - **Panels:** how many, or leave it to you. Pages read well with 3–7 panels. Each panel is one shot of the video, so plan about 1.5–2.5 s of `duration` per panel, within what the H3 length allows (the example workflows use 10 s).
   - **Look:** the style (manga black-and-white, color anime, western comic…), reading direction, and the language of the lettering.

   Offer sensible defaults the user can accept in one word, such as: "5 panels, color anime, manga order, English lettering". Before laying out, sum up the page in two or three lines, shot by shot, and wait for the user's go-ahead.

   Then load the references:
   - H3 draws the characters, places and props from the reference pictures, so never assume the workflow's pictures (a previous page's, or `komikku_example_character.png`) are the ones to use.
   - If the user says to keep the workflow's references, run `refs`, look at those images and confirm what they show before writing shots.
   - Load them with `ref <n> <image>`, one Picture per subject. A Load Images & Compose Picture can take several images as one sheet, such as front and side views of one character. Empty unused Pictures with `ref <n> none`.
   - Write `story({ subjects })` so each `<Subject N>` names its `<Picture N>` and its role. For example: `<Subject 1> is the girl in <Picture 1>: appearance, hair and outfit follow it. <Subject 2> is the black cat in <Picture 2>.`
1. **Inspect:** call `komikku.layout().describe()` and look at the story fields and the existing shots on the Page & Shots node.
2. **Lay out the page** with exactly the agreed panel count:
   - Use `page`, `template`, `split`, `cut` and `addPanel`. `komikku.templates()` lists the templates with their panel counts. Split or remove panels to reach the agreed count.
   - Set the `duration` agreed in the brief with `story({ duration })`, along with the `style`, `soundscape` and `music` lines that fit the story.
   - Use `"rtl"` for manga and `"ltr"` for western comics.
   - Vary panel sizes: a wide establishing panel, small panels for reactions, a large one for the climax.
   - `keep("layout.png", komikku.layout().preview())` and look at it before going on.
3. **Write one shot per panel** with `shots([...])`, in panel order:
   - Start with the framing (wide shot, medium shot, close-up, low angle), then the action, setting and light.
   - Keep `<Subject N>` tags as the subjects define them, and never describe the subject's looks: Picture 1 does.
   - End static shots with "Static camera."; a panel is one frame of the shot.
   - Frame each shot for its panel's aspect (`describe().panels[i].aspect`).
   - For a black-and-white style, say "black-and-white manga ink and grey screentone" inside shot 1 too. The first shot otherwise follows the colors of the reference picture.
4. **Run** the workflow.
5. **Look at the panels:**
   - `keep("panels.jpg", await komikku.compose().render())`.
   - For each panel, note where faces and mouths are, as fractions of the panel box. You need them for the tails.
6. **Letter the page:**
   - Use `await compose.addText(n, type, text, { speaker: [x, y] })`, with `speaker` at the speaking mouth.
   - Text types:
     - `speech`, `thought`, `shout` and `whisper` for characters.
     - `caption` for narration.
     - `sfx` for sound effects.
     - `rounded` for a boxy balloon.
   - Lines are short: about 4–12 words per bubble, one idea each.
   - Place bubbles in reading order: top-right first for manga, top-left for comics. The placer leans that way on its own.
   - Without `speaker` the placer can pick a face, because skin reads as empty space. Always give `speaker` for character lines.
   - Check with `render()`. Fix covered faces, wrong tails or crowded panels with `updateText(id, {x, y, w, h, tail, size})`, `removeText` or `frame(n, {zoom, dx, dy})`.
7. **Save and run:** `await compose.save()`, then `run` again (only the page is recomposed), then `save` the workflow.
8. **Show the user** the final `page_<n>.png` and the workflow file. Mention anything you could not fix.

## Creating references

When the user wants you to make the reference images, use what your environment offers:
- **ComfyUI:** a ComfyUI MCP server if one is connected, or a text-to-image workflow of the user's run on the same server. The pack has no image model of its own.
- **Built-in image generation,** if you have it, as Codex, Grok and similar agents do.

Make each image a clean reference:
- One subject per image, on a plain light background.
- Characters: full body in a neutral pose, face clearly visible, the whole outfit shown.
- Places: an establishing view with no people in it.
- Draw them in the page's style, color or black-and-white, because H3 copies the look of the reference.
- Keep the user's descriptions word for word: hair, clothes, colors, props.

Save each image as a local file, show it to the user, and load it with `ref <n> <file>` only after the user approves it. If you cannot generate images, say so and ask the user for the files.

## Example steps file

```js
const L = komikku.layout();
L.template("manga-5");
L.split(3, "x", { slant: 0.05 });
L.shots(["Wide establishing shot of ...", "Medium shot of <Subject 1> ...", "...", "...", "...", "..."]);
keep("layout.png", L.preview());
return L.describe();
```

```js
const C = komikku.compose();
await C.addText(1, "caption", "That night, the city felt different...");
await C.addText(3, "speech", "Hello? Is someone there?", { speaker: [0.5, 0.3] });
await C.addText(4, "sfx", "MEOW");
keep("lettered.jpg", await C.render());
return C.describe().texts;
```
