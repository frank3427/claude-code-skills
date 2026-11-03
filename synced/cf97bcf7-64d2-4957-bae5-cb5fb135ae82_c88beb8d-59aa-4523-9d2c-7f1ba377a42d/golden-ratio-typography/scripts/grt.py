#!/usr/bin/env python3
"""
Golden Ratio Typography (GRT) Calculator
Generates CSS custom properties and type styles based on GRT principles.

Usage:
  python grt.py --font-size 16 --content-width 680
  python grt.py --font-size 18 --content-width 800 --format scss
  python grt.py --font-size 16 --content-width 680 --scan ./src
  python grt.py --font-size 16 --content-width 680 --inject index.html

References:
  https://grtcalculator.com/math/
  https://pearsonified.com/golden-ratio-typography/
"""

import argparse
import math
import os
import re
import sys
from pathlib import Path

PHI = (1 + math.sqrt(5)) / 2  # ≈ 1.618033988749895
PHI_SQRT = math.sqrt(PHI)      # ≈ 1.272019649514069


def round_half(n):
    """Round to nearest 0.5 for precise CSS values."""
    return round(n * 2) / 2


def calculate_grt(font_size: float, content_width: float, x_height_ratio: float = None):
    """
    Calculate the full Golden Ratio Typography system.

    The GRT system produces:
    - A 6-level typographic scale (font sizes)
    - Corresponding line heights for each scale level
    - Spacing units derived from the primary line height
    - Ideal content width (if not provided)

    Formulas (from grtcalculator.com/math/):
      φ = 1.618033988749895
      Typographic scale: f, f×φ, f×φ², f×φ³, f×φ⁴, f×φ⁵
      Base line height: h = f × φ
      Line height (width-adjusted): uses content width to fine-tune
      X-height correction: adjusts line height based on font metrics
      Spacing units: primary line height scaled by φ and 1/φ
    """

    # ── Typographic scale (6 levels) ──────────────────────────────────────────
    # Level 1 = body/base, levels 2–6 grow by φ each step
    scale = [font_size * (PHI ** i) for i in range(6)]

    # ── Line heights ──────────────────────────────────────────────────────────
    # Base formula: line_height = font_size × φ
    # Width-tuning: the GRT calculator uses a "constant width factor" (W=34)
    # to adjust line height based on content_width.
    # Adjusted ratio: q = (1/φ) × (φ + content_width/(W × font_size²))
    # This increases line height when lines are wider.
    W = 34  # GRT width constant

    def calc_line_height(fs, width=content_width):
        base_h = fs * PHI
        # Width adjustment term
        width_adj = width / (W * fs)
        # Blended line height ratio (harmonic between φ and width-adjusted value)
        q = (1 / PHI) * (PHI + width_adj)
        adjusted_h = fs * q
        # Blend: weight base formula heavily, let width nudge it
        h = (base_h + adjusted_h) / 2
        # X-height correction: if ratio provided, adjust
        if x_height_ratio:
            ideal_x = 1 / PHI  # ≈ 0.618
            correction = fs * (x_height_ratio - ideal_x)
            h += correction * 0.5
        return max(round(h), round(fs * 1.2))  # Never less than 1.2× font size

    line_heights = [calc_line_height(s) for s in scale]

    # ── Spacing units ─────────────────────────────────────────────────────────
    # Derived from the primary (body) line height:
    # xs = lh/φ², sm = lh/φ, md = lh, lg = lh×φ, xl = lh×φ², xxl = lh×φ³
    primary_lh = line_heights[0]
    spacing = {
        'xs':  round(primary_lh / PHI**2),
        'sm':  round(primary_lh / PHI),
        'md':  round(primary_lh),
        'lg':  round(primary_lh * PHI),
        'xl':  round(primary_lh * PHI**2),
        'xxl': round(primary_lh * PHI**3),
    }

    # ── Ideal content width ───────────────────────────────────────────────────
    # GRT principle: for a given font size and line height,
    # the ideal line holds ~66 characters (the "golden" CPL).
    # Approximated as: ideal_width ≈ font_size × 2.5 × PHI × 5
    ideal_width = round(font_size * PHI**2 * 10)

    # ── Heading mapping (practical web scale) ────────────────────────────────
    # GRT's full 6-level scale grows very fast. For practical web headings
    # we use half-phi steps (√φ ≈ 1.272) to keep h1 at ~2.6× the base:
    #   h1 = base × φ²        ≈ 2.618× (e.g. ~42px for 16px base)
    #   h2 = base × φ^1.5     ≈ 2.058× (e.g. ~33px)
    #   h3 = base × φ         ≈ 1.618× (e.g. ~26px)
    #   h4 = base × √φ        ≈ 1.272× (e.g. ~20px)
    #   h5 = base × φ^0.25    ≈ 1.128× (e.g. ~18px)
    #   h6 = base             = 1.0× (same as body)
    # The full mathematical scale (scale-1 … scale-6) is still exported as
    # CSS variables for display/hero text or design systems that need it.
    h_sizes = {
        'h1': font_size * PHI**2,                  # scale step 3
        'h2': font_size * PHI**1.5,                # half-step between 2 & 3
        'h3': font_size * PHI,                     # scale step 2
        'h4': font_size * PHI_SQRT,                # half-step between 1 & 2
        'h5': font_size * PHI**0.25,               # quarter-step
        'h6': font_size,                           # body size
    }
    h_line_heights = {tag: calc_line_height(size) for tag, size in h_sizes.items()}

    return {
        'font_size': font_size,
        'content_width': content_width,
        'ideal_width': ideal_width,
        'phi': PHI,
        'scale': scale,
        'line_heights': line_heights,
        'spacing': spacing,
        'headings': h_sizes,
        'heading_line_heights': h_line_heights,
        'primary_line_height': primary_lh,
    }


