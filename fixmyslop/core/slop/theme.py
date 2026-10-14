"""
Theme index — what the project's design system actually is.

Two jobs:
1. Resolve colors (hex, rgb, hsl, oklch, CSS variables) so rules can judge a
   gradient by its real hue instead of by name.
2. Describe the existing tokens (primary color, fonts, radius, icon library)
   so the fix brief can tell an agent "use bg-primary (your blue)" instead of
   just "don't use purple". Agents write slop when they don't know the design
   system; this tells them.
"""
import colorsys
import json
import math
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

_SKIP_DIRS = {
    "node_modules", ".git", "dist", "build", ".next", ".nuxt", "coverage", ".svelte-kit",
    ".turbo", ".output", ".vercel", "vendor", "__pycache__", ".venv", "venv",
}
_STYLE_EXT = {".css", ".scss", ".sass", ".less"}
_VAR_DEF = re.compile(r"(--[\w-]+)\s*:\s*([^;{}]+);")
_CSS_BLOCK = re.compile(r"([^{}]+)\{([^{}]*)\}")
_UPPERCASE = re.compile(r"text-transform\s*:\s*uppercase", re.IGNORECASE)
_WIDE_TRACKING = re.compile(r"letter-spacing\s*:\s*(?:0?\.(?:0[8-9]|[1-9])\d*em|[1-9]\d*(?:\.\d+)?px|0?\.\d+rem)",
                            re.IGNORECASE)
_ICON_LIBS = [
    "lucide-react", "lucide-vue-next", "lucide-svelte", "@heroicons/react", "@tabler/icons-react",
    "react-icons", "@phosphor-icons/react", "@radix-ui/react-icons", "@iconify/react", "phosphor-react",
]
_TW_CONFIGS = ["tailwind.config.ts", "tailwind.config.js", "tailwind.config.cjs", "tailwind.config.mjs"]

# ─── Color parsing ───────────────────────────────────────────────────────────

_NUM = r"-?\d*\.?\d+"
_SEP = r"[\s,_/]+"
COLOR_RE = re.compile(
    r"#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3,4})\b"
    rf"|rgba?\(\s*{_NUM}%?{_SEP}{_NUM}%?{_SEP}{_NUM}%?(?:{_SEP}{_NUM}%?)?\s*\)"
    rf"|hsla?\(\s*{_NUM}(?:deg)?{_SEP}{_NUM}%?{_SEP}{_NUM}%?(?:{_SEP}{_NUM}%?)?\s*\)"
    rf"|oklch\(\s*{_NUM}%?{_SEP}{_NUM}%?{_SEP}{_NUM}(?:deg)?(?:{_SEP}{_NUM}%?)?\s*\)"
    r"|hsla?\(\s*var\(\s*--[\w-]+\s*\)[^)]*\)|var\(\s*--[\w-]+\s*\)",
    re.IGNORECASE,
)
_BARE_HSL = re.compile(rf"^\s*({_NUM})(?:deg)?\s+({_NUM})%\s+({_NUM})%\s*(?:/\s*{_NUM}%?)?\s*$")


@dataclass(frozen=True)
class Color:
    """A parsed color in HSL terms (hue in degrees, sat/light 0-1)."""

    hue: float
    sat: float
    light: float
    alpha: float = 1.0

    @property
    def is_neutral(self) -> bool:
        """Grays, near-black, near-white."""
        return self.sat < 0.18 or self.light < 0.08 or self.light > 0.96

    @property
    def family(self) -> str:
        """Coarse hue family name."""
        if self.is_neutral:
            return "neutral"
        h = self.hue
        for limit, name in ((15, "red"), (45, "orange"), (65, "yellow"), (160, "green"), (195, "teal"),
                            (250, "blue"), (290, "violet"), (330, "magenta"), (360, "red")):
            if h < limit:
                return name
        return "red"

    @property
    def is_ai_purple(self) -> bool:
        """The violet/purple/magenta band AI templates default to."""
        return not self.is_neutral and 255 <= self.hue <= 325


def _nums(text: str) -> list[float]:
    return [float(n) for n in re.findall(_NUM, text)]


