"""App styles (owner 2026-10-04, OPUSUI1): one themes stylesheet, every page follows it.

- every style in static/themes.css defines every --cf-* token, and the boot script lists the same styles;
- the restyled stylesheets name no colours of their own (map art on the table is an explicit allow-list);
- every page loads themes.css and the boot script before its own CSS (no flash of the old look);
- bundled fonts exist with their licences;
- Settings > Appearance offers the four styles and six custom colours;
- the boot script's behaviour (defaults, legacy names, custom-colour tokens, saving) via node;
- rules that set both a text and a background colour stay readable (4.5:1) in the dark styles.
- review fixes (OPUSUI1f1): Reduce motion switches animations off (toasts stay readable), table/sheet/map editor
  text follows Text size, and the Settings contrast check covers small (faint) text for built-in and custom colours.
- review fixes (OPUSUI1f3): a refused save is reported in Settings (not shown as saved), and hovered builder step hints
  stay readable (and are part of the Settings contrast check).
  Rendered versions of these checks are in test_ui_themes_browser.py (opt-in, CF_UI_BROWSER=1).
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
THEMES = (STATIC / "themes.css").read_text(encoding="utf-8")
STYLES = ["lacquer", "celestial", "ember", "classic"]

RESTYLED = [
    "styles.css",
    "tabletop/tabletop.css",
    "tabletop/sheet.css",
    "tabletop/mapeditor.css",
    "tabletop/newcomer.css",
]
PAGES = ["index.html", "tabletop/tabletop.html", "tabletop/sheet.html", "tabletop/mapeditor.html"]

COLOUR = re.compile(
    r"#[0-9a-fA-F]{3,8}\b|\b(?:rgba?|hsla?|hwb|lab|lch|oklab|oklch)\(|(?<![-\w])(?:white|black|Canvas|CanvasText)(?![-\w])"
)
# Battlefield art on the table keeps fixed colours so the map reads the same in every style.
MAP_ART_SELECTOR = re.compile(r"\.tt-(cell|stone|wall|walls|mark|token(?!-card)|float|zone-(halo|hatch|label|edge)|object-art|board)\b")
MAP_ART_PROPERTY = re.compile(r"--(team-\d|wall-[a-z]+|sight|floor-[a-z0-9]+)$")


def style_block(name: str) -> dict[str, str]:
    match = re.search(r'\[data-theme-preview="%s"\]\s*\{([^}]*)\}' % name, THEMES)
    assert match, f"themes.css has no block for {name}"
    return dict(re.findall(r"(--cf-[a-z0-9-]+)\s*:\s*([^;]+);", match.group(1)))


def rules(css: str):
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    for match in re.finditer(r"([^{}]+)\{([^{}]*)\}", css):
        yield match.group(1).strip(), match.group(2)


def declarations(body: str):
    depth, start = 0, 0
    for i, ch in enumerate(body + ";"):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == ";" and depth == 0:
            decl = body[start:i]
            start = i + 1
            if ":" in decl:
                prop, value = decl.split(":", 1)
                yield prop.strip(), value.strip()


def test_every_style_defines_every_token():
    blocks = {name: style_block(name) for name in STYLES}
    expected = set(blocks["lacquer"])
    assert len(expected) >= 55
    for name, tokens in blocks.items():
        assert set(tokens) == expected, (name, sorted(expected ^ set(tokens)))
    # Night Lacquer is the default (applies with no attribute) and uses the owner's palette.
    assert re.search(r':root,\s*:root\[data-theme="lacquer"\],\s*\[data-theme-preview="lacquer"\]', THEMES)
    lacquer = blocks["lacquer"]
    for token, value in {"bg": "#121214", "panel": "#1b1b1f", "line": "#2c2c33", "tile": "#232329", "text": "#ece7df",
                         "muted": "#b3aca2", "faint": "#8a847b", "accent": "#c8402f", "on-accent": "#fff4ee",
                         "chip": "#3a1d18"}.items():
        assert lacquer[f"--cf-{token}"] == value, token
    assert lacquer["--cf-font-display"].startswith('"Cinzel"')
    assert lacquer["--cf-font-body"].startswith('"Space Grotesk"')


def test_boot_script_lists_the_same_styles():
    boot = (STATIC / "appearance-boot.js").read_text(encoding="utf-8")
    ids = re.findall(r'\{ id: "([a-z]+)", name: "', boot)
    assert ids == STYLES
    for name in STYLES:
        assert f':root[data-theme="{name}"]' in THEMES


@pytest.mark.parametrize("relative", RESTYLED)
def test_restyled_stylesheets_name_no_colours(relative):
    css = (STATIC / relative).read_text(encoding="utf-8")
    offenders = []
    for selector, body in rules(css):
        if selector.startswith("@font-face"):
            continue
        for prop, value in declarations(body):
            if not COLOUR.search(value):
                continue
            if relative == "tabletop/tabletop.css" and (MAP_ART_SELECTOR.search(selector) or MAP_ART_PROPERTY.match(prop)):
                continue
            offenders.append(f"{selector[:60]} {{ {prop}: {value[:60]} }}")
    assert offenders == [], "\n".join(offenders[:40])
    assert "color-scheme: light" not in css or relative != "styles.css"


@pytest.mark.parametrize("page", PAGES)
def test_pages_apply_the_style_before_first_paint(page):
    html = (STATIC / page).read_text(encoding="utf-8")
    themes = html.index('href="/static/themes.css')
    boot = html.index('<script src="/static/appearance-boot.js')
    own_css = [m.start() for m in re.finditer(r'<link rel="stylesheet" href="/static/(?!themes\.css)', html)]
    body = html.index("<body")
    assert themes < boot < body
    assert all(boot < position for position in own_css), page
    assert "data-theme=" not in html[body:html.index(">", body)], "the style lives on <html>, not <body>"
    assert not re.search(r'style="[^"]*(#[0-9a-fA-F]{3,8}\b|rgba?\()', html), "inline colours bypass the styles"


def test_bundled_fonts_have_files_and_licences():
    urls = re.findall(r'url\("/static/(fonts/[^"]+\.woff2)"\)', THEMES)
    assert len(urls) >= 20
    for url in urls:
        assert (STATIC / url).is_file(), url
    families = {Path(url).name.split("-latin")[0] for url in urls}
    assert families == {"cinzel", "space-grotesk", "cormorant-garamond", "marcellus", "figtree", "nunito-sans"}
    for family in families:
        licence = (STATIC / "fonts" / f"{family}-OFL.txt").read_text(encoding="utf-8")
        assert "SIL Open Font License" in licence


def test_settings_appearance_screen():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert '<button data-screen="settings">Settings</button>' in html
    assert 'id="screen-settings"' in html
    assert re.findall(r'class="style-card" role="radio" aria-checked="false" data-style="([a-z]+)"', html) == STYLES
    assert re.findall(r'data-colour="([a-z]+)"', html) == ["accent", "bg", "panel", "text", "debuff", "buff"]
    for element in ["appearanceHeadingFont", "appearanceTextSize", "appearanceReduceMotion", "appearanceContrast",
                    "appearanceSave", "appearanceUndo", "appearanceResetColours"]:
        assert f'id="{element}"' in html
    assert '<script src="/static/appearance-settings.js' in html
    # The nav sits in the top bar, as in the approved mockups.
    header = html[html.index('<header class="app-header">'):html.index("</header>")]
    assert '<nav class="product-nav"' in header


def test_table_sheet_and_map_editor_pickers_offer_the_app_styles():
    for page, select in [("tabletop/tabletop.html", "ttTheme"), ("tabletop/sheet.html", "theme-select"),
                         ("tabletop/mapeditor.html", "meTheme")]:
        html = (STATIC / page).read_text(encoding="utf-8")
        block = html[html.index(f'id="{select}"'):]
        block = block[:block.index("</select>")]
        assert re.findall(r'<option value="([a-z]+)"', block) == STYLES, page
    assert "TianxiaAppearance" in (STATIC / "tabletop/tabletop.js").read_text(encoding="utf-8")
    assert "TianxiaAppearance" in (STATIC / "tabletop/sheet.js").read_text(encoding="utf-8")
    assert "TianxiaAppearance" in (STATIC / "tabletop/mapeditor.js").read_text(encoding="utf-8")


NODE_HARNESS = r"""
const fs = require('fs');
const themes = fs.readFileSync(process.argv[2], 'utf8');
const boot = fs.readFileSync(process.argv[3], 'utf8');
const blocks = {};
for (const name of ['lacquer', 'celestial', 'ember', 'classic']) {
  const m = themes.match(new RegExp('\\[data-theme-preview="' + name + '"\\]\\s*\\{([^}]*)\\}'));
  blocks[name] = Object.fromEntries([...m[1].matchAll(/(--cf-[a-z0-9-]+)\s*:\s*([^;]+);/g)].map(x => [x[1], x[2].trim()]));
}
function makeWorld(saved) {
  const attrs = {}, inline = {}, store = {};
  if (saved !== undefined) store['tianxia.appearance.v1'] = JSON.stringify(saved);
  const root = {
    setAttribute: (k, v) => { attrs[k] = String(v); }, removeAttribute: k => { delete attrs[k]; },
    getAttribute: k => attrs[k], hasAttribute: k => k in attrs,
    style: { setProperty: (k, v) => { inline[k] = v; }, removeProperty: k => { delete inline[k]; } },
  };
  const window = { addEventListener() {}, matchMedia: () => ({ matches: false }) };
  const ctx = {
    window, document: { documentElement: root },
    localStorage: { getItem: k => (k in store ? store[k] : null), setItem: (k, v) => { store[k] = v; } },
    getComputedStyle: () => ({ getPropertyValue: n => (n in inline ? inline[n] : (blocks[attrs['data-theme'] || 'lacquer'][n] || '')) }),
  };
  new Function('window', 'document', 'localStorage', 'getComputedStyle', boot)(ctx.window, ctx.document, ctx.localStorage, ctx.getComputedStyle);
  return { A: window.TianxiaAppearance, attrs, inline, store };
}
const out = {};
let w = makeWorld();
out.fresh = { theme: w.attrs['data-theme'], inline: Object.keys(w.inline).length };
w = makeWorld({ style: 'crimson', custom: { accent: 'nonsense' }, textSize: 'huge', headingFont: 'comic' });
out.legacy = { theme: w.attrs['data-theme'], custom: w.A.current().custom, size: w.attrs['data-text-size'] || null,
               font: w.attrs['data-heading-font'] || null };