def format_value(v, unit='px', decimals=3):
    """Format a numeric value as a CSS value string."""
    rounded = round(v, decimals)
    if rounded == int(rounded):
        return f"{int(rounded)}{unit}"
    return f"{rounded}{unit}"


def generate_css(grt: dict, prefix: str = '', fmt: str = 'css', target: str = '.grt') -> str:
    """
    Generate CSS or SCSS from GRT data.

    - prefix: variable name prefix (e.g. 'grt-')
    - fmt: 'css' (custom properties) or 'scss' (SCSS variables)
    - target: CSS selector to scope styles to (default: '.grt')
    """
    fs = grt['font_size']
    lh = grt['primary_line_height']
    scale = grt['scale']
    lhs = grt['line_heights']
    sp = grt['spacing']
    h = grt['headings']
    hlh = grt['heading_line_heights']
    cw = grt['content_width']
    phi = grt['phi']

    p = prefix or 'grt-'  # Default variable prefix

    lines = []
    lines.append(f"/* ============================================================")
    lines.append(f"   Golden Ratio Typography")
    lines.append(f"   Base: {fs}px  |  Content width: {cw}px  |  φ = {phi:.10f}")
    lines.append(f"   Generated by the GRT Skill (grtcalculator.com)")
    lines.append(f"   ============================================================ */")
    lines.append("")

    if fmt == 'scss':
        # SCSS variables
        lines.append("// ── Typographic scale ───────────────────────────────────────────")
        lines.append(f"${p}scale-1:  {format_value(scale[0])};  // body / base")
        lines.append(f"${p}scale-2:  {format_value(scale[1])};  // 1 step  (×φ)")
        lines.append(f"${p}scale-3:  {format_value(scale[2])};  // 2 steps (×φ²)")
        lines.append(f"${p}scale-4:  {format_value(scale[3])};  // 3 steps (×φ³)")
        lines.append(f"${p}scale-5:  {format_value(scale[4])};  // 4 steps (×φ⁴)")
        lines.append(f"${p}scale-6:  {format_value(scale[5])};  // 5 steps (×φ⁵)")
        lines.append("")
        lines.append("// ── Line heights ────────────────────────────────────────────────")
        for i, (s, lh_val) in enumerate(zip(scale, lhs), 1):
            lines.append(f"${p}lh-{i}:     {format_value(lh_val)};  // for {format_value(s)} text")
        lines.append("")
        lines.append("// ── Spacing units ───────────────────────────────────────────────")
        for key, val in sp.items():
            lines.append(f"${p}space-{key}: {format_value(val)};")
        lines.append("")
        lines.append("// ── Content width ───────────────────────────────────────────────")
        lines.append(f"${p}content-width: {format_value(cw)};")
        lines.append(f"${p}ideal-width:   {format_value(grt['ideal_width'])};")
        lines.append("")
        lines.append("// ── Heading sizes ───────────────────────────────────────────────")
        for tag, size in h.items():
            lines.append(f"${p}{tag}-size: {format_value(size)};")
        lines.append("")
        lines.append("// ── Heading line heights ────────────────────────────────────────")
        for tag, lh_val in hlh.items():
            lines.append(f"${p}{tag}-lh:   {format_value(lh_val)};")

    else:
        # CSS custom properties
        lines.append(f":root {{")
        lines.append(f"  /* ── Typographic scale ─────────────────────────────────────── */")
        lines.append(f"  --{p}scale-1:  {format_value(scale[0])};  /* body / base */")
        lines.append(f"  --{p}scale-2:  {format_value(scale[1])};  /* 1 step  (×φ) */")
        lines.append(f"  --{p}scale-3:  {format_value(scale[2])};  /* 2 steps (×φ²) */")
        lines.append(f"  --{p}scale-4:  {format_value(scale[3])};  /* 3 steps (×φ³) */")
        lines.append(f"  --{p}scale-5:  {format_value(scale[4])};  /* 4 steps (×φ⁴) */")
        lines.append(f"  --{p}scale-6:  {format_value(scale[5])};  /* 5 steps (×φ⁵) */")
        lines.append(f"")
        lines.append(f"  /* ── Line heights ──────────────────────────────────────────── */")
        for i, (s, lh_val) in enumerate(zip(scale, lhs), 1):
            lines.append(f"  --{p}lh-{i}:     {format_value(lh_val)};  /* for {format_value(s)} text */")
        lines.append(f"")
        lines.append(f"  /* ── Spacing units ─────────────────────────────────────────── */")
        for key, val in sp.items():
            lines.append(f"  --{p}space-{key}: {format_value(val)};")
        lines.append(f"")
        lines.append(f"  /* ── Content width ─────────────────────────────────────────── */")
        lines.append(f"  --{p}content-width: {format_value(cw)};")
        lines.append(f"  --{p}ideal-width:   {format_value(grt['ideal_width'])};")
        lines.append(f"")
        lines.append(f"  /* ── Heading sizes ─────────────────────────────────────────── */")
        for tag, size in h.items():
            lines.append(f"  --{p}{tag}-size: {format_value(size)};")
        lines.append(f"")
        lines.append(f"  /* ── Heading line heights ──────────────────────────────────── */")
        for tag, lh_val in hlh.items():
            lines.append(f"  --{p}{tag}-lh:   {format_value(lh_val)};")
        lines.append(f"}}")

    # ── Applied styles block ─────────────────────────────────────────────────
    lines.append("")
    lines.append(f"/* ============================================================")
    lines.append(f"   Applied GRT Styles")
    lines.append(f"   Add class \"{target.lstrip('.')}\" to your root element, or adjust")
    lines.append(f"   the selector below to match your layout.")
    lines.append(f"   ============================================================ */")
    lines.append("")

    if fmt == 'scss':
        var = lambda name: f"${p}{name}"
    else:
        var = lambda name: f"var(--{p}{name})"

    body_sel = "body" if target in ("body", ":root") else f"{target}, {target} body"
    lines.append(f"{body_sel} {{")
    lines.append(f"  font-size:   {format_value(fs)};")
    lines.append(f"  line-height: {var('lh-1')};")
    lines.append(f"}}")
    lines.append("")
    lines.append(f"/* Paragraphs and readable content */")
    lines.append(f"{target} p,")
    lines.append(f"{target} li,")
    lines.append(f"{target} blockquote {{")
    lines.append(f"  max-width:   {var('content-width')};")
    lines.append(f"  font-size:   {var('scale-1')};")
    lines.append(f"  line-height: {var('lh-1')};")
    lines.append(f"  margin-bottom: {var('space-md')};")
    lines.append(f"}}")
    lines.append("")
    lines.append(f"/* Headings */")
    for tag, size in h.items():
        lh_val = hlh[tag]
        mt = sp['lg'] if tag in ('h1', 'h2') else sp['md']
        mb = sp['sm']
        if fmt == 'scss':
            lines.append(f"{target} {tag} {{")
            lines.append(f"  font-size:   {format_value(size)};")
            lines.append(f"  line-height: {format_value(lh_val)};")
            lines.append(f"  margin-top:    {format_value(mt)};")
            lines.append(f"  margin-bottom: {format_value(mb)};")
            lines.append(f"}}")
        else:
            lines.append(f"{target} {tag} {{")
            lines.append(f"  font-size:   {var(f'{tag}-size')};")
            lines.append(f"  line-height: {var(f'{tag}-lh')};")
            lines.append(f"  margin-top:    {format_value(mt)};")
            lines.append(f"  margin-bottom: {format_value(mb)};")
            lines.append(f"}}")
        lines.append("")

    lines.append(f"/* Small text / captions */")
    lines.append(f"{target} small,")
    lines.append(f"{target} caption,")
    lines.append(f"{target} figcaption {{")
    lines.append(f"  font-size:   {format_value(round(fs / PHI))};")
    lines.append(f"  line-height: {var('lh-1')};")
    lines.append(f"}}")
    lines.append("")
    lines.append(f"/* Blockquote */")
    lines.append(f"{target} blockquote {{")
    lines.append(f"  font-size:   {var('scale-2')};")
    lines.append(f"  line-height: {var('lh-2')};")
    lines.append(f"  padding-left: {var('space-md')};")
    lines.append(f"  border-left: {format_value(round(fs / PHI**2))} solid currentColor;")
    lines.append(f"}}")
    lines.append("")
    lines.append(f"/* Spacing utility classes */")
    for key, val in sp.items():
        lines.append(f".mt-{key} {{ margin-top:    {format_value(val)}; }}")
        lines.append(f".mb-{key} {{ margin-bottom: {format_value(val)}; }}")
        lines.append(f".py-{key} {{ padding-top: {format_value(val)}; padding-bottom: {format_value(val)}; }}")

    return "\n".join(lines)


