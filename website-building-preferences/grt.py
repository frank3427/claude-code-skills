#!/usr/bin/env python3
"""
Golden Ratio Typography (GRT) token generator, calibrated to grtcalculator.com.

v2 (2026-10-23). v1 approximated line heights with an invented blend and ran 4-8% tight on
headings; v2 uses the published equation (grtcalculator.com/math/) and is checked against the
calculator's own output with --self-test.

  Typographic scale     f·φ², f·φ^1.5, f·φ, f·√φ, f, f/√φ   (the calculator's six sizes)
  Line height           h = f · [ (3 − φ) + (2φ − 3) · w / (34 f) + c ]
  x-height correction   c = (x − (φ − 1)) / φ,  x = x-height ÷ CAP height (not ÷ em!)
  Spacing               h·φ, h, h/φ, h/φ², h/φ³, h/φ⁴, each rounded from the previous step

Usage
  grt.py --font-size 18 --content-width 680 --font-file src/fonts/Body.ttf --output src/css/grt.css
  grt.py -f 18 -w 680 --x-ratio 0.72               # x-height ÷ cap height, if you know it
  grt.py --measure src/fonts/Body.ttf               # print a font's x-height ÷ cap height
  grt.py --self-test                                # compare against stored calculator results

Without --font-file or --x-ratio no x-height correction is applied (c = 0), which is the
calculator's answer for a font whose x-height is exactly a golden section of its cap height.

Output is rem (16px root) so readers' browser font settings are respected. It contains:
  static tokens   --grt-scale-1..6 / --grt-lh-1..6 (body = 1), --grt-h1..h6-size/-lh,
                  --grt-space-3xs..xxl, --grt-content-width, plus unitless --grt-lh-ratio-*
  fluid tokens    --grt-step--1..5 and --grt-step-lh--1..5: Utopia-style clamp() that reaches
                  the GRT values at --max-viewport and scales down to --min-font-size at
                  --min-viewport (steps 1-4 land exactly on h4, h3, h2, h1)
"""

import argparse
import math
import struct
import sys
from pathlib import Path

PHI = (1 + math.sqrt(5)) / 2
SQRT_PHI = math.sqrt(PHI)
WIDTH_FACTOR = 34  # GRT's constant width factor (grtcalculator.com/math/)
ROOT_PX = 16


def rnd(n: float) -> int:
    """Round half up, like the calculator (PHP round), not Python's banker's rounding."""
    return int(math.floor(n + 0.5))


# ── Font metrics ────────────────────────────────────────────────────────────────

def measure_x_ratio(path: str) -> float:
    """x-height ÷ cap height from a TTF/OTF's OS/2 table (version 2+). No dependencies."""
    data = Path(path).read_bytes()
    if data[:4] == b"wOF2":
        sys.exit(f"{path} is WOFF2 (compressed). Point --font-file at the .ttf/.otf instead, "
                 "or pass --x-ratio.")
    if data[:4] == b"wOFF":
        sys.exit(f"{path} is WOFF. Point --font-file at the .ttf/.otf instead, or pass --x-ratio.")
    num_tables = struct.unpack(">H", data[4:6])[0]
    tables = {}
    for i in range(num_tables):
        tag, _cs, off, ln = struct.unpack(">4sIII", data[12 + 16 * i: 28 + 16 * i])
        tables[tag] = (off, ln)
    if b"OS/2" not in tables:
        sys.exit(f"{path} has no OS/2 table. Pass --x-ratio instead.")
    off = tables[b"OS/2"][0]
    version = struct.unpack(">H", data[off:off + 2])[0]
    if version < 2:
        sys.exit(f"{path} has OS/2 version {version}, which carries no x-height. Pass --x-ratio.")
    x_height, cap_height = struct.unpack(">hh", data[off + 86: off + 90])
    if x_height <= 0 or cap_height <= 0:
        sys.exit(f"{path} reports x-height {x_height} / cap height {cap_height}. Pass --x-ratio.")
    return x_height / cap_height


# ── GRT math ────────────────────────────────────────────────────────────────────

def correction(x_ratio):
    return 0.0 if x_ratio is None else (x_ratio - (PHI - 1)) / PHI


