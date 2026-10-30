import json
import math

import numpy as np
import torch
from PIL import Image, ImageDraw, ImageOps
from typing_extensions import override

import comfy.utils
import folder_paths
from comfy_api.latest import ComfyExtension, io, ui

WEB_DIRECTORY = "./web"

# Panel rects are normalized to the page (0..1). Page width/height only set the aspect ratio; margin and gutter are in the same units.
DEFAULT_LAYOUT = {
    "page": {"name": "Manga B5", "width": 182, "height": 257},
    "margin": 10,
    "gutter": 4,
    "direction": "rtl",
    "preset": None,
    "panels": [],
}


# Page editor state of Komikku Page Compose. Framing is per panel (zoom over the cover scale, dx/dy in fractions of the panel box);
# overlays and the lettering layer are files the editor uploads to the input folder.
DEFAULT_COMPOSITION = {"panels": [], "overlays": [], "texts": [], "lettering": None}


@io.comfytype(io_type="KOMIKKU_PAGE_LAYOUT")
class PageLayout(io.ComfyTypeIO):
    Type = str

    class Input(io.WidgetInput):
        pass


@io.comfytype(io_type="KOMIKKU_PAGE_COMPOSITION")
class PageComposition(io.ComfyTypeI):
    Type = str

    class Input(io.WidgetInput):
        pass


def _assist_clip_input():
    # Only the page editors read this link (they run the loader wired here through TextGenerate); it is lazy and never requested,
    # so the text model is not loaded when the workflow runs.
    return io.Clip.Input("assist_clip", optional=True, lazy=True,
                         tooltip="Text model for the editor's prompt and dialogue assist. Wire a CLIP Loader whose model can generate text, e.g. the MOSS-Image Qwen3.5-9B encoder.")


def _timestamp(seconds: float) -> str:
    minutes, seconds = divmod(seconds, 60)
    return f"{int(minutes):02d}:{seconds:06.3f}"


def _panel_size(aspect: float, megapixels: float) -> tuple[int, int]:
    w = math.sqrt(megapixels * 1024 * 1024 * aspect)
    return max(16, round(w / 16) * 16), max(16, round(w / aspect / 16) * 16)


def _polygon_mask(points, x0, y0, w, h):
    # Drawn at 4x and box-filtered down so slanted edges stay smooth.
    img = Image.new("L", (w * 4, h * 4), 0)
    ImageDraw.Draw(img).polygon([((x - x0) * 4, (y - y0) * 4) for x, y in points], fill=255)
    return torch.from_numpy(np.asarray(img.resize((w, h), Image.BOX), dtype=np.float32) / 255.0)


def _framed(image, w, h, framing):
    # Same placement as the page editor: cover scale times zoom, centered, shifted by dx/dy; uncovered area stays white.
    ih, iw = image.shape[0], image.shape[1]
    s = max(w / iw, h / ih) * framing.get("zoom", 1.0)
    left = (w - iw * s) / 2 + framing.get("dx", 0.0) * w
    top = (h - ih * s) / 2 + framing.get("dy", 0.0) * h
    out = torch.ones((h, w, 3), dtype=image.dtype, device=image.device)
    x0, y0, x1, y1 = max(0, round(left)), max(0, round(top)), min(w, round(left + iw * s)), min(h, round(top + ih * s))
    if x1 <= x0 or y1 <= y0:
        return out
    sx0, sy0 = int((x0 - left) / s), int((y0 - top) / s)
    sx1, sy1 = min(iw, max(sx0 + 1, math.ceil((x1 - left) / s))), min(ih, max(sy0 + 1, math.ceil((y1 - top) / s)))
    crop = image[sy0:sy1, sx0:sx1].movedim(-1, 0)[None]
    out[y0:y1, x0:x1] = comfy.utils.common_upscale(crop, x1 - x0, y1 - y0, "area" if s < 1 else "bilinear", "disabled")[0].movedim(0, -1)
    return out