def parse_color(token: str, variables: Optional[dict] = None, depth: int = 0) -> Optional[Color]:
    """Parse one color token; resolves var(--x) / hsl(var(--x)) through `variables`."""
    t = token.strip()
    low = t.lower()
    try:
        if "var(" in low:
            if depth > 4 or not variables:
                return None
            name = re.search(r"--[\w-]+", t).group(0)
            value = variables.get(name)
            if not value:
                return None
            bare = _BARE_HSL.match(value)
            if bare:  # shadcn style: --primary: 262 83% 58%;
                h, s, li = (float(x) for x in bare.groups())
                return Color(h % 360, s / 100, li / 100)
            inner = COLOR_RE.search(value)
            return parse_color(inner.group(0), variables, depth + 1) if inner else None
        if low.startswith("#"):
            hexv = low[1:]
            if len(hexv) in (3, 4):
                hexv = "".join(c * 2 for c in hexv)
            r, g, b = (int(hexv[i:i + 2], 16) / 255 for i in (0, 2, 4))
            alpha = int(hexv[6:8], 16) / 255 if len(hexv) == 8 else 1.0
            return _from_rgb(r, g, b, alpha)
        if low.startswith("rgb"):
            n = _nums(t[t.index("("):])
            pct = "%" in t.split(")")[0].split("(")[1].split(",")[0] if "," in t else False
            scale = 100 if pct else 255
            r, g, b = (x / scale for x in n[:3])
            return _from_rgb(r, g, b, n[3] if len(n) > 3 and n[3] <= 1 else 1.0)
        if low.startswith("hsl"):
            n = _nums(t[t.index("("):])
            return Color(n[0] % 360, n[1] / 100, n[2] / 100, n[3] if len(n) > 3 and n[3] <= 1 else 1.0)
        if low.startswith("oklch"):
            n = _nums(t[t.index("("):])
            lightness = n[0] / 100 if n[0] > 1 else n[0]
            chroma, hue = n[1], n[2]
            sat = min(1.0, chroma / 0.25)
            return Color(_oklch_hue_to_hsl_hue(hue), sat if chroma > 0.04 else 0.0, lightness,
                         n[3] if len(n) > 3 and n[3] <= 1 else 1.0)
    except (ValueError, IndexError, AttributeError):
        return None
    return None


def _from_rgb(r: float, g: float, b: float, alpha: float = 1.0) -> Color:
    h, li, s = colorsys.rgb_to_hls(max(0.0, min(1.0, r)), max(0.0, min(1.0, g)), max(0.0, min(1.0, b)))
    return Color(h * 360, s, li, alpha)


def _oklch_hue_to_hsl_hue(h: float) -> float:
    """OKLCH hue angles run ~25° ahead of HSL for blues/purples; map onto HSL's scale."""
    table = [(0, 340), (30, 10), (60, 30), (90, 50), (130, 90), (150, 130), (195, 180), (230, 200),
             (255, 222), (265, 240), (280, 258), (292, 270), (305, 285), (320, 300), (345, 320), (360, 340)]
    h %= 360
    for (a, ha), (b, hb) in zip(table, table[1:], strict=False):
        if a <= h <= b:
            return (ha + (hb - ha) * (h - a) / (b - a)) % 360
    return h


def colors_in(text: str, variables: Optional[dict] = None) -> list[Color]:
    """Every parseable color in a piece of text."""
    out = []
    for match in COLOR_RE.finditer(text):
        color = parse_color(match.group(0), variables)
        if color is not None:
            out.append(color)
    return out


def describe(color: Color) -> str:
    """Human words for a color, e.g. 'blue', 'dark violet'."""
    if color.is_neutral:
        return "near-black" if color.light < 0.15 else "near-white" if color.light > 0.9 else "gray"
    tone = "dark " if color.light < 0.3 else "light " if color.light > 0.75 else ""
    return tone + color.family


# ─── Theme index ─────────────────────────────────────────────────────────────

