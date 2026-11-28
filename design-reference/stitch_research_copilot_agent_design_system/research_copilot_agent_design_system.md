---
name: "Research Copilot Agent — Flagship Commercial System"
description: "A bright, light-first, intellectually calm design system for an AI academic research copilot combining editorial product presentation with high-focus operational precision."
---

## Overview

Research Copilot Agent is a commercial-grade, local-first academic research environment designed for deep intellectual work. The visual identity balances **editorial flagship confidence** (for product presentation and the About experience) with **calm, high-legibility operational clarity** (for daily literature discovery, PDF inspection, and controllable agent execution).

- **Brand Personality:** Precise, authoritative, curious, and unhurried. Comparable to flagship professional tools from Apple, Microsoft, and Stripe—never a developer console, never a generic SaaS template, and free of sci-fi AI clichés.
- **Visual Language:** Inspired by connected knowledge, scientific discovery, and optical precision. Built on a bright, light-first foundation of warm and cool off-whites, restrained architectural hairlines, and a disciplined accent triad of deep Cobalt Blue, Cyan-Teal, and Iris Violet.
- **Theme Polarity:** Light-first by default. Expressive atmospheric gradients and layered product compositions are reserved for the flagship presentation and empty-state focal moments; operational surfaces remain crisp, flat, and distraction-free.

## Colors

The color system derives from a deep **Cobalt Blue** primary (`#0037B0` / `#1D4ED8`) for primary actions and intellectual focus, paired with a **Cyan-Teal** secondary (`#006780`) for knowledge retrieval and source citations, and a restrained **Iris Violet** tertiary (`#5800C0`) for agent routing and execution states.

- **Surfaces:** Pure white (`#FFFFFF`) for active reading canvases and input composers, stepping outward through cool-slate off-whites (`#F8F9FF`, `#EFF4FF`, `#E5EEFF`) to separate navigation, inspector panels, and secondary metadata without heavy borders.
- **Text & Ink:** Deep midnight slate (`#0B1C30`) for primary reading copy and headings; muted slate (`#434655`) for metadata, citations, and timestamps.
- **Semantic States:** Emerald green (`#006C4A`) for verified citations and completed tool runs, amber (`#904D00`) for pause/approval gates, and crimson (`#BA1A1A`) for import or connection failures.

```yaml
colors:
  light:
    primary: "#0037B0"
    on-primary: "#FFFFFF"
    primary-container: "#1D4ED8"
    on-primary-container: "#CAD3FF"
    secondary: "#006780"
    on-secondary: "#FFFFFF"
    secondary-container: "#76DCFF"
    on-secondary-container: "#006077"
    tertiary: "#5800C0"
    on-tertiary: "#FFFFFF"
    tertiary-container: "#712EDD"
    on-tertiary-container: "#DFCDFF"
    error: "#BA1A1A"
    on-error: "#FFFFFF"
    error-container: "#FFDAD6"
    on-error-container: "#93000A"
    background: "#F8F9FF"
    on-background: "#0B1C30"
    surface: "#F8F9FF"
    surface-dim: "#CBDBF5"
    surface-bright: "#F8F9FF"
    surface-container-lowest: "#FFFFFF"
    surface-container-low: "#EFF4FF"
    surface-container: "#E5EEFF"
    surface-container-high: "#DCE9FF"
    surface-container-highest: "#D3E4FE"
    on-surface: "#0B1C30"
    surface-variant: "#E0E1F4"
    on-surface-variant: "#434655"
    outline: "#747686"
    outline-variant: "#C4C5D7"
    inverse-surface: "#213145"
    inverse-on-surface: "#EAF1FF"
    inverse-primary: "#B7C4FF"
    shadow: "#000000"
    scrim: "#000000"
    warning: "#904D00"
    on-warning: "#FFFFFF"
    warning-container: "#FFDCC3"
    on-warning-container: "#2F1500"
    success: "#006C4A"
    on-success: "#FFFFFF"
    success-container: "#85F8C4"
    on-success-container: "#002114"
  dark:
    primary: "#B7C4FF"
    on-primary: "#002682"
    primary-container: "#1D4ED8"
    on-primary-container: "#CAD3FF"
    secondary: "#6CD3F7"
    on-secondary: "#003543"
    secondary-container: "#269DBE"
    on-secondary-container: "#001F29"
    tertiary: "#D3BBFF"
    on-tertiary: "#3F008D"
    tertiary-container: "#712EDD"
    on-tertiary-container: "#DFCDFF"
    error: "#FFB4AB"
    on-error: "#690005"
    error-container: "#93000A"
    on-error-container: "#FFDAD6"
    background: "#031427"
    on-background: "#D3E4FE"
    surface: "#031427"
    surface-dim: "#031427"
    surface-bright: "#2A3A4F"
    surface-container-lowest: "#000F21"
    surface-container-low: "#0B1C30"
    surface-container: "#102034"
    surface-container-high: "#1B2B3F"
    surface-container-highest: "#26364A"
    on-surface: "#D3E4FE"
    surface-variant: "#434655"
    on-surface-variant: "#C4C5D7"
    outline: "#8E90A0"
    outline-variant: "#434655"
    inverse-surface: "#D3E4FE"
    inverse-on-surface: "#213145"
    inverse-primary: "#2151DA"
    shadow: "#000000"
    scrim: "#000000"
    warning: "#FFB77D"
    on-warning: "#4D2600"
    warning-container: "#6E3900"
    on-warning-container: "#FFDCC3"
    success: "#68DBA9"
    on-success: "#003825"
    success-container: "#005137"
    on-success-container: "#85F8C4"
```