def print_summary(grt: dict):
    """Print a human-readable summary of the GRT values."""
    fs = grt['font_size']
    cw = grt['content_width']
    scale = grt['scale']
    lhs = grt['line_heights']
    sp = grt['spacing']
    h = grt['headings']
    hlh = grt['heading_line_heights']

    print(f"\n{'═'*58}")
    print(f"  Golden Ratio Typography Summary")
    print(f"  Base: {fs}px  |  Content width: {cw}px")
    print(f"  φ = {PHI:.6f}")
    print(f"{'═'*58}")
    print(f"\n  TYPOGRAPHIC SCALE")
    print(f"  {'Level':<10} {'Size':>8}  {'Line Height':>12}")
    print(f"  {'-'*32}")
    labels = ['body', 'h4/lead', 'h3', 'h2', 'h1', 'display']
    for i, (s, lh_v, label) in enumerate(zip(scale, lhs, labels), 1):
        print(f"  {label:<10} {format_value(s):>8}  {format_value(lh_v):>12}")

    print(f"\n  HEADINGS")
    print(f"  {'Tag':<6} {'Size':>8}  {'Line Height':>12}")
    print(f"  {'-'*28}")
    for tag in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']:
        print(f"  {tag:<6} {format_value(h[tag]):>8}  {format_value(hlh[tag]):>12}")

    print(f"\n  SPACING UNITS")
    for key, val in sp.items():
        print(f"  {key:<6} {format_value(val)}")

    print(f"\n  IDEAL CONTENT WIDTH: {format_value(grt['ideal_width'])}")
    print(f"{'═'*58}\n")