w = makeWorld({ style: 'celestial', custom: { accent: '#ffe14d', text: '#c0c0c0', debuff: '#ff2a2a' },
                headingFont: 'marcellus', textSize: 'large', reduceMotion: true });
const t = w.A.tokens();
out.custom = {
  theme: w.attrs['data-theme'], font: w.attrs['data-heading-font'], size: w.attrs['data-text-size'], motion: w.attrs['data-motion'],
  accent: w.inline['--cf-accent'], onAccent: w.inline['--cf-on-accent'],
  onAccentContrast: w.A.contrast(t['on-accent'], t.accent), accentTextContrast: w.A.contrast(t['accent-text'], t.panel),
  mutedContrast: w.A.contrast(t.muted, t.panel), debuffContrast: w.A.contrast(t['debuff-text'], t['debuff-bg']),
  buffContrast: w.A.contrast(t['buff-text'], t['buff-bg']),
};
w.A.setStyle('ember');
out.setStyle = { theme: w.attrs['data-theme'], saved: JSON.parse(w.store['tianxia.appearance.v1']), inline: Object.keys(w.inline).length };
w.A.save({ style: 'classic', custom: { bg: '#101010' } });
out.saveDark = { theme: w.attrs['data-theme'], bg: w.inline['--cf-bg'], textContrast: w.A.contrast(w.A.tokens().text, w.A.tokens().bg) };
console.log(JSON.stringify(out));
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_boot_script_behaviour(tmp_path):
    harness = tmp_path / "harness.cjs"
    harness.write_text(NODE_HARNESS, encoding="utf-8")
    result = subprocess.run(["node", str(harness), str(STATIC / "themes.css"), str(STATIC / "appearance-boot.js")],
                            check=True, capture_output=True, text=True, timeout=30)
    out = json.loads(result.stdout)
    # Nothing saved: Night Lacquer, no custom colours.
    assert out["fresh"] == {"theme": "lacquer", "inline": 0}
    # Old skin names land on a style; bad values are dropped.
    assert out["legacy"] == {"theme": "lacquer", "custom": {}, "size": None, "font": None}
    custom = out["custom"]
    assert (custom["theme"], custom["font"], custom["size"], custom["motion"]) == ("celestial", "marcellus", "large", "reduce")
    assert custom["accent"] == "#ffe14d"
    assert custom["onAccent"] == "#16110c"  # a bright accent gets dark button text
    for key in ["onAccentContrast", "accentTextContrast", "mutedContrast", "debuffContrast", "buffContrast"]:
        assert custom[key] >= 4.5, (key, custom[key])
    # Changing style clears the custom colours (they belong to a style) and saves.
    assert out["setStyle"]["theme"] == "ember"
    assert out["setStyle"]["saved"]["style"] == "ember" and out["setStyle"]["saved"]["custom"] == {}
    assert out["setStyle"]["inline"] == 0
    # A dark background on the light style: the warning would show, but the tokens still apply.
    assert out["saveDark"]["theme"] == "classic" and out["saveDark"]["bg"] == "#101010"


