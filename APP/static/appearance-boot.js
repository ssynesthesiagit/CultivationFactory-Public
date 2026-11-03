/* Tianxia appearance (owner 2026-10-04, OPUSUI1): the player's chosen style, saved on this device.
 *
 * Load as a plain (non-module) script in <head>, AFTER /static/themes.css and before page CSS:
 *   <link rel="stylesheet" href="/static/themes.css?v=ui1">
 *   <script src="/static/appearance-boot.js?v=ui1"></script>
 * It runs before first paint, so a page never flashes the wrong look. It sets on <html>:
 *   data-theme        lacquer | celestial | ember | classic   (themes.css has one block per style)
 *   data-heading-font cinzel | cormorant | marcellus           (only when the player overrides it)
 *   data-text-size    large | xlarge                           (only when not normal)
 *   data-motion       reduce                                   (player choice or the system setting)
 * and, for custom colours, inline --cf-* properties derived from the six colours the player picks.
 *
 * window.TianxiaAppearance is the small API used by Settings > Appearance and the table/sheet/map
 * editor style pickers: STYLES, load(), save(prefs), store(prefs) (false if the browser refused),
 * apply(prefs), setStyle(name), contrast(a, b),
 * tokens(), CUSTOM_KEYS, onChange(fn). Other tabs pick up saved changes through the storage event.
 */