## Typography

Typography is anchored by **Geist** across editorial headlines and operational reading copy, paired with **Geist Mono** exclusively for model identifiers, token budgets, latency measurements, page coordinates, and code blocks.

- **Editorial Presentation:** Uses tight tracking (`-1.5px` to `-0.5px`) and deliberate line breaks (`text-balance`) on `display-lg` and `display-md` to achieve flagship product gravitas.
- **Operational Reading:** Research conversations and PDF source text use `body-lg` (`16px` / `26px` line height) and `body-md` (`14px` / `22px` line height) constrained to comfortable reading measures (`65ch`).
- **Technical Metadata:** Uses `mono-sm` and `mono-xs` with `tabular-nums` so token counts, latencies, and page numbers align cleanly.

```yaml
typography:
  display-lg:
    fontFamily: "Geist"
    fontSize: 56px
    fontWeight: 600
    lineHeight: 62px
    letterSpacing: -1.5px
  display-lg-mobile:
    fontFamily: "Geist"
    fontSize: 32px
    fontWeight: 600
    lineHeight: 38px
    letterSpacing: -0.75px
  display-md:
    fontFamily: "Geist"
    fontSize: 40px
    fontWeight: 600
    lineHeight: 46px
    letterSpacing: -1px
  display-md-mobile:
    fontFamily: "Geist"
    fontSize: 28px
    fontWeight: 600
    lineHeight: 34px
    letterSpacing: -0.5px
  headline-lg:
    fontFamily: "Geist"
    fontSize: 28px
    fontWeight: 600
    lineHeight: 34px
    letterSpacing: -0.5px
  headline-md:
    fontFamily: "Geist"
    fontSize: 22px
    fontWeight: 600
    lineHeight: 28px
    letterSpacing: -0.3px
  title-lg:
    fontFamily: "Geist"
    fontSize: 18px
    fontWeight: 600
    lineHeight: 24px
    letterSpacing: -0.2px
  title-md:
    fontFamily: "Geist"
    fontSize: 15px
    fontWeight: 600
    lineHeight: 22px
    letterSpacing: -0.1px
  body-lg:
    fontFamily: "Geist"
    fontSize: 16px
    fontWeight: 400
    lineHeight: 26px
    letterSpacing: 0px
  body-md:
    fontFamily: "Geist"
    fontWeight: 400
    fontSize: 14px
    lineHeight: 22px
    letterSpacing: 0px
  body-sm:
    fontFamily: "Geist"
    fontSize: 13px
    fontWeight: 400
    lineHeight: 19px
    letterSpacing: 0px
  label-lg:
    fontFamily: "Geist"
    fontSize: 14px
    fontWeight: 500
    lineHeight: 20px
    letterSpacing: 0px
  label-md:
    fontFamily: "Geist"
    fontSize: 12px
    fontWeight: 500
    lineHeight: 16px
    letterSpacing: 0.1px
  label-sm:
    fontFamily: "Geist"
    fontSize: 11px
    fontWeight: 500
    lineHeight: 14px
    letterSpacing: 0.2px
  mono-sm:
    fontFamily: "Geist Mono"
    fontSize: 13px
    fontWeight: 400
    lineHeight: 20px
    letterSpacing: 0px
  mono-xs:
    fontFamily: "Geist Mono"
    fontSize: 11px
    fontWeight: 500
    lineHeight: 16px
    letterSpacing: 0px
```

## Layout & Spacing

Designed primarily for desktop research workflows (`1440px` and `1920px` viewports) with responsive collapse for narrower viewports.

- **Application Shell:** A compact, persistent left navigation rail (`240px` expanded, `64px` collapsed) paired with a spacious main canvas and an optional, collapsible right-hand **Agent Inspector** (`360px` when open).
- **Flagship Presentation:** Uses a `1280px` max-width editorial grid with generous vertical rhythm (`64px`–`96px` section spacing) and asymmetrical 12-column compositions.
- **Grid Scale:** Strict `4px` / `8px` base unit across all padding, gaps, and component internals.

