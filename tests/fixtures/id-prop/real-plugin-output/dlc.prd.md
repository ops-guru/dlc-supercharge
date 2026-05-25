# Product Requirements Document — Feedback Collector (excerpt)

Verbatim heading style from the live `/dlc:analyze-requirements` skill
(captured 2026-05-25 from `.dlc/feedback-collector/requirements.prd.md`):
**h3 (`###`) headings** with **em-dash (`—`, U+2014)** separators.

## 5. Functional Requirements

### FR-1 — Serve the feedback form on `GET /`
**Priority:** Must · **Source:** Req 1 AC1

**Acceptance criteria:**
- A GET request to `/` returns the Feedback_Form HTML with HTTP **200**.

### FR-2 — Email validation (RFC 5322 server-side)
**Priority:** Must · **Source:** Req 2 AC2

**Acceptance criteria:**
- Email must conform to RFC 5322 address syntax.
- Validation is performed server-side on POST `/feedback`.

## 6. Non-Functional Requirements

### NFR-1 — Accessibility (WCAG 2.1 AA)
**Priority:** Must

**Acceptance criteria:**
- Form satisfies WCAG 2.1 success criteria 1.3.1, 2.4.7, 1.4.3.