def inject_into_html(html_path: str, css: str):
    """Inject GRT styles into an HTML file's <head>."""
    path = Path(html_path)
    if not path.exists():
        print(f"  ✗ File not found: {html_path}", file=sys.stderr)
        return False

    content = path.read_text(encoding='utf-8')

    # Remove existing GRT block if present
    content = re.sub(
        r'\n?<!-- GRT-START -->.*?<!-- GRT-END -->\n?',
        '',
        content,
        flags=re.DOTALL
    )

    style_block = f"\n<!-- GRT-START -->\n<style>\n{css}\n</style>\n<!-- GRT-END -->\n"

    # Insert before </head>
    if '</head>' in content:
        content = content.replace('</head>', f"{style_block}</head>", 1)
    elif '<body' in content:
        content = content.replace('<body', f"{style_block}<body", 1)
    else:
        content = style_block + content

    path.write_text(content, encoding='utf-8')
    print(f"  ✓ Injected GRT styles into {html_path}")
    return True


def find_css_files(directory: str):
    """Recursively find CSS/SCSS files in a directory."""
    root = Path(directory)
    found = []
    skip_dirs = {'node_modules', '.git', 'vendor', 'dist', 'build', '__pycache__'}
    for ext in ('*.css', '*.scss', '*.sass'):
        for f in root.rglob(ext):
            if not any(skip in f.parts for skip in skip_dirs):
                found.append(f)
    return sorted(found)