(function () {
  "use strict";
  var KEY = "tianxia.appearance.v1";
  var STYLES = [
    { id: "lacquer", name: "Night Lacquer", note: "Black lacquer and vermilion" },
    { id: "celestial", name: "Celestial Court", note: "Midnight and gold" },
    { id: "ember", name: "Ember Forge", note: "Charred and orange" },
    { id: "classic", name: "Classic light", note: "The earlier cream and jade look" }
  ];
  var STYLE_IDS = STYLES.map(function (s) { return s.id; });
  // Older table / sheet skin names, so an old link or saved table choice still lands somewhere sensible.
  var LEGACY = { crimson: "lacquer", midnight: "celestial", jade: "classic", ivory: "classic" };
  var CUSTOM_KEYS = ["accent", "bg", "panel", "text", "debuff", "buff"];
  var FONTS = ["cinzel", "cormorant", "marcellus"];
  var SIZES = ["normal", "large", "xlarge"];
  var DERIVED = [
    "--cf-accent", "--cf-accent-hover", "--cf-accent-text", "--cf-on-accent", "--cf-on-accent-soft", "--cf-chip",
    "--cf-chip-text", "--cf-link", "--cf-link-hover", "--cf-focus", "--cf-deep-accent",
    "--cf-bg", "--cf-bg-deep", "--cf-deep-bg",
    "--cf-panel", "--cf-panel-2", "--cf-tile", "--cf-input", "--cf-line", "--cf-line-strong",
    "--cf-deep-panel", "--cf-deep-panel-2", "--cf-deep-line",
    "--cf-text", "--cf-muted", "--cf-faint", "--cf-deep-text", "--cf-deep-muted",
    "--cf-debuff", "--cf-debuff-bg", "--cf-debuff-text", "--cf-buff", "--cf-buff-bg", "--cf-buff-text"
  ];
  var root = document.documentElement;
  var listeners = [];

  function defaults() {
    return { style: "lacquer", custom: {}, headingFont: "", textSize: "normal", reduceMotion: false };
  }

  function clean(prefs) {
    var out = defaults();
    if (!prefs || typeof prefs !== "object") return out;
    var style = LEGACY[prefs.style] || prefs.style;
    if (STYLE_IDS.indexOf(style) >= 0) out.style = style;
    if (prefs.custom && typeof prefs.custom === "object") {
      CUSTOM_KEYS.forEach(function (k) {
        var v = String(prefs.custom[k] || "").toLowerCase();
        if (/^#[0-9a-f]{6}$/.test(v)) out.custom[k] = v;
      });
    }
    if (FONTS.indexOf(prefs.headingFont) >= 0) out.headingFont = prefs.headingFont;
    if (SIZES.indexOf(prefs.textSize) >= 0) out.textSize = prefs.textSize;
    out.reduceMotion = prefs.reduceMotion === true;
    return out;
  }

  function load() {
    try { return clean(JSON.parse(localStorage.getItem(KEY) || "null")); }
    catch (e) { return defaults(); }
  }

  // ---------------------------------------------------------------- colour maths (sRGB, like color-mix)
  function rgb(hex) {
    var h = String(hex || "").trim().replace("#", "");
    if (h.length === 3) h = h.replace(/./g, "$&$&");
    if (!/^[0-9a-fA-F]{6}$/.test(h)) return null;
    return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16)];
  }
  function hex(c) {
    return "#" + c.map(function (v) { return Math.max(0, Math.min(255, Math.round(v))).toString(16).padStart(2, "0"); }).join("");
  }
  // mix(a, b, p): p of a, the rest b (same as color-mix(in srgb, a p%, b)).
  function mix(a, b, p) {
    var x = rgb(a), y = rgb(b);
    return hex([0, 1, 2].map(function (i) { return x[i] * p + y[i] * (1 - p); }));
  }
  function luminance(c) {
    var v = rgb(c).map(function (x) { x /= 255; return x <= 0.03928 ? x / 12.92 : Math.pow((x + 0.055) / 1.055, 2.4); });
    return 0.2126 * v[0] + 0.7152 * v[1] + 0.0722 * v[2];
  }
  function contrast(a, b) {
    if (!rgb(a) || !rgb(b)) return 0;
    var la = luminance(a), lb = luminance(b);
    return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
  }
  function isDark(c) { return luminance(c) < 0.18; }
  // Move `colour` toward `toward` until it reaches `target` contrast against `against` (one colour,
  // or a list of the surfaces the text sits on: then it must reach `target` on every one of them).
  function readable(colour, against, toward, target) {
    var surfaces = [].concat(against);
    function worst(c) { return Math.min.apply(null, surfaces.map(function (s) { return contrast(c, s); })); }
    var out = colour;
    for (var i = 1; i <= 10 && worst(out) < target; i++) out = mix(toward, colour, i / 10);
    return out;
  }

  function styleValue(name) {
    return getComputedStyle(root).getPropertyValue(name).trim();
  }

  // The style's own values for the six player colours (custom colours cleared first).
  function baseColours() {
    DERIVED.forEach(function (n) { root.style.removeProperty(n); });
    return {
      accent: styleValue("--cf-accent"), bg: styleValue("--cf-bg"), panel: styleValue("--cf-panel"),
      text: styleValue("--cf-text"), debuff: styleValue("--cf-debuff"), buff: styleValue("--cf-buff")
    };
  }

  // Every token that depends on a custom colour, recomputed so the whole style stays coherent.
  function derive(custom, base) {
    var c = {}, t = {};
    CUSTOM_KEYS.forEach(function (k) { c[k] = custom[k] || base[k]; });
    if (!CUSTOM_KEYS.some(function (k) { return custom[k]; })) return t;
    var dark = isDark(c.bg);
    var black = "#000000", white = "#ffffff";
    if (custom.bg) {
      t["--cf-bg"] = c.bg;
      t["--cf-bg-deep"] = mix(dark ? black : "#3a3226", c.bg, dark ? 0.35 : 0.08);
      if (dark) t["--cf-deep-bg"] = mix(black, c.bg, 0.15);
    }
    if (custom.panel || custom.text || custom.bg) {
      t["--cf-panel"] = c.panel;
      t["--cf-panel-2"] = mix(c.text, c.panel, 0.03);
      t["--cf-tile"] = mix(c.text, c.panel, 0.06);
      t["--cf-input"] = mix(c.bg, c.panel, 0.5);
      t["--cf-line"] = mix(c.text, c.panel, 0.12);
      t["--cf-line-strong"] = mix(c.text, c.panel, 0.25);
      if (dark) {
        t["--cf-deep-panel"] = mix(c.bg, c.panel, 0.5);
        t["--cf-deep-panel-2"] = mix(c.text, c.panel, 0.04);
        t["--cf-deep-line"] = t["--cf-line"];
      }
    }
    if (custom.text || custom.bg || custom.panel) {
      t["--cf-text"] = c.text;
      // Secondary and faint text are small (labels, hints, captions), so both need 4.5:1 on panels and on the page;
      // secondary text also on tiles (hints of a hovered builder step).
      t["--cf-muted"] = readable(mix(c.text, c.panel, 0.74), [c.panel, c.bg, t["--cf-tile"]], c.text, 4.5);
      t["--cf-faint"] = readable(mix(c.text, c.panel, 0.56), [c.panel, c.bg], c.text, 4.5);
      if (dark) { t["--cf-deep-text"] = c.text; t["--cf-deep-muted"] = t["--cf-muted"]; }
    }
    if (custom.accent || custom.bg || custom.panel || custom.text) {
      var onAccent = contrast("#fff6f0", c.accent) >= contrast("#16110c", c.accent) ? "#fff6f0" : "#16110c";
      var accentText = readable(c.accent, c.panel, c.text, 4.5);
      t["--cf-accent"] = c.accent;
      t["--cf-accent-hover"] = mix(onAccent, c.accent, 0.12);
      t["--cf-accent-text"] = accentText;
      t["--cf-on-accent"] = onAccent;
      // Small hints on an accent fill (the active builder step): softer than button text but still 4.5:1.
      t["--cf-on-accent-soft"] = readable(mix(onAccent, c.accent, 0.75), c.accent, onAccent, 4.5);
      t["--cf-chip"] = mix(c.accent, c.bg, 0.22);
      t["--cf-chip-text"] = readable(accentText, t["--cf-chip"], c.text, 4.5);
      t["--cf-link"] = accentText;
      t["--cf-link-hover"] = mix(c.text, accentText, 0.4);
      t["--cf-focus"] = readable(mix(c.text, c.accent, 0.35), c.bg, c.text, 3);
      if (dark) t["--cf-deep-accent"] = accentText;
    }
    [["debuff", "--cf-debuff"], ["buff", "--cf-buff"]].forEach(function (pair) {
      var k = pair[0], name = pair[1];
      if (!(custom[k] || custom.panel || custom.text || custom.bg)) return;
      var fill = mix(c[k], c.panel, dark ? 0.28 : 0.16);
      t[name] = c[k];
      t[name + "-bg"] = fill;
      t[name + "-text"] = readable(mix(c[k], c.text, dark ? 0.55 : 0.75), fill, dark ? white : black, 4.5);
    });
    return t;
  }

  var current = null;

  function apply(prefs) {
    prefs = clean(prefs);
    current = prefs;
    root.setAttribute("data-theme", prefs.style);
    if (prefs.headingFont) root.setAttribute("data-heading-font", prefs.headingFont);
    else root.removeAttribute("data-heading-font");
    if (prefs.textSize !== "normal") root.setAttribute("data-text-size", prefs.textSize);
    else root.removeAttribute("data-text-size");
    var systemReduce = false;
    try { systemReduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches; } catch (e) { /* old browser */ }
    if (prefs.reduceMotion || systemReduce) root.setAttribute("data-motion", "reduce");
    else root.removeAttribute("data-motion");
    var base = baseColours();
    var tokens = derive(prefs.custom, base);
    Object.keys(tokens).forEach(function (n) { root.style.setProperty(n, tokens[n]); });
    listeners.forEach(function (fn) { try { fn(prefs); } catch (e) { /* a listener must not break the page */ } });
    return prefs;
  }

  // Keep `prefs` on this device. Returns false when the browser refuses (storage full or blocked).
  function store(prefs) {
    try { localStorage.setItem(KEY, JSON.stringify(clean(prefs))); return true; } catch (e) { return false; }
  }

  // Store and apply; the look still applies for this visit when storing fails (use store() to know).
  function save(prefs) {
    prefs = clean(prefs);
    store(prefs);
    return apply(prefs);
  }

  // Switch style (custom colours belong to a style, so they are cleared) and save.
  function setStyle(name) {
    var prefs = load();
    prefs.style = LEGACY[name] || name;
    prefs.custom = {};
    return save(prefs);
  }

  // The current resolved value of every --cf colour token (for previews and contrast checks).
  function tokens() {
    var cs = getComputedStyle(root), out = {};
    ["bg", "panel", "panel-2", "tile", "line", "text", "muted", "faint", "accent", "accent-text", "on-accent",
      "on-accent-soft", "chip", "chip-text", "link", "debuff", "debuff-bg", "debuff-text", "buff", "buff-bg", "buff-text",
      "deep-panel", "deep-text"].forEach(function (k) { out[k] = cs.getPropertyValue("--cf-" + k).trim(); });
    return out;
  }

  window.TianxiaAppearance = {
    KEY: KEY, STYLES: STYLES, CUSTOM_KEYS: CUSTOM_KEYS, LEGACY: LEGACY,
    load: load, save: save, store: store, apply: apply, setStyle: setStyle, clean: clean,
    contrast: contrast, mix: mix, tokens: tokens, baseColours: function () {
      var b = baseColours(); apply(current || load()); return b;
    },
    current: function () { return current || load(); },
    onChange: function (fn) { listeners.push(fn); }
  };

  apply(load());

  // Saved in another tab (Settings, the table's picker): follow it here too.
  window.addEventListener("storage", function (event) {
    if (event.key === KEY) apply(load());
  });
})();