def line_height(size: float, width: float, x_ratio=None) -> float:
    """Unrounded GRT line height in px."""
    q = (3 - PHI) + (2 * PHI - 3) * width / (size * WIDTH_FACTOR) + correction(x_ratio)
    return size * q


def calculate(font_size: float, content_width: float, x_ratio=None) -> dict:
    f, w = font_size, content_width
    # The calculator's six sizes, largest first; index 4 is the body.
    calc_sizes = [f * PHI ** 2, f * PHI ** 1.5, f * PHI, f * SQRT_PHI, f, f / SQRT_PHI]
    body_lh = rnd(line_height(f, w, x_ratio))

    # Spacing: chained rounding from the rounded body line height, as the calculator does.
    down = [body_lh]
    for _ in range(4):
        down.append(rnd(down[-1] / PHI))          # h/φ, h/φ², h/φ³, h/φ⁴
    up = [rnd(body_lh * PHI)]
    for _ in range(2):
        up.append(rnd(up[-1] * PHI))              # hφ, hφ², hφ³
    spacing = {
        "3xs": down[4], "2xs": down[3], "xs": down[2], "sm": down[1], "md": body_lh,
        "lg": up[0], "xl": up[1], "xxl": up[2],
    }

    # Display scale kept from v1's token names: scale-n = f·φ^(n−1), scale-1 = body.
    scale = [f * PHI ** i for i in range(6)]
    headings = {"h1": f * PHI ** 2, "h2": f * PHI ** 1.5, "h3": f * PHI,
                "h4": f * SQRT_PHI, "h5": f * PHI ** 0.25, "h6": f}

    # The calculator rounds each size to whole px first, then computes its line height.
    def lh(size):
        return rnd(line_height(rnd(size), w, x_ratio))

    return {
        "font_size": f, "content_width": w, "x_ratio": x_ratio,
        "calc_table": [(rnd(s), lh(s)) for s in calc_sizes],  # px, as the calculator shows
        "body_lh": body_lh,
        "scale": [(rnd(s), lh(s)) for s in scale],
        "headings": {k: (rnd(s), lh(s)) for k, s in headings.items()},
        "spacing": spacing,
    }


# ── Fluid (Utopia-style) steps ──────────────────────────────────────────────────

def clamp(min_px, max_px, min_vw, max_vw):
    if abs(max_px - min_px) < 0.01:
        return rem(max_px)
    slope = (max_px - min_px) / (max_vw - min_vw)
    intercept = min_px - slope * min_vw
    lo, hi = sorted((min_px, max_px))
    return f"clamp({rem(lo)}, {intercept / ROOT_PX:.4f}rem + {slope * 100:.4f}vw, {rem(hi)})"


def fluid(grt, min_font, min_vw, max_vw, min_ratio, gutter, x_ratio):
    """Steps -1..5. Max end is GRT (ratio √φ from the body); min end uses min_font and min_ratio,
    with its line height computed by GRT at the narrow column (min viewport − 2 gutters)."""
    f, w = grt["font_size"], grt["content_width"]
    min_w = max(min_vw - 2 * gutter, 200)
    steps = {}
    for n in range(-1, 6):
        max_size = f * SQRT_PHI ** n
        min_size = min_font * min_ratio ** n
        # Line heights from whole-px sizes, as the calculator computes them.
        max_lh = rnd(line_height(rnd(max_size), w, x_ratio))
        min_lh = rnd(line_height(rnd(min_size), min_w, x_ratio))
        steps[n] = (clamp(min_size, max_size, min_vw, max_vw), clamp(min_lh, max_lh, min_vw, max_vw),
                    (min_size, max_size, min_lh, max_lh))
    return steps


# ── Output ──────────────────────────────────────────────────────────────────────

def rem(px: float) -> str:
    v = round(px / ROOT_PX, 4)
    return f"{v:g}rem"


