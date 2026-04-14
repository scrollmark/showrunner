"""Static checks on LLM-generated scene TSX.

Prompt rules are only a quality floor if something mechanically enforces
them. This module scans a scene's source for the anti-patterns the
codegen prompt forbids and returns human-readable violations that feed
into the retry loop.

The checks are deliberately shallow regex — they catch the common
amateur-output patterns (hex literals, inline fontSize, bare
interpolate) without pretending to be a full parser.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class LintViolation:
    rule: str
    line_number: int
    snippet: str
    explanation: str


# A line is skipped if the *source* line (pre-strip) is a JS/TSX
# single-line comment, a JSX comment block on its own line, or blank.
_COMMENT_OR_BLANK = re.compile(r"^\s*(//|/\*|\*|$)")

_DEFAULT_EXPORT = re.compile(r"^\s*export\s+default\b", re.MULTILINE)
_HEX_LITERAL = re.compile(r"#[0-9a-fA-F]{3,8}\b")
_RAW_EASING_USE = re.compile(r"\bEasing\s*\.")
# Large fixed-pixel widths inside scene code (width: 800, width: 1200) overflow
# the illustration slot when it ends up smaller than expected. 400 is the
# threshold — smaller values are plausibly decorations (icons, badges).
_LARGE_FIXED_WIDTH = re.compile(r"\bwidth\s*:\s*([4-9]\d{2}|[1-9]\d{3,})\b")
_LAYOUT_IMPORT = re.compile(
    r'import\s*{[^}]*\b(?P<name>CenterStack|Hero|StatBig|BulletList|Quote|Comparison|TitleOverContent)\b'
    r'[^}]*}\s*from\s*[\'"]\.\./layouts[\'"]'
)
_FONT_FAMILY_STRING = re.compile(r"fontFamily\s*:\s*['\"]")
# Literal numeric value after `fontSize:` / `fontWeight:`. JSX expressions
# like `fontSize: typography.title.size` or `fontSize: {...}` don't start
# with a digit, so they never match.
_FONT_SIZE_NUMBER = re.compile(r"\bfontSize\s*:\s*\d+")
_FONT_WEIGHT_NUMBER = re.compile(r"\bfontWeight\s*:\s*\d+")
# Bare `interpolate(` calls with no easing: option. Multiline-aware.
# Matches the call-site opening through its closing paren, rejects if
# no `easing:` key is found in the options object.
_INTERPOLATE_CALL = re.compile(r"\binterpolate\s*\(", re.MULTILINE)

_ALLOWED_HEX_CONTEXTS = (
    "filter: ",  # rare: drop-shadow(...) color literals — allowed for now
)


def _line_is_skipped(line: str) -> bool:
    return bool(_COMMENT_OR_BLANK.match(line))


def lint_scene(code: str) -> list[LintViolation]:
    """Return the list of lint violations in the given scene source."""
    violations: list[LintViolation] = []
    lines = code.splitlines()

    # Whole-file check: the composer's Root.tsx imports scenes as default
    # imports. A file with only `export const X` silently renders as
    # `undefined` and the Remotion render fails with React error #130.
    if not _DEFAULT_EXPORT.search(code):
        violations.append(LintViolation(
            rule="missing-default-export",
            line_number=len(lines),
            snippet="(end of file)",
            explanation=(
                "Scene file has no `export default` — Root.tsx imports this scene "
                "as a default import, so a named-only export renders as undefined "
                "at runtime. Add `export default <ComponentName>;` at the end of the file."
            ),
        ))

    # Whole-file check: every scene MUST use a layout primitive from
    # ../layouts. Hand-rolled flex + padding + AbsoluteFill produced
    # overlapping text in every prior render; the library encapsulates
    # all of that. Allowed layouts: CenterStack, Hero, StatBig,
    # BulletList, Quote, Comparison, TitleOverContent.
    if not _LAYOUT_IMPORT.search(code):
        violations.append(LintViolation(
            rule="missing-layout-import",
            line_number=1,
            snippet="(file header)",
            explanation=(
                "Scene must import at least one layout from `../layouts` "
                "(CenterStack, Hero, StatBig, BulletList, Quote, Comparison, "
                "or TitleOverContent) and return it as the default export's "
                "root element. Hand-rolled <AbsoluteFill>+flex layouts are "
                "no longer supported — they produced overlap bugs."
            ),
        ))

    for i, raw in enumerate(lines, start=1):
        line = raw.strip()
        if _line_is_skipped(raw):
            continue

        # R9: no large fixed-pixel widths. Illustration slots have variable
        # pixel sizes depending on aspect ratio and how much vertical space
        # the title uses; a `width: 1200` terminal overflows when the slot
        # ends up smaller than 1200 and gets clipped.
        for m in _LARGE_FIXED_WIDTH.finditer(line):
            violations.append(LintViolation(
                rule="no-large-fixed-width",
                line_number=i, snippet=line,
                explanation=(
                    f"Fixed pixel width `{m.group(0)}` inside scene code will "
                    f"overflow its layout slot when aspect / title size pushes "
                    f"the container smaller. Use `width: '100%'` on your "
                    f"outermost illustration element and relative units "
                    f"(percentages, flex: 1, svg viewBox) for inner sizing."
                ),
            ))

        # R8: no raw `Easing.*` calls — LLMs hallucinate methods that don't
        # exist (e.g. `Easing.step(2)`) which crashes the render. All easing
        # must flow through `curve('name')` from ../tokens, which is the
        # curated, type-checked set.
        if _RAW_EASING_USE.search(line):
            violations.append(LintViolation(
                rule="no-raw-easing",
                line_number=i, snippet=line,
                explanation=(
                    "Direct `Easing.*` call. Remotion's Easing module is a minefield "
                    "of names that look right but aren't — use `curve('out-cubic')` "
                    "(or another named curve) from ../tokens instead."
                ),
            ))

        # R1: no hardcoded hex colors
        for m in _HEX_LITERAL.finditer(line):
            ctx = line
            if any(allowed in ctx for allowed in _ALLOWED_HEX_CONTEXTS):
                continue
            violations.append(LintViolation(
                rule="no-hardcoded-color",
                line_number=i, snippet=line,
                explanation=f"Hex color `{m.group(0)}` must come from `colors.*` (imported from ../tokens), not be inlined.",
            ))

        # R2 + R5: no inline fontFamily string literal
        if _FONT_FAMILY_STRING.search(line):
            violations.append(LintViolation(
                rule="no-inline-font-family",
                line_number=i, snippet=line,
                explanation="Inline `fontFamily: '...'` — use `typeStyle('body')` etc. from ../tokens.",
            ))

        # R2: no hardcoded fontSize
        if _FONT_SIZE_NUMBER.search(line):
            violations.append(LintViolation(
                rule="no-hardcoded-font-size",
                line_number=i, snippet=line,
                explanation="Hardcoded `fontSize: N` — use `typeStyle(role)` from ../tokens.",
            ))

        # R2: no hardcoded fontWeight
        if _FONT_WEIGHT_NUMBER.search(line):
            violations.append(LintViolation(
                rule="no-hardcoded-font-weight",
                line_number=i, snippet=line,
                explanation="Hardcoded `fontWeight: N` — use `typeStyle(role)` from ../tokens.",
            ))

    # R4: each `interpolate(` call must name an easing: option, OR the
    # call must be inside a motion-kit hook (but we only see scene code
    # here — motion-kit lives in a sibling module, so any `interpolate`
    # in scene code is scene-authored and must declare easing).
    for m in _INTERPOLATE_CALL.finditer(code):
        start = m.start()
        # Find the matching closing paren of this call.
        depth = 0
        i = m.end() - 1
        close = -1
        while i < len(code):
            if code[i] == "(":
                depth += 1
            elif code[i] == ")":
                depth -= 1
                if depth == 0:
                    close = i
                    break
            i += 1
        if close == -1:
            continue  # unbalanced, let tsc complain
        call_body = code[start:close + 1]
        if "easing:" not in call_body:
            line_number = code[:start].count("\n") + 1
            snippet = code.splitlines()[line_number - 1].strip()
            violations.append(LintViolation(
                rule="no-bare-interpolate",
                line_number=line_number, snippet=snippet,
                explanation=(
                    "`interpolate(...)` without `easing:` produces linear motion. "
                    "Use a motion-kit hook (`useEnter`, `useExit`, `usePulse`) or pass "
                    "`{ easing: curve('out-cubic'), extrapolateLeft: 'clamp', extrapolateRight: 'clamp' }`."
                ),
            ))

    return violations


def format_violations(violations: list[LintViolation]) -> str:
    """Render a list of violations for inclusion in the LLM retry prompt."""
    if not violations:
        return ""
    lines = [f"Found {len(violations)} design-system violation(s):"]
    for v in violations:
        lines.append(f"  [line {v.line_number}] {v.rule}: {v.explanation}")
        lines.append(f"      > {v.snippet}")
    return "\n".join(lines)
