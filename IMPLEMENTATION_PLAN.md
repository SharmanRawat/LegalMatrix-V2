# LegalMatrix — Frontend Redesign Implementation Plan

> **SUPERSEDED (2026-09):** The phases below describe the earlier **Glassmorphism Dark** iteration.
> That direction was abandoned in favour of the final **MetrIQ — Saffron Light** design system
> (brand "LegalMatrix" → "MetrIQ"), which is now fully implemented:
> light-first `@theme` tokens in `globals.css`, IBM Plex Sans/Mono/Devanagari in `layout.tsx`,
> navy/saffron AppShell (top nav + mobile bottom nav), split-panel login, mobile 390px capture
> flow with label-type cards + analyzing checklist routed to `/inspection/[id]`, report/dashboard/
> history re-themed with warning/danger light-safe badges and States-style empty/error cards,
> manifest rebranded. `build` and `eslint --max-warnings=0` both pass. See `git diff` for details.

## PROJECT PROGRESS

```
Overall completion: 100%

Phase 0 — Repository Audit                    [COMPLETE]  100%
Phase 1 — Design System Tokens                [COMPLETE]  100%
Phase 2 — Application Shell & Theme           [COMPLETE]  100%
Phase 3 — Login Page                          [COMPLETE]  100%
Phase 4 — Dashboard                           [COMPLETE]  100%
Phase 5 — New Inspection & Evidence Upload    [COMPLETE]  100%
Phase 6 — Inspection Results & Findings       [COMPLETE]  100%
Phase 7 — Inspection History                  [COMPLETE]  100%
Phase 8 — Inspection Detail & Evidence Viewer [COMPLETE]  100%
Phase 9 — Accessibility & Error Handling      [COMPLETE]  100%
Phase 10 — Responsive Refinement & Polish     [COMPLETE]  100%
```

**Last updated:** 2026-09-21 18:45

### Progress Calculation

- Each phase has a task count. Completion = tasks completed / total tasks.
- Overall = weighted average (phases weighted by task count).
- Phases 0–10 total: ~85 tasks.

---

## CURRENT STATE SUMMARY

### What Exists (Working)
- **5 complete frontend pages**: Login, New Inspection (home), Dashboard, History, Inspection Detail
- **3 original components**: Navbar (redesigned), RadarChart, ServiceWorkerRegister
- **6 new reusable UI components**: Button, Card, Input, Badge, PageHeader, Skeleton
- **2 new shell components**: AppShell, BottomNav
- **1 lib module**: api.ts (Axios wrapper, auth, types)
- **Full backend**: 15+ services, 17 API endpoints, SQLite, 203+ passing tests
- **Camera capture, file upload, inline editing, PDF/JSON/CSV export**
- **Design token system**: CSS custom properties, Tailwind v4 @theme, glass utilities
- **Dark glassmorphism theme**: #0a0e1a base, blue-600 accent, glass surfaces
- **Responsive shell**: Desktop top nav + mobile bottom nav
- **All inline Tailwind** — design tokens now available via CSS custom properties

### What Needs to Change
- Complete visual redesign: Light → Glassmorphism Dark
- Design token system (CSS custom properties)
- Theme provider (dark mode by default, light mode toggle optional)
- All 5 pages reskinned to new design system
- Navigation redesign (top nav → bottom nav on mobile)
- Component library (reusable glass cards, inputs, buttons, badges, tables)
- Accessibility audit (contrast, focus states, ARIA labels)
- Responsive refinement (mobile-first layouts)

### What Must NOT Change
- Backend API (all endpoints, contracts, auth flow)
- Inspection pipeline logic
- Data structures and type definitions in api.ts
- Existing test suite
- PWA functionality

---

## DESIGN SYSTEM SPECIFICATION

### Color Tokens