@dataclass
class ThemeIndex:
    """The project's design tokens, discovered once per scan."""

    root: Path
    variables: dict = field(default_factory=dict)
    shadcn: bool = False
    icon_library: str = ""
    fonts: list = field(default_factory=list)
    radius: str = ""
    tailwind_config: str = ""
    tailwind_colors: list = field(default_factory=list)
    eyebrow_classes: set = field(default_factory=set)

    @classmethod
    def build(cls, root: Path) -> "ThemeIndex":
        """Walk style files and configs once (bounded)."""
        index = cls(root=root)
        index.shadcn = (root / "components.json").exists()
        seen = 0
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS and not d.startswith(".")]
            for name in filenames:
                seen += 1
                path = Path(dirpath) / name
                if path.suffix.lower() in _STYLE_EXT:
                    index._read_css(path)
                elif name == "package.json" and Path(dirpath) == root:
                    index._read_package(path)
                elif name in _TW_CONFIGS and not index.tailwind_config:
                    index._read_tailwind(path)
            if seen > 20000:
                break
        return index

    def _read_css(self, path: Path):
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return
        if len(text) > 400_000:
            return
        for selector, body in _CSS_BLOCK.findall(text):
            if _UPPERCASE.search(body) and _WIDE_TRACKING.search(body):
                self.eyebrow_classes.update(re.findall(r"\.([A-Za-z][\w-]*)", selector))
        for name, value in _VAR_DEF.findall(text):
            # First definition wins (usually :root / light theme).
            self.variables.setdefault(name, value.strip())
        for family in re.findall(r"font-family\s*:\s*([^;]+);", text):
            self._add_font(family)
        for family in re.findall(r"--font-[\w-]+\s*:\s*([^;]+);", text):
            self._add_font(family)
        radius = self.variables.get("--radius")
        if radius and not self.radius:
            self.radius = radius

    def _add_font(self, family: str):
        first = family.split(",")[0].strip().strip("'\"")
        if first and not first.startswith(("var(", "inherit", "-apple", "system-ui", "ui-", "sans-serif",
                                          "serif", "monospace")) and first not in self.fonts:
            self.fonts.append(first)

    def _read_package(self, path: Path):
        try:
            data = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
        except (OSError, ValueError):
            return
        deps = {**(data.get("dependencies") or {}), **(data.get("devDependencies") or {})}
        for lib in _ICON_LIBS:
            if lib in deps:
                self.icon_library = lib
                break
        for dep in deps:
            if dep.startswith("@fontsource/") or dep.startswith("@fontsource-variable/"):
                self._add_font(dep.split("/", 1)[1].replace("-", " ").title())

    def _read_tailwind(self, path: Path):
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return
        self.tailwind_config = path.name
        colors = re.search(r"colors\s*:\s*\{(.*?)\n\s{4,6}\}", text, re.DOTALL)
        if colors:
            self.tailwind_colors = sorted(set(re.findall(r"^\s*['\"]?([a-z][\w-]*)['\"]?\s*:", colors.group(1),
                                                         re.MULTILINE)))[:20]
        for family in re.findall(r"fontFamily\s*:\s*\{[^}]*?\[\s*['\"]([^'\"]+)['\"]", text, re.DOTALL):
            self._add_font(family)

    # ── queries ─────────────────────────────────────────────────────────────
    def token_color(self, name: str) -> Optional[Color]:
        """Resolve a CSS variable to a color."""
        return parse_color(f"var({name})", self.variables)

    @property
    def primary(self) -> Optional[Color]:
        for name in ("--primary", "--color-primary", "--brand", "--accent", "--color-brand"):
            color = self.token_color(name)
            if color is not None:
                return color
        return None

    def design_context(self) -> str:
        """Markdown bullet list describing the existing design system for an agent."""
        lines = []
        primary = self.primary
        if primary is not None:
            hint = " — use `bg-primary` / `text-primary` / `text-primary-foreground`" if self.shadcn else \
                " — use the `--primary` token"
            lines.append(f"- Primary/brand color: **{describe(primary)}** (`--primary`){hint}. "
                         "Use it as the ONLY accent.")
        neutrals = [n for n in ("--background", "--foreground", "--muted", "--muted-foreground", "--border", "--card")
                    if n in self.variables]
        if neutrals:
            classes = ", ".join(f"`{n[2:]}`" for n in neutrals)
            lines.append(f"- Surfaces & text tokens available: {classes} — use these instead of raw colors.")
        if self.radius:
            lines.append(f"- Corner radius token: `--radius: {self.radius}` (use `rounded-lg`/`rounded-md` "
                         "from the theme, not ad-hoc `rounded-3xl`).")
        if self.fonts:
            lines.append(f"- Fonts already defined: {', '.join(self.fonts[:4])}. Don't add new ones.")
        if self.icon_library:
            lines.append(f"- Icon library: `{self.icon_library}` — use it for every icon; never emoji.")
        if self.shadcn:
            lines.append("- shadcn/ui is installed: reuse components from `components/ui/` "
                         "(Button, Card, Badge, Input…) instead of hand-styled lookalikes.")
        if self.tailwind_colors:
            lines.append(f"- Tailwind theme colors: {', '.join(self.tailwind_colors[:12])}.")
        if not lines:
            lines.append("- No design tokens found. Before restyling, define a small set: one accent color, "
                         "neutrals for background/foreground/muted/border, one radius, one font pairing — "
                         "as CSS variables or tailwind theme — and use only those.")
        return "\n".join(lines)


def hue_distance(a: float, b: float) -> float:
    """Shortest angular distance between two hues."""
    d = abs(a - b) % 360
    return min(d, 360 - d)


def is_close(a: Color, b: Color) -> bool:
    """Same-ish color (used to avoid flagging the project's own brand color)."""
    return hue_distance(a.hue, b.hue) < 18 and abs(a.light - b.light) < 0.25 and not math.isnan(a.hue)