def _load_rgba(name):
    img = ImageOps.exif_transpose(Image.open(folder_paths.get_annotated_filepath(name))).convert("RGBA")
    return torch.from_numpy(np.asarray(img, dtype=np.float32) / 255.0)


def _paste_rgba(target, rgba, x, y, w, h, opacity):
    # Alpha-composites rgba, scaled to w x h, onto target at (x, y); the part outside target is dropped.
    if w <= 0 or h <= 0:
        return
    if rgba.shape[0] != h or rgba.shape[1] != w:
        rgba = comfy.utils.common_upscale(rgba.movedim(-1, 0)[None], w, h, "bilinear", "disabled")[0].movedim(0, -1)
    tx0, ty0, tx1, ty1 = max(0, x), max(0, y), min(target.shape[1], x + w), min(target.shape[0], y + h)
    if tx1 <= tx0 or ty1 <= ty0:
        return
    part = rgba[ty0 - y:ty1 - y, tx0 - x:tx1 - x]
    target[ty0:ty1, tx0:tx1] = torch.lerp(target[ty0:ty1, tx0:tx1], part[..., :3], part[..., 3:] * opacity)


class KomikkuPageLayout(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="KomikkuPageLayout",
            display_name="Komikku Page & Shots",
            category="Minimax-H3-Komikku",
            description="Page layout editor that builds a MiniMax H3 full-reference prompt with one hard-cut shot per manga panel, in panel number order. The duration is split between shots by each panel's length weight.",
            inputs=[
                PageLayout.Input("layout", socketless=True, default=json.dumps(DEFAULT_LAYOUT),
                                 tooltip="Page layout: panel rects, their order and one shot prompt per panel."),
                io.Float.Input("duration", default=10.0, min=1.0, max=150.0, step=0.5, tooltip="Video length in seconds. Use the same value that drives the H3 length."),
                io.String.Input("subjects", multiline=True,
                                default="<Subject 1> is the main character whose appearance, hairstyle, clothing and colors are defined by <Picture 1>."),
                io.String.Input("style", multiline=True,
                                default="2D anime style with clean linework, cel shading and strong silhouettes."),
                io.String.Input("soundscape", multiline=True, default="Ambient sound that matches each shot."),
                io.String.Input("music", multiline=True, default="Cinematic background score that follows the action."),
                io.Float.Input("panel_megapixels", default=1.0, min=0.1, max=16.0, step=0.05, tooltip="Pixel area used to size each panel from its aspect ratio on the page."),
                _assist_clip_input(),
            ],
            outputs=[
                io.String.Output(display_name="prompt"),
                io.Int.Output(display_name="panel_width", is_output_list=True),
                io.Int.Output(display_name="panel_height", is_output_list=True),
                PageLayout.Output(display_name="layout"),
            ],
        )

    @classmethod
    def check_lazy_status(cls, **kwargs):
        return []

    @classmethod
    def execute(cls, layout, duration, subjects, style, soundscape, music, panel_megapixels, assist_clip=None) -> io.NodeOutput:
        layout = json.loads(layout)
        panels = layout["panels"]
        if not panels:
            raise ValueError("The page layout has no panels. Open the page editor on Komikku Page & Shots and design the page.")
        count = len(panels)
        shot_tags = ", ".join(f"[Shot {i}]" for i in range(1, count + 1))
        # Each panel's weight is its share of the duration; layouts saved before weights existed split evenly.
        weights = [p.get("weight", 1.0) for p in panels]
        total = sum(weights)
        shots = []
        start = 0.0
        for i, panel in enumerate(panels, start=1):
            text = panel["prompt"].strip()
            if i == 1:
                shots.append(f"[Shot 1] {text}")
            else:
                shots.append(f"[Shot {i}] At {_timestamp(duration * start / total)}, the camera cuts to {text}")
            start += weights[i - 1]
        shots_text = "\n".join(shots)

        prompt = f"""subject_definitions:
{subjects.strip()}

summary:
[reference generation] A {count}-shot scene. Each shot is a clearly different, stable camera setup that reads as a single comic panel. Hard cuts only, no transitions.

retention_analysis:
All subjects defined above (appear in {shot_tags}): fully_preserved - face, hair, outfit and color palette stay identical in every shot.

detailed_description:
The target video is in {style.strip()} Every shot holds a stable, readable composition with limited camera motion.
{shots_text}

overall_soundscape:
{soundscape.strip()}

non_diegetic_music:
{music.strip()}"""
        page_w, page_h = layout["page"]["width"], layout["page"]["height"]
        sizes = [_panel_size(p["w"] * page_w / (p["h"] * page_h), panel_megapixels) for p in panels]
        return io.NodeOutput(prompt, [w for w, _ in sizes], [h for _, h in sizes], json.dumps(layout))