```yaml
spacing:
  gutter-xs: 4px
  gutter-sm: 8px
  gutter-md: 16px
  gutter-lg: 24px
  gutter-xl: 32px
  section: 64px
  page-margin: 32px
```

## Elevation & Depth

Hierarchy is established through **tonal surface stepping** and **architectural hairlines** (`1px solid outline-variant` at subtle opacity) rather than heavy drop shadows.

- **Operational Surfaces:** Flat tonal layers (`surface` `#F8F9FF` → `surface-container-lowest` `#FFFFFF` for primary reading cards and composers, `surface-container-low` `#EFF4FF` for sidebars and inspector panels).
- **Floating & Flagship Depth:** Popovers, modal dialogs, and layered product showcase mockups use extra-diffused, cool-tinted ambient shadows (`0 12px 32px -8px rgba(11, 28, 48, 0.08)` and `0 24px 64px -16px rgba(0, 55, 176, 0.10)`).
- **Controlled Translucency:** Reserved strictly for sticky presentation headers and floating command bars, never applied indiscriminately to every card or button.

## Shapes

Crisp, architectural corner radii that distinguish interactive controls from large editorial frames.

```yaml
rounded:
  sm: 6px
  DEFAULT: 8px
  md: 12px
  lg: 16px
  xl: 24px
  full: 9999px
```

## Motion & Micro-interaction

Motion reinforces intellectual clarity, spatial continuity, and flagship craft. It is orchestrated across five calibrated tiers, honoring `prefers-reduced-motion: reduce` and targeting 60 FPS via GPU-composited `transform` and `opacity` properties.

- **Immediate Feedback (`80–150ms`):** Tactile button press, citation chip hover, and focus ring transitions.
- **Standard Interactions (`150–250ms`):** Tab switching, document selection crossfades, and dropdown/menu reveals.
- **Panel Transitions (`250–350ms`):** Collapsible Agent Inspector, sidebar rail, and Knowledge Base fragment drawer slides.
- **Brand & Cinematic Sequences (`400–800ms` + scroll-driven):** Flagship hero typography choreography, sticky showcase morphing, and exploded-view spatial layer separation.
- **Expressive Spring:** Used selectively for spatial layer recombination and modal mount, never with exaggerated bounce.

```yaml
motion:
  state-change:
    duration: 120ms
    delay: 0ms
    timingFunction: cubic-bezier(0.2, 0, 0, 1)
  standard-interaction:
    duration: 200ms
    delay: 0ms
    timingFunction: cubic-bezier(0.2, 0, 0, 1)
  panel-slide:
    duration: 280ms
    delay: 0ms
    timingFunction: cubic-bezier(0.16, 1, 0.3, 1)
  surface-enter:
    duration: 360ms
    delay: 0ms
    timingFunction: cubic-bezier(0.16, 1, 0.3, 1)
  brand-transition:
    duration: 560ms
    delay: 0ms
    timingFunction: cubic-bezier(0.16, 1, 0.3, 1)
  surface-exit:
    duration: 160ms
    delay: 0ms
    timingFunction: cubic-bezier(0.4, 0, 1, 1)
```

## Voice & Content Strategy

- **Tone:** Calm, scholarly, and commercially credible. Speaks directly to researchers without hype ("10x", "Revolutionary", "Magic").
- **Capitalization:** Sentence case for headings, navigation items, and action labels; Title Case only for proper product/model names.
- **Action Labels:** Specific verb-noun phrases (`Open Workspace`, `Import PDF`, `Approve Tool Run`, `Export Markdown`).
- **Honest Capabilities:** Accurately reflects local-first, single-process execution, 20 MiB / 500-page PDF limits, hybrid retrieval, and OpenAI-compatible API configuration. No fabricated metrics, testimonials, or cloud SaaS claims.

## Components

Component implementations live as individual HTML sticker sheet files in
`components/`. Each file contains the canonical, styled HTML components with
`<!-- COMPONENT: name -->` comment markers. Read each file before use.

- **Badge** → `@components/badge.html` — `badge-numeric`, `badge-dot`
- **Button** → `@components/button.html` — `button-primary`, `button-icon`, `button-with-icon`
- **Card** → `@components/card.html` — `card-elevated`, `card-action`, `card-interactive`, `card-interactive-2`
- **Input Field** → `@components/input-field.html` — `input-field-text`, `input-field-icon`
- **Modal** → `@components/modal.html` — `modal-standard`, `modal-alert`, `modal-drawer`
- **Tabs** → `@components/tabs.html` — `tabs-horizontal`, `tabs-with-icon`