def _resolve(expr: str, tokens: dict[str, str], aliases: dict[str, str], base: str | None):
    for _ in range(8):
        match = re.search(r"var\((--[a-z0-9-]+)(?:,\s*([^()]*))?\)", expr)
        if not match:
            break
        value = tokens.get(match.group(1)) or aliases.get(match.group(1)) or (match.group(2) or "")
        expr = expr[:match.start()] + value + expr[match.end():]
    mix = re.match(r"\s*color-mix\(in srgb,\s*(#[0-9a-f]{6})\s+(\d+)%,\s*(transparent|#[0-9a-f]{6})\)", expr)
    if mix:
        other = base if mix.group(3) == "transparent" else mix.group(3)
        if not other:
            return None
        a, b, p = _rgb(mix.group(1)), _rgb(other), int(mix.group(2)) / 100
        return "#%02x%02x%02x" % tuple(round(a[i] * p + b[i] * (1 - p)) for i in range(3))
    plain = re.fullmatch(r"\s*(#[0-9a-fA-F]{6})\s*(!important)?\s*", expr)
    return plain.group(1) if plain else None


def _rgb(value: str):
    return [int(value[i:i + 2], 16) for i in (1, 3, 5)]


def _contrast(a: str, b: str) -> float:
    def lum(c):
        v = [x / 255 for x in _rgb(c)]
        v = [x / 12.92 if x <= .03928 else ((x + .055) / 1.055) ** 2.4 for x in v]
        return .2126 * v[0] + .7152 * v[1] + .0722 * v[2]
    hi, lo = sorted([lum(a), lum(b)], reverse=True)
    return (hi + .05) / (lo + .05)