def generate_css(grt, steps, prefix="grt-", target="body", applied=True):
    p = prefix
    f, w = grt["font_size"], grt["content_width"]
    x = grt["x_ratio"]
    xdesc = f"x-height/cap {x:.4f}" if x is not None else "no x-height correction"
    out = [
        "/* ============================================================",
        "   Golden Ratio Typography (GENERATED by grt.py v2, do not hand-edit)",
        f"   Base {f:g}px  |  Content width {w:g}px  |  {xdesc}",
        "   Calibrated to grtcalculator.com; regenerate when size, column (>40px) or face changes.",
        "   ============================================================ */",
        "",
        ":root {",
        "  /* Typographic scale: scale-1 is the body, each step ×φ */",
    ]
    for i, (s, lh) in enumerate(grt["scale"], 1):
        out.append(f"  --{p}scale-{i}: {rem(s)};  /* {s:.2f}px */")
    out.append("")
    for i, (s, lh) in enumerate(grt["scale"], 1):
        out.append(f"  --{p}lh-{i}: {rem(lh)};  /* {lh}px */")
    for i, (s, lh) in enumerate(grt["scale"], 1):
        out.append(f"  --{p}lh-ratio-{i}: {lh / s:.4f};")
    out.append("")
    out.append("  /* Headings (calculator scale: φ², φ^1.5, φ, √φ; h5 φ^0.25; h6 body) */")
    for tag, (s, lh) in grt["headings"].items():
        out.append(f"  --{p}{tag}-size: {rem(s)};  /* {s:.2f}px */")
        out.append(f"  --{p}{tag}-lh: {rem(lh)};  /* {lh}px, ratio {lh / s:.4f} */")
    out.append("")
    out.append("  /* Spacing from the body line height */")
    for k, v in grt["spacing"].items():
        out.append(f"  --{p}space-{k}: {rem(v)};  /* {v}px */")
    out.append("")
    out.append(f"  --{p}content-width: {rem(w)};  /* {w:g}px */")
    if steps:
        out.append("")
        out.append("  /* Fluid steps: step-0 body, 1-4 = h4..h1 at the max viewport */")
        for n, (size, lh, (mn, mx, mnl, mxl)) in steps.items():
            out.append(f"  --{p}step-{n}: {size};  /* {mn:.1f} -> {mx:.1f}px */")
            out.append(f"  --{p}step-lh-{n}: {lh};  /* {mnl} -> {mxl}px */")
    out.append("}")

    if applied:
        sel = target
        fl = bool(steps)
        def size(n, tag):
            return f"var(--{p}step-{n})" if fl else f"var(--{p}{tag}-size)"
        def lhv(n, tag):
            return f"var(--{p}step-lh-{n})" if fl else f"var(--{p}{tag}-lh)"
        out += [
            "",
            "/* Applied defaults (override in style.css; no borders or colours here) */",
            f"{sel} {{ font-size: {size(0, 'h6')}; line-height: {lhv(0, 'h6')}; }}",
            f"{sel} p {{ margin-block: 0 var(--{p}space-md); }}",
        ]
        for tag, n in (("h1", 4), ("h2", 3), ("h3", 2), ("h4", 1)):
            out.append(f"{sel} {tag} {{ font-size: {size(n, tag)}; line-height: {lhv(n, tag)}; "
                       f"margin-block: var(--{p}space-lg) var(--{p}space-sm); }}")
        if fl:
            out.append(f"{sel} small, {sel} figcaption {{ font-size: var(--{p}step--1); "
                       f"line-height: var(--{p}step-lh--1); }}")
    return "\n".join(out) + "\n"


def print_summary(grt, steps):
    print(f"\nGRT  base {grt['font_size']:g}px  width {grt['content_width']:g}px  "
          + (f"x/cap {grt['x_ratio']:.4f}" if grt['x_ratio'] is not None else "no x-height correction"))
    print("  calculator table (size / line height):")
    for s, lh in grt["calc_table"]:
        print(f"    {s:>4}px / {lh}px")
    print("  spacing: " + "  ".join(f"{k} {v}" for k, v in grt["spacing"].items()))
    if steps:
        print("  fluid steps (min -> max px):")
        for n, (_, _, (mn, mx, mnl, mxl)) in steps.items():
            print(f"    step {n:>2}: {mn:5.1f} -> {mx:5.1f}   lh {mnl} -> {mxl}")
    print()