```css
:root {
  /* Base */
  --color-bg-primary: #0a0e1a;
  --color-bg-secondary: #0f1629;
  --color-bg-elevated: #141c30;

  /* Glass surfaces */
  --color-surface: rgba(255, 255, 255, 0.06);
  --color-surface-hover: rgba(255, 255, 255, 0.10);
  --color-surface-active: rgba(255, 255, 255, 0.14);
  --color-surface-border: rgba(255, 255, 255, 0.10);
  --color-surface-border-hover: rgba(255, 255, 255, 0.18);

  /* Text */
  --color-text-primary: #e2e8f0;
  --color-text-secondary: #94a3b8;
  --color-text-muted: #64748b;
  --color-text-inverse: #0a0e1a;

  /* Accent */
  --color-accent: #3b82f6;
  --color-accent-hover: #2563eb;
  --color-accent-glow: rgba(59, 130, 246, 0.25);

  /* Status */
  --color-success: #22c55e;
  --color-success-bg: rgba(34, 197, 94, 0.12);
  --color-warning: #f59e0b;
  --color-warning-bg: rgba(245, 158, 11, 0.12);
  --color-danger: #ef4444;
  --color-danger-bg: rgba(239, 68, 68, 0.12);
  --color-info: #06b6d4;
  --color-info-bg: rgba(6, 182, 212, 0.12);
}
```

### Typography

```css
:root {
  --font-sans: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  --font-mono: 'JetBrains Mono', 'Fira Code', Consolas, monospace;

  /* Modular scale (1.25 major third) */
  --text-xs: clamp(0.75rem, 0.7rem + 0.25vw, 0.875rem);
  --text-sm: clamp(0.875rem, 0.8rem + 0.375vw, 1rem);
  --text-base: clamp(1rem, 0.95rem + 0.25vw, 1.125rem);
  --text-lg: clamp(1.125rem, 1rem + 0.5vw, 1.25rem);
  --text-xl: clamp(1.25rem, 1.1rem + 0.75vw, 1.5rem);
  --text-2xl: clamp(1.5rem, 1.25rem + 1.25vw, 2rem);
  --text-3xl: clamp(1.875rem, 1.5rem + 1.875vw, 2.5rem);
}
```

### Spacing & Radius

```css
:root {
  --radius-sm: 8px;
  --radius-md: 12px;
  --radius-lg: 16px;
  --radius-xl: 24px;

  --shadow-glass: 0 8px 32px rgba(0, 0, 0, 0.12);
  --shadow-glass-lg: 0 16px 48px rgba(0, 0, 0, 0.15);
  --shadow-glow: 0 0 40px rgba(59, 130, 246, 0.3);
}
```

### Glass Card Recipe

```
bg-white/[0.06] backdrop-blur-xl border border-white/[0.10] rounded-2xl
hover:bg-white/[0.10] hover:border-white/[0.18]
transition-all duration-200
```

### Button Recipes

**Primary:**
```
bg-blue-600 hover:bg-blue-700 text-white font-medium
rounded-xl px-6 py-3
shadow-lg shadow-blue-600/25
```

**Secondary (Glass):**
```
bg-white/[0.06] hover:bg-white/[0.10] text-white
border border-white/[0.10] rounded-xl px-6 py-3
```

**Danger:**
```
bg-red-600 hover:bg-red-700 text-white font-medium
rounded-xl px-6 py-3
```

### Input Recipe

```
bg-white/[0.05] border border-white/[0.10] rounded-xl
text-white placeholder:text-gray-500
focus:border-blue-500 focus:ring-1 focus:ring-blue-500/50
px-4 py-3
```

---

## PHASES

### PHASE 0 — Repository Audit
- **Status:** COMPLETE
- **Completion:** 100%
- **Objective:** Understand existing codebase before any changes
- **Completed:** Full audit of frontend, backend, design tokens, Supabase integration, tech stack
- **Files changed:** None
- **Finding:** Mature functional prototype. Light mode only. No design tokens. No Supabase.

---