@pytest.mark.parametrize("style", ["lacquer", "celestial", "ember"])
@pytest.mark.parametrize("relative", ["styles.css", "tabletop/tabletop.css", "tabletop/sheet.css"])
def test_text_on_painted_backgrounds_stays_readable(style, relative):
    tokens = style_block(style)
    css = (STATIC / relative).read_text(encoding="utf-8")
    aliases = {k: v.strip() for k, v in re.findall(r"(--[a-z0-9-]+)\s*:\s*([^;{}]+);", re.sub(r"/\*.*?\*/", "", css, flags=re.S))
               if not k.startswith("--cf-")}
    weak = []
    for selector, body in rules(css):
        if ":disabled" in selector or "::before" in selector or "::after" in selector:
            continue
        decls = dict(declarations(body))
        fg = decls.get("color")
        bg = decls.get("background-color") or decls.get("background")
        if not fg or not bg:
            continue
        bg_value = _resolve(bg, tokens, aliases, tokens["--cf-bg"])
        fg_value = _resolve(fg, tokens, aliases, bg_value)
        if fg_value and bg_value and _contrast(fg_value, bg_value) < 4.5:
            weak.append((round(_contrast(fg_value, bg_value), 2), selector[:70], fg_value, bg_value))
    assert weak == []


# ---------------------------------------------------------------- review fixes (OPUSUI1f1)
SETTINGS_JS = (STATIC / "appearance-settings.js").read_text(encoding="utf-8")
SETTINGS_PAIRS = re.findall(r'\["([a-z-]+)", "([a-z-]+)", "([^"]+)"\]', SETTINGS_JS)
SCALED_CSS = ["tabletop/tabletop.css", "tabletop/sheet.css", "tabletop/mapeditor.css", "tabletop/newcomer.css"]
# Glyphs drawn inside a 64px map token follow the map zoom, not Text size.
TOKEN_GLYPH = re.compile(r"\.tt-token-(face|badge|conds)\b|\.tt-zone-label\b")