def scan_project(directory: str, css: str, fmt: str):
    """Save GRT file and report where to import it in a project."""
    root = Path(directory)
    ext = '.scss' if fmt == 'scss' else '.css'
    out_path = root / f"grt{ext}"
    out_path.write_text(css, encoding='utf-8')
    print(f"\n  ✓ Saved GRT stylesheet: {out_path}")

    css_files = find_css_files(directory)
    if css_files:
        print(f"\n  Found {len(css_files)} stylesheet(s) in project:")
        for f in css_files[:10]:
            print(f"    • {f.relative_to(root)}")
        if len(css_files) > 10:
            print(f"    … and {len(css_files) - 10} more")
        print(f"\n  To use GRT variables, add this import at the top of your main stylesheet:")
        rel = out_path.relative_to(root)
        if fmt == 'scss':
            print(f"    @use './{rel}' as *;")
            print(f"    // or: @import './{rel}';")
        else:
            print(f"    @import url('./{rel}');")
            print(f"    // or: <link rel=\"stylesheet\" href=\"{rel}\">")
    return out_path


def main():
    parser = argparse.ArgumentParser(
        description='Golden Ratio Typography Calculator — Generate GRT CSS',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python grt.py --font-size 16 --content-width 680
  python grt.py --font-size 18 --content-width 800 --format scss --output styles/grt.scss
  python grt.py --font-size 16 --content-width 680 --inject index.html
  python grt.py --font-size 16 --content-width 680 --scan ./src
        """
    )
    parser.add_argument('--font-size', '-f', type=float, required=True,
                        help='Base font size in pixels (e.g. 16)')
    parser.add_argument('--content-width', '-w', type=float, default=680,
                        help='Content/column width in pixels (default: 680)')
    parser.add_argument('--format', choices=['css', 'scss'], default='css',
                        help='Output format: css (custom properties) or scss (default: css)')
    parser.add_argument('--prefix', default='grt-',
                        help='Variable name prefix (default: grt-)')
    parser.add_argument('--target', default='.grt',
                        help='CSS selector for applied styles (default: .grt)')
    parser.add_argument('--output', '-o', default=None,
                        help='Write CSS to this file path')
    parser.add_argument('--inject', default=None,
                        help='Inject styles into this HTML file')
    parser.add_argument('--scan', default=None,
                        help='Save grt.css to this project directory and report import locations')
    parser.add_argument('--x-height', type=float, default=None,
                        help='Font x-height ratio for correction (0.45–0.60 typical)')
    parser.add_argument('--no-summary', action='store_true',
                        help='Suppress the summary table')
    parser.add_argument('--css-only', action='store_true',
                        help='Print only the CSS (no summary)')

    args = parser.parse_args()

    # Calculate GRT
    grt = calculate_grt(args.font_size, args.content_width, args.x_height)
    css = generate_css(grt, prefix=args.prefix, fmt=args.format, target=args.target)

    if not args.no_summary and not args.css_only:
        print_summary(grt)

    if args.css_only:
        print(css)
        return

    if args.inject:
        inject_into_html(args.inject, css)
        return

    if args.scan:
        scan_project(args.scan, css, args.format)
        return

    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(css, encoding='utf-8')
        print(f"  ✓ Saved: {args.output}\n")
    else:
        print(css)


if __name__ == '__main__':
    main()
