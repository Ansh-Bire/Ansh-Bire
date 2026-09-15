"""Convert a photo into a self-typing ASCII portrait SVG.

Pipeline (see the "ASCII Portrait README Guide" this is based on, plus the
fixes documented in "A GitHub profile that generates itself"):
  1. rembg cuts the subject out; everything outside it is forced to pure
     white so it lands on the blank end of the character ramp.
  2. A bilateral filter smooths skin while keeping edges crisp.
  3. CLAHE (clip ~3.0) adds local contrast so a flatly-lit face doesn't
     collapse into one tone.
  4. A (v/255)^1.7 darkening curve keeps highlights but pushes shadows and
     mid-tones darker -- without it, fine features (glasses, brows, lips)
     wash out.
  5. The result is downsampled to a character grid and mapped onto a
     13-character ramp, quiet to loud: ' .`:-=+*cs#%@'.
  6. Each row types in via an SVG clipPath wipe (SMIL), staggered
     top-to-bottom, so the portrait prints once and freezes.

Usage:
    python make_portrait.py <input-image> <output-svg> [--cols N]
"""
import base64
import io
import sys
from pathlib import Path

import cv2
import numpy as np
from fontTools import subset
from fontTools.ttLib import TTFont
from PIL import Image
from rembg import remove

RAMP = " .`:-=+*cs#%@"  # quiet -> loud; leading space clears the background
FONT_PATH = Path(__file__).parent / "fonts" / "JetBrainsMono-Regular.ttf"

# JetBrains Mono is 600/1000 units -- an advance width of exactly 0.600em.
# Get this wrong and the character grid renders ~7% narrower on Windows
# (Consolas' fallback advance is ~0.55em), which is why the font is
# embedded rather than left to the viewer's default monospace.
FONT_SIZE_PX = 12.9
CHAR_W = round(FONT_SIZE_PX * 0.600, 2)  # 7.74
ROW_ASPECT = 0.48  # rows = cols * (h/w) * ROW_ASPECT
ROW_H = round(CHAR_W / ROW_ASPECT, 2)  # ~16.125px

ROW_DUR = 0.15  # seconds for one row's wipe-in
ROW_STAGGER = 0.09  # seconds between each row starting


def cutout_and_process(path: Path) -> np.ndarray:
    """Return a grayscale array (0=black .. 255=white) ready for ramp mapping."""
    rgba = remove(Image.open(path).convert("RGB"))
    rgba_arr = np.array(rgba)
    rgb, alpha = rgba_arr[..., :3], rgba_arr[..., 3:4] / 255.0
    white = np.full_like(rgb, 255)
    composited = (rgb * alpha + white * (1 - alpha)).astype(np.uint8)

    gray = cv2.cvtColor(composited, cv2.COLOR_RGB2GRAY)
    gray = cv2.bilateralFilter(gray, d=9, sigmaColor=75, sigmaSpace=75)

    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    gray = clahe.apply(gray)

    curved = (np.power(gray.astype(np.float64) / 255.0, 1.7) * 255.0)
    return np.clip(curved, 0, 255).astype(np.uint8)


def grid_from_gray(gray: np.ndarray, cols: int) -> list[str]:
    h, w = gray.shape
    rows = max(1, round(cols * (h / w) * ROW_ASPECT))
    small = cv2.resize(gray, (cols, rows), interpolation=cv2.INTER_AREA)

    ramp_len = len(RAMP)
    lines = []
    for y in range(rows):
        line = []
        for x in range(cols):
            brightness = int(small[y, x])  # 0 (dark) .. 255 (light)
            idx = min(int((255 - brightness) / 256 * ramp_len), ramp_len - 1)
            line.append(RAMP[idx])
        lines.append("".join(line))
    return lines


def subset_font_bytes(font_path: Path, characters: str) -> bytes:
    font = TTFont(str(font_path))
    options = subset.Options()
    options.flavor = "woff2"
    options.desubroutinize = True
    subsetter = subset.Subsetter(options=options)
    subsetter.populate(text=characters)
    subsetter.subset(font)
    buf = io.BytesIO()
    font.save(buf)
    return buf.getvalue()


def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def build_svg(lines: list[str]) -> str:
    cols = max(len(line) for line in lines)
    rows = len(lines)
    used_chars = "".join(sorted(set("".join(lines))))
    font_b64 = base64.b64encode(subset_font_bytes(FONT_PATH, used_chars)).decode("ascii")

    width = round(cols * CHAR_W)
    height = round(rows * ROW_H)
    row_width_px = cols * CHAR_W

    rows_svg = []
    for i, line in enumerate(lines):
        y_top = i * ROW_H
        baseline = round(y_top + ROW_H * 0.8, 2)
        begin = round(i * ROW_STAGGER, 3)
        rows_svg.append(f"""<clipPath id="rc{i}">
<rect x="0" y="{y_top:.2f}" width="0" height="{ROW_H:.2f}">
<animate attributeName="width" from="0" to="{row_width_px:.2f}" begin="{begin}s" dur="{ROW_DUR}s" fill="freeze"/>
</rect>
</clipPath>
<g clip-path="url(#rc{i})">
<text x="0" y="{baseline}" xml:space="preserve">{esc(line)}</text>
</g>
<rect class="cursor" y="{y_top:.2f}" width="{CHAR_W * 0.55:.2f}" height="{ROW_H:.2f}">
<animate attributeName="x" from="0" to="{row_width_px:.2f}" begin="{begin}s" dur="{ROW_DUR}s" fill="freeze"/>
<animate attributeName="opacity" from="1" to="0" begin="{begin + ROW_DUR}s" dur="0.12s" fill="freeze"/>
</rect>""")

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}">
<defs>
<style>
@font-face {{
  font-family: "PortraitMono";
  src: url(data:font/woff2;base64,{font_b64}) format("woff2");
}}
text {{
  font-family: "PortraitMono", monospace;
  font-size: {FONT_SIZE_PX}px;
  fill: #15181c;
  white-space: pre;
}}
.cursor {{ fill: #15181c; }}
@media (prefers-color-scheme: dark) {{
  text {{ fill: #e8e6e1; }}
  .cursor {{ fill: #e8e6e1; }}
}}
</style>
</defs>
<g>
{chr(10).join(rows_svg)}
</g>
</svg>
"""
    return svg


def main() -> None:
    if len(sys.argv) < 3:
        print("usage: make_portrait.py <input-image> <output-svg> [--cols N]", file=sys.stderr)
        raise SystemExit(1)

    src = Path(sys.argv[1])
    dst = Path(sys.argv[2])
    cols = 90
    if "--cols" in sys.argv:
        cols = int(sys.argv[sys.argv.index("--cols") + 1])

    gray = cutout_and_process(src)
    lines = grid_from_gray(gray, cols)
    dst.write_text(build_svg(lines), encoding="utf-8")
    print(f"wrote {dst} ({cols} cols x {len(lines)} rows)")


if __name__ == "__main__":
    main()