def test_reduce_motion_switches_animations_off_instead_of_finishing_them():
    """A fade-out finished in .001ms hid table toasts at once; with no animation they stay until removed."""
    block = THEMES[THEMES.index(':root[data-motion="reduce"] *,'):]
    block = block[:block.index("}")]
    assert "animation: none !important" in block
    assert "animation-duration" not in block
    # The table toast fades to nothing at its end, so a shortened animation would hide it immediately.
    table = (STATIC / "tabletop/tabletop.css").read_text(encoding="utf-8")
    assert re.search(r"@keyframes tt-toast \{.*100% \{ opacity: 0; \} \}", table)
    assert re.search(r"setTimeout\(\(\) => node\.remove\(\), 4200\)", (STATIC / "tabletop/tabletop.js").read_text(encoding="utf-8"))


@pytest.mark.parametrize("relative", SCALED_CSS)
def test_table_sheet_and_map_editor_text_follows_text_size(relative):
    """Fixed px font sizes ignored Settings > Text size; every one is multiplied by --cf-text-scale."""
    css = (STATIC / relative).read_text(encoding="utf-8")
    fixed = []
    for selector, body in rules(css):
        for prop, value in declarations(body):
            if prop == "font-size":
                size = value
            elif prop == "font":
                size = re.sub(r"/[^ ]+", "", value)
            else:
                continue
            if re.search(r"\d+(\.\d+)?px", size) and "var(--cf-text-scale" not in size and not TOKEN_GLYPH.search(selector):
                fixed.append(f"{selector[:60]} {{ {prop}: {value} }}")
    assert fixed == [], "\n".join(fixed)
    if relative == "tabletop/tabletop.css":
        for selector in [".tt-pill", ".tt-btn b", ".tt-btn small", ".tt-card-cond"]:
            body = next(b for s, b in rules(css) if s == selector)
            assert "calc(" in dict(declarations(body))["font-size"], selector
    if relative == "tabletop/sheet.css":
        for selector in [".arow-label", ".arow-sub", ".cond", ".qbtn .qsub"]:
            body = next(b for s, b in rules(css) if s == selector)
            assert "var(--cf-text-scale, 1)" in body, selector


def test_settings_contrast_check_covers_small_text():
    pairs = {(fg, bg) for fg, bg, _ in SETTINGS_PAIRS}
    assert {("faint", "panel"), ("faint", "bg"), ("muted", "panel"), ("muted", "bg")} <= pairs
    assert "All text is easy to read" not in SETTINGS_JS


@pytest.mark.parametrize("style", STYLES)
def test_built_in_styles_pass_every_settings_contrast_check(style):
    """Each style's own colours get the all-clear honestly (every pair Settings checks reaches 4.5:1)."""
    tokens = style_block(style)
    weak = [(label, round(_contrast(tokens[f"--cf-{fg}"], tokens[f"--cf-{bg}"]), 2)) for fg, bg, label in SETTINGS_PAIRS
            if _contrast(tokens[f"--cf-{fg}"], tokens[f"--cf-{bg}"]) < 4.5]
    assert weak == []


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_custom_text_colour_keeps_small_text_readable(tmp_path):
    """Review counterexample: Night Lacquer with only Text = #909090 derived faint #6c6c6d (3.27:1 on panels)."""
    world = NODE_HARNESS[:NODE_HARNESS.index("const out = {};")]
    script = world + r"""
const pairs = JSON.parse(process.argv[4]);
const results = {};
for (const [name, custom] of [['textOnly', { text: '#909090' }], ['darkPanel', { text: '#a0a0a0', panel: '#303030' }],
                               ['lightStyle', { text: '#4a4a4a', bg: '#ffffff' }]]) {
  const w = makeWorld({ style: name === 'lightStyle' ? 'classic' : 'lacquer', custom });
  const t = w.A.tokens();
  results[name] = { faint: t.faint, ratios: Object.fromEntries(pairs.map(([fg, bg]) => [fg + '/' + bg, w.A.contrast(t[fg], t[bg])])) };
}
console.log(JSON.stringify(results));
"""
    harness = tmp_path / "small_text.cjs"
    harness.write_text(script, encoding="utf-8")
    pairs = [[fg, bg] for fg, bg, _ in SETTINGS_PAIRS]
    result = subprocess.run(["node", str(harness), str(STATIC / "themes.css"), str(STATIC / "appearance-boot.js"), json.dumps(pairs)],
                            check=True, capture_output=True, text=True, timeout=30)
    out = json.loads(result.stdout)
    assert out["textOnly"]["faint"] != "#6c6c6d"
    for name, case in out.items():
        for pair in ["faint/panel", "faint/bg", "muted/panel", "muted/bg", "muted/tile"]:
            assert case["ratios"][pair] >= 4.5, (name, pair, case)


