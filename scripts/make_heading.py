"""Draw a section-heading SVG in the profile's own typeface.

READMEs strip inline CSS, so headings can't be styled text in Markdown --
they're rendered as tiny SVGs instead: a lowercase mono label with a
hairline rule running to the right edge. (The alt text on the <img> is
what carries the word to screen readers -- an image heading has no
anchor link, so GitHub's own README outline goes empty for it.)

Usage:
    python make_heading.py "about" hd-about.svg [--width 460]
"""
import base64
import io
import sys
from pathlib import Path

from fontTools import subset
from fontTools.ttLib import TTFont

FONT_PATH = Path(__file__).parent / "fonts" / "JetBrainsMono-Regular.ttf"
FONT_SIZE_PX = 14
CHAR_ADVANCE_EM = 0.600
PAD_X = 2
HEIGHT = 24
RULE_GAP = 12  # space between the label and where the rule starts


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


def build_svg(label: str, width: int) -> str:
    text = label.lower()
    font_b64 = base64.b64encode(subset_font_bytes(FONT_PATH, text)).decode("ascii")

    label_width = len(text) * CHAR_ADVANCE_EM * FONT_SIZE_PX
    rule_x = PAD_X + label_width + RULE_GAP
    baseline = round(HEIGHT * 0.68, 2)
    rule_y = round(HEIGHT * 0.55, 2)

    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {HEIGHT}" width="{width}" height="{HEIGHT}">
<defs>
<style>
@font-face {{
  font-family: "HeadingMono";
  src: url(data:font/woff2;base64,{font_b64}) format("woff2");
}}
text {{
  font-family: "HeadingMono", monospace;
  font-size: {FONT_SIZE_PX}px;
  letter-spacing: 0.08em;
  fill: #15181c;
}}
line {{ stroke: #15181c; stroke-opacity: 0.35; }}
@media (prefers-color-scheme: dark) {{
  text {{ fill: #e8e6e1; }}
  line {{ stroke: #e8e6e1; stroke-opacity: 0.3; }}
}}
</style>
</defs>
<text x="{PAD_X}" y="{baseline}">{text}</text>
<line x1="{rule_x:.2f}" y1="{rule_y}" x2="{width - PAD_X}" y2="{rule_y}" stroke-width="1"/>
</svg>
"""


def main() -> None:
    if len(sys.argv) < 3:
        print("usage: make_heading.py <label> <output-svg> [--width N]", file=sys.stderr)
        raise SystemExit(1)
    label, dst = sys.argv[1], Path(sys.argv[2])
    width = 460
    if "--width" in sys.argv:
        width = int(sys.argv[sys.argv.index("--width") + 1])
    dst.write_text(build_svg(label, width), encoding="utf-8")
    print(f"wrote {dst}")


if __name__ == "__main__":
    main()
