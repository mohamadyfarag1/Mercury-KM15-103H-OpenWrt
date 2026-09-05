# Horus UI Design System

This document describes the shared frontend design system used by both
`luci-app-horus-controller` and `luci-app-horus-client`. The system lives in
one file, `horus-theme.css`, which is **byte-identical** between the two
projects (only its directory name differs: `horus_controller/` vs
`horus_client/`). If you change one copy, copy the exact same change to the
other and diff to confirm.

Read [AI_AGENT_RULES.md](AI_AGENT_RULES.md) first — it covers the mechanics
(cache-busting, `!important` requirements) that keep this system actually
working on a real device. This document covers the design intent and the
class reference.

## Design intent

The previous theme was a generic Tailwind-slate palette (`#0066FF` primary
on `#f8fafc`/`#0f172a` neutrals) with dozens of hardcoded hex colors
scattered through the JS (mostly a leftover dark-only palette that became
unreadable in light mode). The current system:

- Uses CSS custom properties (`--h-*`) for every color, so light/dark
  theming is centralized and automatic (`prefers-color-scheme` +
  `[data-theme]` override for LuCI themes that set it explicitly).
- Picks a primary accent (`--h-primary`, a lapis/indigo blue with a violet
  gradient partner `--h-primary-2`) distinct from generic SaaS blue, used
  in a signature gradient (`--h-gradient`) for page headers and primary CTAs.
- Keeps semantic status colors (success/warning/error) separate from the
  brand accent, plus one additional semantic color, `--h-pending`
  (goldenrod), reserved specifically for "AP awaiting adoption" — this used
  to be a hardcoded `#ff9800` sprinkled through `map.js`.
- Never hardcodes a hex color in JS for anything themeable. If you're about
  to write `style="color:#..."` in a `.js` file, there should be a `--h-*`
  token or `.h-*` class for it already — check this file before adding a
  new hardcoded color.

## Token reference (light values; see the file for dark overrides)

| Token | Light value | Purpose |
|---|---|---|
| `--h-primary` / `--h-primary-hover` / `--h-primary-bg` | `#2C4BD4` / `#2340B8` / `#E8ECFC` | Brand accent, buttons, links, active states |
| `--h-primary-2` | `#5B2CC9` | Gradient partner, "info" tone |
| `--h-gradient` | `linear-gradient(135deg, --h-primary, --h-primary-2)` | Page headers, primary CTA backgrounds |
| `--h-success` / `--h-success-bg` | `#1E9E6B` / tint | Online/connected/good states |
| `--h-warning` / `--h-warning-bg` | `#D97706` / tint | Warnings, thresholds |
| `--h-error` / `--h-error-bg` | `#D64550` / tint | Offline/error/destructive actions |
| `--h-pending` / `--h-pending-bg` | `#A8790C` / tint | AP awaiting adoption — nothing else |
| `--h-bg` / `--h-bg-darker` | `#F5F7FB` / `#ECEFF6` | Page background, secondary surfaces |
| `--h-card-bg` / `--h-card-hover` | `#FFFFFF` / `#F0F3FA` | Card/panel surfaces |
| `--h-text-main` / `--h-text-muted` | `#131B2E` / `#4C5A7A` | Primary/secondary text |
| `--h-border` / `--h-border-strong` | `#DDE3F0` / `#C7D0E6` | Dividers, input borders |
| `--h-radius-sm/md/lg` | `4px` / `8px` / `12px` | Corner radii |
| `--h-shadow-sm/md` | — | Card / header elevation |

Dark mode redefines all of these under
`@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) {...} }`
and again under `:root[data-theme="dark"] {...}` so an explicit theme
toggle wins in both directions. **Never add a color that's only defined in
one of these blocks** — always define the light value on bare `:root` first.

## Component classes

**Layout:** `.horus-container` (base font/color/background reset — every
top-level view wrapper needs this class, including `.horus-settings-view`
and `.horus-ban-view`; missing it was itself a bug found this session),
`.h-page-header` (+ `-id`, `-icon`, `-title`, `-sub`, `-actions`) — the
gradient header used on `map.js` and `ban.js`, `.h-panel` (+ `-header`,
`-title`, `-desc`) — generic card, `.h-kpi-grid` / `.h-kpi-card` (+
`.tone-primary/success/error/warning/info` for the left accent border) —
dashboard summary cards.

**Status & badges:** `.h-status-dot` (+ `.h-status-online/offline/warning`),
`.h-badge` (+ `.h-badge-outline/secondary/success/error/warning/primary/
pending/2g/5g`).

**Tables:** `.h-table-wrapper`, `.h-table`.

**Buttons:** `.h-btn` (+ `.h-btn-primary/secondary/danger/success/warning/
pending/icon`, size modifiers `.h-btn-sm/lg`). `.h-btn-pending` is reserved
for the "activate this AP" call-to-action specifically.

**Forms:** `.h-input`, `.h-form-group`, `.h-form-label`.

**Tabs:** `.h-tabs` / `.h-tab` (+ `.active`) — note `.h-page-header .h-tabs`
and `.h-page-header .h-tab` are separately styled to read on the gradient
background instead of on a card background.

**Language toggle:** `.h-lang-toggle` — deliberately has two style contexts
(plain card vs `.h-page-header` gradient) via a nested selector, because it
appears in both. See `i18n.js`'s `buildLangBtn()`.

**Hero status card** (client's "am I connected" summary, promoted to the top
of the settings page instead of being buried in the form): `.h-hero` (+
`-id`, `-ring` with `.online/offline/pending`, `-name`, `-meta`, `-status`,
`-status-badge` with `.online/offline/pending`, `-status-sub`).

**Peer/neighbor cards** (replaces a raw HTML table for "nearby Horus APs"):
`.h-peer-list`, `.h-peer-card`, `-left`, `-icon`, `-name`, `-sub`, `-empty`.

**Injector cells & badges** — used by `horus_injector.js` on *native* LuCI
pages (e.g. Network > Wireless > Associated Stations) it decorates, which
are not wrapped in `.horus-container`: `.h-inj-cell`, `-row`, `-title` (+
`.tone-success/primary`), `-link`, `-chip` (+ `.tone-success/warning/
primary/muted`), `-mono`, `-muted`, `-badge` (+ `.tone-success/primary/
error/warning/muted`). These rules carry inline fallback color values
(`var(--h-primary, #2C4BD4)`) as a second safety net in case the global
stylesheet injection fails on a given native page for any reason.

**CBI form overrides** (`.horus-settings-view .cbi-*`) — see rule 5 in
[AI_AGENT_RULES.md](AI_AGENT_RULES.md): every declaration here needs
`!important`, and `.horus-settings-view .cbi-map > h2` /
`.cbi-map-descr` are suppressed because each settings view renders its own
`topBar` with the same title/description instead.

## Icons

No icon font or SVG sprite sheet — emoji are used directly (matching the
existing codebase convention throughout, e.g. `📡` for AP/network, `🔑` for
activation, `🛡️` for the ban/security page, `⚙️` for settings). Avoid
Unicode blocks with unreliable font coverage across admin browsers (e.g.
Egyptian hieroglyphs) — emoji have universal rendering support and are
already the established idiom here.