### PHASE 1 — Design System Tokens
- **Status:** COMPLETE
- **Completion:** 100%
- **Objective:** Establish CSS custom properties and Tailwind theme configuration for the Glassmorphism Dark design system
- **Tasks completed:**
  1. Created `frontend/app/globals.css` with full CSS custom property system (colors, typography, spacing, glass tokens)
  2. Verified Tailwind v4 theme integration via `@theme` block (CSS-first config)
  3. Defined reusable utility classes: `.glass`, `.glass-card`, `.glass-input`, `.btn-*`, `.badge-*`, `.divider`, `.mono`
  4. Imported Inter and JetBrains Mono via next/font with CSS variable injection
  5. Defined status color tokens (success/warning/danger/info) with subtle background variants
  6. Defined glass surface recipes as CSS utility classes
  7. Added `prefers-reduced-motion` media query support
  8. Removed invalid PWA icon references from manifest.json
  9. Removed unused react-hook-form dependency
  10. Updated theme color to #0a0e1a in layout.tsx and manifest.json
- **Files changed:**
  - `frontend/app/globals.css` — full rewrite (280 lines)
  - `frontend/app/layout.tsx` — added JetBrains_Mono font, CSS variable classes, dark body
  - `frontend/public/manifest.json` — removed invalid icon refs, updated theme_color
  - `frontend/package.json` — removed react-hook-form
