# Motion & Interaction Design Specification

**Product:** Research Copilot Agent  
**Design System:** Clarity Light — Flagship Commercial Edition  

---

## 1. Motion Choreography Principles

Motion in Research Copilot Agent communicates **spatial continuity, intellectual focus, and product craft**. Every transition is derived from physical optics and precision instruments—immediate when triggered by the user, unhurried when staging flagship storytelling.

1. **Spatial Continuity:** Elements enter from and exit toward their logical origin (e.g., the Agent Inspector slides from the right edge; citations link directly to their source fragment).
2. **Staggered Hierarchy:** Flagship headlines, supporting copy, and layered product compositions reveal in a disciplined 60–90ms stagger rather than all at once.
3. **Scroll-Driven Storytelling:** In the Flagship Presentation (`AboutFlagship`), sticky showcase sequences and 3D exploded-view layers respond directly to scroll progression.
4. **Performance & Restraint:** Only GPU-composited properties (`transform`, `opacity`, `filter`) are animated. Decorative ambient lighting pauses automatically when outside the viewport via `IntersectionObserver`.

---

## 2. Calibrated Timing & Easing System

| Tier | Token | Duration | Easing Curve | Primary Usage |
| :--- | :--- | :--- | :--- | :--- |
| **Immediate Feedback** | `state-change` | `120ms` (`80–150ms`) | `cubic-bezier(0.2, 0, 0, 1)` | Button press, focus ring, citation chip highlight |
| **Standard Interaction** | `standard-interaction` | `200ms` (`150–250ms`) | `cubic-bezier(0.2, 0, 0, 1)` | Document selection crossfade, tab switch, dropdowns |
| **Panel Transition** | `panel-slide` | `280ms` (`250–350ms`) | `cubic-bezier(0.16, 1, 0.3, 1)` | Agent Inspector expand/collapse, sidebar rail |
| **Surface Mount** | `surface-enter` | `360ms` | `cubic-bezier(0.16, 1, 0.3, 1)` | Modal dialog entrance, empty-state reveal |
| **Brand Sequence** | `brand-transition` | `560ms` (`400–800ms`) | `cubic-bezier(0.16, 1, 0.3, 1)` | Flagship hero choreography, spatial layer morphing |
| **Expressive Spring** | `--ease-spring` | `220ms` | `cubic-bezier(0.34, 1.36, 0.64, 1)` | Exploded-view layer separation & tactile snap |

---

## 3. Intelligent Research & Flagship Sequences

- **Cinematic Sticky Showcase:** As the reader scrolls through the Flagship Presentation, a sticky product stage morphs smoothly between *Hybrid Inquiry*, *Page-Level Reader*, and *Agent Inspector* without jarring page jumps.
- **Spatial Exploded View:** Separates the 4 architectural UI layers (Navigation Rail, Research Stream, Knowledge Base Fragment, Agent Inspector) along the Z-axis with depth-aware shadows.
- **Citation-to-Source Choreography:** Hovering or clicking an inline citation (`[Vaswani et al., p. 4]`) highlights the corresponding source reference and previews its extracted fragment.
- **Streaming & Execution States:** SSE response streaming and Agent Inspector timeline updates animate smoothly without layout thrashing.
- **Reduced Motion (`prefers-reduced-motion: reduce`):** All 3D perspective shifts, parallax, and spatial translations collapse to clean `150ms` opacity crossfades.