class KomikkuPageCompose(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="KomikkuPageCompose",
            display_name="Komikku Page Compose",
            category="Minimax-H3-Komikku",
            description="Composes the page from Komikku Page & Shots in panel number order. The page editor frames each panel image, adds imported RGB/RGBA images over the panels, and letters the page with speech bubbles and text.",
            is_input_list=True,
            inputs=[
                io.Image.Input("panels", tooltip="One image per panel, in shot order. Missing panels stay blank, extra images are ignored."),
                PageLayout.Input("layout", force_input=True),
                io.Int.Input("page_width", default=2480, min=256, max=16384, step=16, tooltip="Page width in pixels; the height follows the page format."),
                io.Int.Input("border", default=6, min=0, max=64, tooltip="Black panel border in pixels, drawn inside each panel."),
                PageComposition.Input("composition", socketless=True, default=json.dumps(DEFAULT_COMPOSITION),
                                      tooltip="Edited in the page editor: image framing per panel, imported images and lettering."),
                _assist_clip_input(),
            ],
            outputs=[io.Image.Output(display_name="page")],
        )

    @classmethod
    def check_lazy_status(cls, **kwargs):
        return []

    @classmethod
    def execute(cls, panels, layout, page_width, border, composition, assist_clip=None) -> io.NodeOutput:
        layout, comp = json.loads(layout[0]), json.loads(composition[0])
        page_width, border = page_width[0], border[0]
        page_height = round(page_width * layout["page"]["height"] / layout["page"]["width"])
        images = [img for batch in panels for img in batch]
        page = torch.ones((page_height, page_width, 3), dtype=images[0].dtype, device=images[0].device)
        for i, (panel, image) in enumerate(zip(layout["panels"], images)):
            x0, y0 = round(panel["x"] * page_width), round(panel["y"] * page_height)
            x1, y1 = round((panel["x"] + panel["w"]) * page_width), round((panel["y"] + panel["h"]) * page_height)
            w, h = x1 - x0, y1 - y0
            if w <= 0 or h <= 0:
                continue
            framing = comp["panels"][i] if i < len(comp["panels"]) else {}
            content = _framed(image[..., :3], w, h, framing)
            for overlay in comp["overlays"]:
                if overlay["panel"] == i:
                    _paste_rgba(content, _load_rgba(overlay["image"]).to(content), round(overlay["x"] * page_width) - x0, round(overlay["y"] * page_height) - y0,
                                round(overlay["w"] * page_width), round(overlay["h"] * page_height), overlay.get("opacity", 1.0))
            if "polygon" in panel:
                mask = _polygon_mask([(x * page_width, y * page_height) for x, y in panel["polygon"]], x0, y0, w, h).to(page)
            else:
                mask = torch.ones((h, w), dtype=page.dtype, device=page.device)
            inner = mask
            if border:
                inner = 1 - torch.nn.functional.max_pool2d(torch.nn.functional.pad(1 - mask[None, None], (border,) * 4, value=1.0), 2 * border + 1, stride=1)[0, 0]
            page[y0:y1, x0:x1] = torch.lerp(page[y0:y1, x0:x1] * (1 - mask[..., None]), content, inner[..., None])
        if comp.get("lettering"):
            _paste_rgba(page, _load_rgba(comp["lettering"]).to(page), 0, 0, page_width, page_height, 1.0)
        page = page[None]
        previews = [r for img in images for r in ui.ImageSaveHelper.save_images([img[..., :3]], "komikku_panel", io.FolderType.temp, None)]
        return io.NodeOutput(page, ui={"komikku_page": ui.ImageSaveHelper.save_images(page, "komikku_page", io.FolderType.temp, None), "komikku_panels": previews,
                                       "komikku_layout": [json.dumps(layout)]})