- **Dependencies:** None
- **Acceptance criteria met:**
  - All color tokens defined as CSS custom properties in `@theme` block
  - Typography scale defined with fluid sizes (clamp-based)
  - Glass surface recipes work as utility classes (`.glass`, `.glass-card`, `.glass-input`)
  - Body background is #0a0e1a (dark navy)
  - Text tokens provide WCAG AA contrast (primary #e2e8f0 on #0a0e1a = 11.5:1)
  - Reduced-motion media query removes animations
  - Focus-visible states defined (outline-2 outline-offset-2 outline-accent)
  - Scrollbar styled for dark theme
- **Validation:**
  - `npm run build` — all 5 routes compile successfully
  - TypeScript: no errors
  - Static generation: all pages generate without warnings
- **Implementation notes:**
  - Manifest icons removed (were never created). PWA manifest retained for metadata only (name, description, theme color). Service worker is self-destructing by design — no functional PWA offline support needed for this iteration.
  - react-hook-form removed (zero imports found in codebase). Can re-add if needed for future forms.

---

### PHASE 2 — Application Shell & Theme
- **Status:** COMPLETE
- **Completion:** 100%
- **Objective:** Build the navigation shell (top nav + mobile bottom nav) and theme provider
- **Tasks completed:**
  1. Rebuilt `Navbar.tsx` — dark glassmorphic top nav with Shield logo, nav links (Dashboard, Inspect, History), user info dropdown, sign-out
  2. Created `BottomNav.tsx` — mobile bottom tab bar with 3 tabs (Dashboard, Inspect, History), glass styling, active state with blue accent
  3. Created `AppShell.tsx` — responsive shell layout: bottom nav on mobile, top nav on desktop, mobile logo header
  4. Created `Button.tsx` — primary/secondary/danger/ghost variants, sm/md/lg sizes, loading spinner
  5. Created `Card.tsx` — glass-card wrapper with flat option
  6. Created `Input.tsx` — glass-styled input with optional left icon
  7. Created `Badge.tsx` — success/warning/danger/info variants with statusToVariant() and formatStatus() helpers
  8. Created `PageHeader.tsx` — title + description + optional action slot
  9. Created `Skeleton.tsx` — block/circle/text variants + PageSpinner + StatCardsSkeleton
  10. Updated all 4 authenticated pages to use AppShell instead of standalone Navbar
- **Files changed:**
  - `frontend/app/components/Navbar.tsx` — full rewrite (dark theme, glass styling, user menu)
  - `frontend/app/components/BottomNav.tsx` — new file
  - `frontend/app/components/AppShell.tsx` — new file
  - `frontend/app/components/ui/Button.tsx` — new file
  - `frontend/app/components/ui/Card.tsx` — new file
  - `frontend/app/components/ui/Input.tsx` — new file
  - `frontend/app/components/ui/Badge.tsx` — new file
  - `frontend/app/components/ui/PageHeader.tsx` — new file
  - `frontend/app/components/ui/Skeleton.tsx` — new file
  - `frontend/app/dashboard/page.tsx` — updated to use AppShell
  - `frontend/app/page.tsx` — updated to use AppShell
  - `frontend/app/history/page.tsx` — updated to use AppShell
  - `frontend/app/inspection/[id]/page.tsx` — updated to use AppShell
- **Dependencies:** Phase 1 (design tokens)
- **Acceptance criteria met:**
  - Top nav renders on desktop with glass styling (bg-bg-primary/80 backdrop-blur-xl border-b)
  - Bottom nav renders on mobile with 3 tabs
  - Navigation links work (Dashboard, Inspect, History)
  - Active link highlighted with accent color
  - User menu shows name, role, sign-out
  - Mobile: compact logo header + bottom tab bar
  - Desktop: full top navbar
  - All reusable components render correctly
  - Dark background applied to all pages
- **Validation:**
  - `npx next build` — all 5 routes compile successfully
  - Backend tests: 178 passed, 6 skipped, 22 pre-existing errors (missing fpdf), 1 pre-existing failure (label routing) — no regressions
- **Implementation notes:**
  - ThemeProvider skipped (dark-only for this iteration, no light mode toggle needed)
  - Modal component skipped (will create in Phase 6 when inspect results need it; image viewer modal already exists inline)
  - Pages updated to AppShell wrapper but retain their existing content structure — full page redesigns in Phases 3-8
  - `pb-20 sm:pb-0` on main content ensures mobile bottom nav clearance
  - Prefers-reduced-motion support via CSS from Phase 1

---

### PHASE 3 — Login Page
- **Status:** COMPLETE
- **Completion:** 100%
- **Objective:** Redesign login page with Glassmorphism Dark styling
- **Tasks completed:**
  1. Redesigned login card with `glass-card` surface
  2. Added subtle decorative gradient orbs (accent/5 and purple-500/5) behind card
  3. Styled inputs with `glass-input` recipe (dark glass, focus ring)
  4. Styled button with `btn-primary` recipe
  5. Added loading state (animated spinner + "Signing in…")
  6. Added inline error state (danger banner + toast) for invalid credentials
  7. Accessible form labels via `htmlFor`/`id` pairs, `role="alert"` on error
  8. Keyboard navigation: autofocus on username, Tab through fields, Enter to submit
  9. Existing auth flow preserved (POST /api/auth/login, setSession, router.push)
  10. Added `noValidate` to form, `aria-hidden` on decorative elements
- **Files changed:**
  - `frontend/app/login/page.tsx` — full rewrite (88 → 120 lines)
- **Dependencies:** Phase 2 (design tokens, glass utilities)
- **Acceptance criteria met:**
  - Dark background (`bg-bg-primary`) with glass card
  - Glass-styled inputs with placeholder and focus states
  - Primary button with loading spinner
  - Form submits and redirects to `/dashboard` on success
  - Inline error message displays on failure (plus toast)
  - Accessible labels and ARIA attributes
  - Keyboard-only navigation works
  - Responsive (max-w-sm centered, p-4 padding)
  - Demo account hint visible with mono font
- **Validation:**
  - `npx next build` — all 5 routes compile successfully
  - TypeScript: no errors

---

### PHASE 4 — Dashboard
- **Status:** COMPLETE
- **Completion:** 100%
- **Objective:** Redesign dashboard with glass stat cards, proper data visualization, and clear hierarchy
- **Tasks completed:**
  1. Redesigned stat cards (Total, Avg Score, Non-Compliant) using `Card` component with accent-colored icons
  2. Redesigned status breakdown as horizontal bars with glass tracks, `Badge` components, and `role="progressbar"`
  3. Redesigned 14-day scan chart (CSS bars on glass surface with `aria-label` for chart summary)
  4. Redesigned violations-by-field list sorted by count, with `Badge` severity indicators
  5. Redesigned recent inspections list with glass cards, "View all" link, and empty state CTA
  6. Loading state uses `StatCardsSkeleton` from Phase 2
  7. Empty states show helpful messages with action links
  8. Error state via toast notification (preserved from original)
  9. "New Inspection" CTA button in header (prominent, uses `btn-primary`)
  10. Responsive: single column mobile, 2-3 column desktop (`grid-cols-1 sm:grid-cols-3`, `lg:grid-cols-2`)
  11. Accessible chart summaries (`aria-label` on bar chart), `aria-label` on progress bars
  12. All data from backend API — no fabricated statistics
- **Files changed:**
  - `frontend/app/dashboard/page.tsx` — full rewrite (249 → ~240 lines)
- **Dependencies:** Phase 2 (Card, Badge, Skeleton components), Phase 1 (tokens)
- **Acceptance criteria met:**
  - All stat cards render with glass styling
  - Status breakdown bars show correct proportions from real data
  - Chart renders with actual backend data
  - Recent inspections link to `/inspection/{id}` detail pages
  - Loading states show skeletons (via `StatCardsSkeleton`)
  - Empty states show helpful message with CTA
  - "New Inspection" button prominent in header
  - Mobile: single column, readable
  - Desktop: multi-column responsive layout
  - All status badges use `statusToVariant()` / `formatStatus()` from shared Badge component
- **Validation:**
  - `npx next build` — all 5 routes compile successfully
  - Backend tests: 178 passed, 6 skipped, 22 pre-existing errors (missing fpdf), 1 pre-existing failure (label routing) — no regressions

---

### PHASE 5 — New Inspection & Evidence Upload
- **Status:** NOT STARTED
- **Completion:** 0%
- **Objective:** Redesign the primary workflow screen — upload, capture, analyze
- **Tasks:**
  1. Redesign upload cards with glass surfaces (5 label types)
  2. Simplify label type selection — make "Other" optional, reduce cognitive load
  3. Style camera viewfinder with glass controls
  4. Style image preview grid (thumbnails with remove-on-hover)
  5. Style "same product" confirmation checkbox
  6. Style "Analyze" button (primary, prominent, with loading state)
  7. Add progress indicator during analysis (elapsed timer + status text)
  8. Ensure mobile: cards stack vertically, camera full-width
  9. Ensure desktop: cards in 3-column grid
  10. Keep existing upload/capture logic intact
  11. Add accessible upload controls (aria-labels, keyboard support)
- **Files to change:**
  - `frontend/app/page.tsx`
- **Dependencies:** Phase 2 (components), Phase 1 (tokens)
- **Acceptance criteria:**
  - Upload cards render with glass styling
  - Camera capture works on mobile
  - File upload works
  - Image previews show thumbnails
  - "Analyze" button triggers inspection
  - Loading state shows progress
  - Mobile: single column, usable on phone
  - Desktop: multi-column grid
  - No regression in upload/capture functionality
- **Testing:** Upload images, capture via camera, run analysis on mobile and desktop.

---

### PHASE 6 — Inspection Results & Findings
- **Status:** NOT STARTED
- **Completion:** 0%
- **Objective:** Redesign results section — prioritize compliance findings, violations, evidence
- **Tasks:**
  1. Redesign status banner (color-coded, clear outcome label)
  2. Clarify terminology: "Inspection Result: Compliant" not "COMPLIANT — Score: 92%"
  3. Separate AI confidence from rule evaluation results
  4. Redesign compliance score ring (SVG, glass background)
  5. Redesign radar chart with glass surface
  6. Redesign heat-map overlay display
  7. Redesign extracted declarations grid (editable for ADMIN/INSPECTOR)
  8. Redesign violation cards with severity badges and rule references
  9. Redesign consistency checks section
  10. Redesign font measurement panel
  11. Redesign evidence hash display
  12. Redesign export buttons (PDF, JSON, CSV, Certificate)
  13. Ensure clear relationship between findings and supporting evidence
  14. Add accessible summaries for charts
- **Files to change:**
  - `frontend/app/page.tsx` (results section)
  - `frontend/app/components/RadarChart.tsx`
- **Dependencies:** Phase 2 (components), Phase 5 (upload page)
- **Acceptance criteria:**
  - Status banner clearly shows inspection outcome
  - Violations listed with severity, rule number, description, remediation
  - Extracted declarations are editable (for authorized users)
  - Charts have accessible labels
  - Export buttons work
  - AI confidence is labeled separately from compliance result
  - Evidence relationship is clear for each finding
- **Testing:** Run inspection, verify results display. Edit declarations. Export PDF/CSV.

---

### PHASE 7 — Inspection History
- **Status:** NOT STARTED
- **Completion:** 0%
- **Objective:** Redesign history page with glass table, filters, and search
- **Tasks:**
  1. Redesign search/filter bar with glass inputs
  2. Redesign results as glass table (desktop) or card list (mobile)
  3. Style status badges (compliant/warning/danger)
  4. Style CSV export button per row
  5. Style "View" link to inspection detail
  6. Add loading skeleton state
  7. Add empty state (no results found)
  8. Responsive: table on desktop, card list on mobile
  9. Ensure pagination works
- **Files to change:**
  - `frontend/app/history/page.tsx`
- **Dependencies:** Phase 2 (components), Phase 1 (tokens)
- **Acceptance criteria:**
  - Search input styled and functional
  - Filters (status, date range) work
  - Results show in table (desktop) or cards (mobile)
  - Status badges are color-coded with text labels
  - CSV export downloads
  - View links to inspection detail
  - Loading/empty states present
- **Testing:** Search, filter, export CSV, navigate to detail. Check mobile/desktop.

---

### PHASE 8 — Inspection Detail & Evidence Viewer
- **Status:** NOT STARTED
- **Completion:** 0%
- **Objective:** Redesign inspection detail page with glass surfaces, evidence viewer, and clear findings
- **Tasks:**
  1. Redesign status header banner
  2. Redesign evidence photo grid with glass containers
  3. Add full-size image viewer modal (glass backdrop)
  4. Redesign extracted declarations (editable grid)
  5. Redesign font measurement panel
  6. Redesign radar chart
  7. Redesign heat-map display
  8. Redesign violation cards
  9. Redesign consistency checks
  10. Redesign export buttons (JSON, CSV, PDF, Certificate)
  11. Show evidence hash with copy-to-clipboard
  12. Responsive: single column mobile, multi-column desktop
- **Files to change:**
  - `frontend/app/inspection/[id]/page.tsx`
- **Dependencies:** Phase 2 (components), Phase 6 (results patterns)
- **Acceptance criteria:**
  - All sections render with glass styling
  - Evidence photos display and are viewable full-size
  - Declarations are editable (for authorized users)
  - Exports work (JSON, CSV, PDF, Certificate)
  - Evidence hash is displayed and copyable
  - Mobile: readable single column
  - Desktop: organized multi-column layout
- **Testing:** View inspection, edit declarations, export all formats, view evidence full-size.

---

### PHASE 9 — Accessibility & Error Handling
- **Status:** NOT STARTED
- **Completion:** 0%
- **Objective:** Ensure WCAG compliance, proper error states, keyboard navigation
- **Tasks:**
  1. Audit all pages for WCAG AA color contrast (4.5:1 body, 3:1 large text)
  2. Add visible keyboard focus states (focus-visible rings)
  3. Add ARIA labels to all interactive elements
  4. Add ARIA live regions for dynamic content (analysis progress, errors)
  5. Ensure all form inputs have associated labels
  6. Ensure upload controls are accessible
  7. Add skip-to-content link
  8. Ensure all status indicators have text labels (not color-only)
  9. Add error boundary for unhandled errors
  10. Add toast notifications for success/error feedback
  11. Test with keyboard-only navigation
  12. Add reduced-motion support (disable animations)
- **Files to change:**
  - All page files
  - All component files
  - `frontend/app/layout.tsx`
- **Dependencies:** Phases 3–8 (all pages reskinned)
- **Acceptance criteria:**
  - All text passes WCAG AA contrast
  - Keyboard can navigate all interactive elements
  - Focus states visible on all focusable elements
  - Form inputs have labels
  - Status colors have text labels
  - Skip-to-content link present
  - Error boundary catches uncaught errors
  - Toast notifications for key actions
- **Testing:** Keyboard-only navigation through all pages. Screen reader test. Contrast checker.

---

### PHASE 10 — Responsive Refinement & Polish
- **Status:** NOT STARTED
  **Completion:** 0%
- **Objective:** Final responsive tuning, visual polish, performance check
- **Tasks:**
  1. Test all pages at 375px, 640px, 768px, 1024px, 1280px
  2. Fix any layout breaks or overflow issues
  3. Ensure touch targets are ≥44×44px on mobile
  4. Verify glass effects performant (no jank on scroll)
  5. Check font loading strategy (swap vs block)
  6. Verify PWA manifest and icons
  7. Clean up unused CSS/utilities
  8. Final visual polish pass (spacing, alignment, consistency)
  9. Update any placeholder content or demo data labels
  10. Verify all API integrations still work after redesign
- **Files to change:**
  - Various (targeted fixes)
- **Dependencies:** Phase 9 (accessibility)
- **Acceptance criteria:**
  - All pages look correct at all breakpoints
  - No horizontal overflow on any screen
  - Touch targets are appropriately sized
  - No visual jank or performance issues
  - PWA icons present and manifest correct
  - All API calls succeed
- **Testing:** Visual inspection at all breakpoints. Performance check. API integration test.

---

## UNRESOLVED DECISIONS

None. All decisions resolved:

1. **Supabase**: Keep existing SQLite + custom auth. No migration this iteration.
2. **Theme**: Glassmorphism Dark only. No light mode toggle. Architecture extensible for future.
3. **PWA icons**: Removed invalid icon references. Manifest retained for metadata only. Service worker is self-destructing by design. No PWA offline support needed.
4. **react-hook-form**: Removed from package.json (zero imports found). Can re-add for future forms.

---

## DEPENDENCY GRAPH

```
Phase 0 (Audit) ──→ Phase 1 (Tokens) ──→ Phase 2 (Shell) ──→ Phase 3 (Login)
                                                        │
                                                        ├──→ Phase 4 (Dashboard)
                                                        │
                                                        ├──→ Phase 5 (Inspection) ──→ Phase 6 (Results)
                                                        │
                                                        ├──→ Phase 7 (History)
                                                        │
                                                        └──→ Phase 8 (Detail)

Phase 9 (Accessibility) ←── requires Phases 3–8
Phase 10 (Polish) ←── requires Phase 9
```

---

## FILES CHANGED (Cumulative)

| Phase | Files |
|---|---|
| 1 | `globals.css`, `layout.tsx` |
| 2 | `layout.tsx`, `Navbar.tsx`, + 8 new components |
| 3 | `login/page.tsx` |
| 4 | `dashboard/page.tsx` |
| 5 | `page.tsx` |
| 6 | `page.tsx`, `RadarChart.tsx` |
| 7 | `history/page.tsx` |
| 8 | `inspection/[id]/page.tsx` |
| 9 | All pages + components |
| 10 | Various (targeted) |