# ---------------------------------------------------------------- review fixes (OPUSUI1f2)
def _rule_body(css: str, selector: str) -> dict[str, str]:
    """Declarations of the last rule naming `selector` (the one that wins the cascade)."""
    return dict(declarations([b for s, b in rules(css) if selector in [x.strip() for x in s.split(",")]][-1]))


@pytest.mark.parametrize("style", STYLES)
def test_active_builder_step_hints_are_readable(style):
    """Active-step hints (.75rem) inherit the step's accent fill; Night Lacquer's soft text was 3.24:1 on it."""
    tokens = style_block(style)
    css = (STATIC / "styles.css").read_text(encoding="utf-8")
    fill = _resolve(_rule_body(css, ".owner-step.is-active")["background"], tokens, {}, tokens["--cf-bg"])
    hint = _resolve(_rule_body(css, ".owner-step.is-active small")["color"], tokens, {}, fill)
    assert fill == tokens["--cf-accent"]
    assert _contrast(hint, fill) >= 4.5, (style, hint, fill, round(_contrast(hint, fill), 2))
    assert ("on-accent-soft", "accent") in {(fg, bg) for fg, bg, _ in SETTINGS_PAIRS}


def test_no_invalid_css_functions():
    """ui-var() is not CSS; the browser dropped the whole declaration (seed and import fields lost their mono font)."""
    for relative in RESTYLED + ["themes.css"]:
        assert "ui-var(" not in (STATIC / relative).read_text(encoding="utf-8"), relative


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_custom_colours_keep_active_step_hints_readable(tmp_path):
    """Review counterexample: Night Lacquer with only Text = #909090 derived soft hint text #f1c8c0 (3.25:1 on the accent)."""
    world = NODE_HARNESS[:NODE_HARNESS.index("const out = {};")]
    script = world + r"""
const results = {};
for (const [name, style, custom] of [['textOnly', 'lacquer', { text: '#909090' }], ['redAccent', 'lacquer', { accent: '#c8402f' }],
                                     ['orangeAccent', 'ember', { accent: '#e0823c' }], ['darkAccent', 'classic', { accent: '#1f5b47' }],
                                     ['midAccent', 'celestial', { accent: '#3a7bd5' }]]) {
  const w = makeWorld({ style, custom });
  const t = w.A.tokens();
  results[name] = { soft: t['on-accent-soft'], onAccent: w.A.contrast(t['on-accent'], t.accent),
                    soft_ratio: w.A.contrast(t['on-accent-soft'], t.accent) };
}
console.log(JSON.stringify(results));
"""
    harness = tmp_path / "accent_hints.cjs"
    harness.write_text(script, encoding="utf-8")
    result = subprocess.run(["node", str(harness), str(STATIC / "themes.css"), str(STATIC / "appearance-boot.js"), "[]"],
                            check=True, capture_output=True, text=True, timeout=30)
    out = json.loads(result.stdout)
    assert out["textOnly"]["soft"] != "#f1c8c0"
    for name, case in out.items():
        # A mid-tone accent can leave even button text below 4.5:1 (Settings reports that); hints are never worse.
        assert case["soft_ratio"] >= min(4.5, case["onAccent"]), (name, case)
        if name != "midAccent":
            assert case["soft_ratio"] >= 4.5, (name, case)


# ---------------------------------------------------------------- review fixes (OPUSUI1f3)
@pytest.mark.parametrize("style", STYLES)
def test_hovered_inactive_builder_step_hints_are_readable(style):
    """Hovering an inactive step paints it --cf-tile; its .75rem faint hints were 4.22:1 on that in Night Lacquer."""
    tokens = style_block(style)
    css = (STATIC / "styles.css").read_text(encoding="utf-8")
    fill = _resolve(_rule_body(css, ".owner-step:hover:not(:disabled)")["background"], tokens, {}, tokens["--cf-bg"])
    hint = _resolve(_rule_body(css, ".owner-step:hover:not(:disabled):not(.is-active) small")["color"], tokens, {}, fill)
    assert fill == tokens["--cf-tile"]
    assert _contrast(hint, fill) >= 4.5, (style, hint, fill, round(_contrast(hint, fill), 2))
    # Settings checks the same pair, so its all-clear covers this surface (and warns for custom colours).
    assert (hint == tokens["--cf-muted"]) and ("muted", "tile") in {(fg, bg) for fg, bg, _ in SETTINGS_PAIRS}