class KomikkuFitFrame(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="KomikkuFitFrame",
            display_name="Komikku Fit Frame",
            category="Minimax-H3-Komikku",
            description="Center-crops a shot frame toward its panel's aspect ratio so the reframe model never has to invent more than max_extend times the frame. "
                        "Very wide or very tall panels made from a frame of the opposite shape otherwise come back with mirrored or repeated content.",
            inputs=[
                io.Image.Input("image"),
                io.Int.Input("panel_width", min=1, max=16384, force_input=True),
                io.Int.Input("panel_height", min=1, max=16384, force_input=True),
                io.Float.Input("max_extend", default=2.0, min=1.0, max=8.0, step=0.05,
                               tooltip="Largest panel/frame aspect ratio left for the reframe model to fill. 1.0 crops the frame to the panel shape."),
            ],
            outputs=[io.Image.Output()],
        )

    @classmethod
    def execute(cls, image, panel_width, panel_height, max_extend) -> io.NodeOutput:
        h, w = image.shape[1:3]
        ratio = (panel_width / panel_height) / (w / h)
        if ratio > max_extend:
            crop_h = round(h * max_extend / ratio)
            top = (h - crop_h) // 2
            image = image[:, top:top + crop_h]
        elif ratio < 1 / max_extend:
            crop_w = round(w * ratio * max_extend)
            left = (w - crop_w) // 2
            image = image[:, :, left:left + crop_w]
        return io.NodeOutput(image)


class KomikkuShotFrames(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="KomikkuShotFrames",
            display_name="Komikku Shot Frames",
            category="Minimax-H3-Komikku",
            description="Finds the hard cuts of the multishot video and returns the middle frame of each shot, one per panel of the layout. "
                        "The cuts are the largest frame-to-frame changes, so it always returns as many frames as the page has panels.",
            inputs=[
                io.Image.Input("video", tooltip="Decoded frames of the multishot video."),
                PageLayout.Input("layout", force_input=True),
                io.Int.Input("min_shot_frames", default=8, min=1, max=240, tooltip="Shortest shot in frames; cuts closer than this are ignored."),
            ],
            outputs=[io.Image.Output(display_name="frames")],
        )

    @classmethod
    def execute(cls, video, layout, min_shot_frames) -> io.NodeOutput:
        count = len(json.loads(layout)["panels"])
        small = torch.nn.functional.interpolate(video.movedim(-1, 1), size=(64, 64), mode="area")
        diff = (small[1:] - small[:-1]).abs().mean(dim=(1, 2, 3)).tolist()
        cuts = []
        for i in sorted(range(len(diff)), key=lambda i: diff[i], reverse=True):
            cut = i + 1
            if len(cuts) == count - 1:
                break
            if min(cut, len(video) - cut) >= min_shot_frames and all(abs(cut - c) >= min_shot_frames for c in cuts):
                cuts.append(cut)
        bounds = [0] + sorted(cuts) + [len(video)]
        return io.NodeOutput(video[[(a + b) // 2 for a, b in zip(bounds, bounds[1:])]])


class KomikkuExtension(ComfyExtension):
    @override
    async def get_node_list(self) -> list[type[io.ComfyNode]]:
        return [KomikkuPageLayout, KomikkuShotFrames, KomikkuFitFrame, KomikkuPageCompose]


async def comfy_entrypoint() -> KomikkuExtension:
    return KomikkuExtension()