# ── Self-test against stored calculator output ──────────────────────────────────

def self_test(fixture_path: Path) -> int:
    import json
    cases = json.loads(fixture_path.read_text())
    fails = 0
    for c in cases:
        g = calculate(c["size"], c["width"], c["x_ratio"])
        want_table = [tuple(r) for r in c["scale"]]
        want_space = c["spacing"]
        got_space = [g["spacing"][k] for k in ("lg", "md", "sm", "xs", "2xs", "3xs")]
        if g["calc_table"] != want_table or got_space != want_space:
            fails += 1
            print(f"MISMATCH {c['font']} {c['size']}/{c['width']}: got {g['calc_table']} {got_space}, "
                  f"calculator {want_table} {want_space}")
    print(f"{len(cases) - fails}/{len(cases)} calculator cases match exactly")
    return 1 if fails else 0


def main():
    ap = argparse.ArgumentParser(description="Golden Ratio Typography tokens, calibrated to grtcalculator.com",
                                 formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument("--font-size", "-f", type=float, help="Body size in px at the max viewport")
    ap.add_argument("--content-width", "-w", type=float, default=680, help="Readable column width in px")
    ap.add_argument("--font-file", help="Body font .ttf/.otf; x-height ÷ cap height is read from it")
    ap.add_argument("--x-ratio", type=float, help="x-height ÷ cap height (typically 0.62-0.80)")
    ap.add_argument("--x-height", type=float, help=argparse.SUPPRESS)  # v1 flag, refused below
    ap.add_argument("--min-font-size", type=float, help="Body size at the min viewport (default: base − 1)")
    ap.add_argument("--min-viewport", type=float, default=360)
    ap.add_argument("--max-viewport", type=float, default=1240)
    ap.add_argument("--min-ratio", type=float, default=1.2, help="Type ratio at the min viewport")
    ap.add_argument("--gutter", type=float, default=16, help="Side gutter at the min viewport, px")
    ap.add_argument("--no-fluid", action="store_true", help="Static tokens only")
    ap.add_argument("--no-applied", action="store_true", help="Tokens only, no element defaults")
    ap.add_argument("--prefix", default="grt-")
    ap.add_argument("--target", default="body")
    ap.add_argument("--output", "-o")
    ap.add_argument("--css-only", action="store_true")
    ap.add_argument("--measure", metavar="FONT", help="Print a font's x-height ÷ cap height and exit")
    ap.add_argument("--self-test", action="store_true", help="Check against stored calculator results")
    a = ap.parse_args()

    here = Path(__file__).resolve().parent
    if a.self_test:
        sys.exit(self_test(here / "grt_calculator_fixtures.json"))
    if a.measure:
        print(f"{measure_x_ratio(a.measure):.4f}")
        return
    if a.font_size is None:
        ap.error("--font-size is required")

    x_ratio = a.x_ratio
    if a.x_height is not None:
        sys.exit("--x-height was v1's flag and took x-height ÷ em (e.g. Georgia 0.49). GRT's correction "
                 "needs x-height ÷ CAP height (Georgia ≈ 0.70). Use --font-file <font.ttf> or --x-ratio.")
    if a.font_file:
        x_ratio = measure_x_ratio(a.font_file)
    if x_ratio is not None and not 0.55 <= x_ratio <= 0.9:
        sys.exit(f"x-ratio {x_ratio:.3f} looks wrong: it is x-height ÷ cap height, usually 0.62-0.80.")

    grt = calculate(a.font_size, a.content_width, x_ratio)
    steps = None if a.no_fluid else fluid(grt, a.min_font_size or a.font_size - 1, a.min_viewport,
                                           a.max_viewport, a.min_ratio, a.gutter, x_ratio)
    css = generate_css(grt, steps, a.prefix, a.target, not a.no_applied)
    if not a.css_only:
        print_summary(grt, steps)
    if a.output:
        Path(a.output).parent.mkdir(parents=True, exist_ok=True)
        Path(a.output).write_text(css, encoding="utf-8")
        print(f"wrote {a.output}")
    elif a.css_only:
        print(css)


if __name__ == "__main__":
    main()