SETTINGS_HARNESS = NODE_HARNESS[:NODE_HARNESS.index("function makeWorld")] + r"""
const settings = fs.readFileSync(process.argv[4], 'utf8');
// One page load of the main page with Settings > Appearance; `store` is the browser's storage for this device.
function loadPage(store, refuseWrites) {
  const attrs = {}, inline = {};
  const el = () => {
    const handlers = {}, classes = new Set();
    return { value: '', checked: false, disabled: false, textContent: '', dataset: {}, handlers,
             classList: { toggle: (c, on) => (on ? classes.add(c) : classes.delete(c)), contains: c => classes.has(c) },
             addEventListener: (type, fn) => { handlers[type] = fn; }, replaceChildren() {}, appendChild() {}, append() {},
             fire(type) { handlers[type]({}); } };
  };
  const ids = {};
  const document = {
    documentElement: { setAttribute: (k, v) => { attrs[k] = String(v); }, removeAttribute: k => { delete attrs[k]; },
                       style: { setProperty: (k, v) => { inline[k] = v; }, removeProperty: k => { delete inline[k]; } } },
    getElementById: id => (ids[id] = ids[id] || Object.assign(el(), { querySelectorAll: () => [] })),
    createElement: () => el(),
  };
  const localStorage = {
    getItem: k => (k in store ? store[k] : null),
    setItem: (k, v) => { if (refuseWrites) throw new Error('QuotaExceededError'); store[k] = v; },
  };
  const window = { addEventListener() {}, matchMedia: () => ({ matches: false }) };
  const getComputedStyle = () => ({ getPropertyValue: n => (n in inline ? inline[n] : (blocks[attrs['data-theme'] || 'lacquer'][n] || '')) });
  for (const src of [boot, settings]) new Function('window', 'document', 'localStorage', 'getComputedStyle', src)(window, document, localStorage, getComputedStyle);
  const state = () => ({ message: ids.appearanceSaveState.textContent, undo: !ids.appearanceUndo.disabled,
                         font: attrs['data-heading-font'] || null, stored: store['tianxia.appearance.v1'] ? JSON.parse(store['tianxia.appearance.v1']).headingFont : null });
  return { ids, state };
}
const out = {};
const store = { 'tianxia.appearance.v1': JSON.stringify({ style: 'lacquer', custom: {}, headingFont: 'cinzel' }) };
// Storage full: reading works, writing throws.
let page = loadPage(store, true);
page.ids.appearanceHeadingFont.value = 'marcellus';
page.ids.appearanceHeadingFont.fire('change');
page.ids.appearanceSave.fire('click');
out.refused = page.state();
out.reload = loadPage(store, true).state();
// Storage working again: the same save is kept and reported as saved.
page = loadPage(store, false);
page.ids.appearanceHeadingFont.value = 'marcellus';
page.ids.appearanceHeadingFont.fire('change');
page.ids.appearanceSave.fire('click');
out.saved = page.state();
out.reloadSaved = loadPage(store, false).state();
console.log(JSON.stringify(out));
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_settings_reports_a_save_the_browser_refused(tmp_path):
    """Review case: with a saved look and storage full, Save said "Saved on this device." and disabled Undo; reload lost the choice."""
    harness = tmp_path / "settings_save.cjs"
    harness.write_text(SETTINGS_HARNESS, encoding="utf-8")
    result = subprocess.run(["node", str(harness), str(STATIC / "themes.css"), str(STATIC / "appearance-boot.js"),
                             str(STATIC / "appearance-settings.js")], check=True, capture_output=True, text=True, timeout=30)
    out = json.loads(result.stdout)
    refused = out["refused"]
    assert refused["message"].startswith("Couldn't save on this device"), refused
    assert "Saved on this device" not in refused["message"]
    assert refused["undo"] is True                       # the preview is still unsaved, so Undo stays available
    assert refused["font"] == "marcellus" and refused["stored"] == "cinzel"
    assert out["reload"]["font"] == "cinzel" and out["reload"]["undo"] is False
    assert out["saved"]["message"] == "Saved on this device." and out["saved"]["undo"] is False
    assert out["saved"]["stored"] == "marcellus" and out["reloadSaved"]["font"] == "marcellus"
