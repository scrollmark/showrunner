from showrunner.formats.faceless_explainer.lint import (
    format_violations,
    lint_scene,
)


CLEAN_SCENE = """
import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame } from "remotion";
import { colors, spacing, typeStyle, curve } from "../tokens";
import { useEnter } from "../motion";

export default function Scene() {
  const frame = useCurrentFrame();
  const enter = useEnter({ durationFrames: 15 });
  const y = interpolate(frame, [0, 30], [0, 100], {
    easing: curve("out-cubic"),
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  return (
    <AbsoluteFill style={{ background: colors.background, padding: spacing.lg }}>
      <h1 style={{ ...typeStyle("title"), color: colors.text, opacity: enter, transform: `translateY(${y}px)` }}>
        Hello
      </h1>
    </AbsoluteFill>
  );
}
""".strip()


def test_lint_accepts_clean_scene():
    assert lint_scene(CLEAN_SCENE) == []


def test_lint_catches_hex_literal():
    code = CLEAN_SCENE.replace("colors.background", '"#ffffff"')
    violations = lint_scene(code)
    assert any(v.rule == "no-hardcoded-color" for v in violations)


def test_lint_catches_inline_font_family():
    bad = 'const s = { fontFamily: "Inter", fontSize: 48 };'
    violations = lint_scene(bad)
    rules = {v.rule for v in violations}
    assert "no-inline-font-family" in rules
    assert "no-hardcoded-font-size" in rules


def test_lint_catches_hardcoded_font_weight():
    bad = "const s = { fontWeight: 700 };"
    violations = lint_scene(bad)
    assert any(v.rule == "no-hardcoded-font-weight" for v in violations)


def test_lint_catches_bare_interpolate():
    bad = """
const x = interpolate(frame, [0, 30], [0, 1]);
""".strip()
    violations = lint_scene(bad)
    assert any(v.rule == "no-bare-interpolate" for v in violations)


def test_lint_accepts_interpolate_with_easing():
    ok = """
const x = interpolate(frame, [0, 30], [0, 1], {
    easing: curve("out-cubic"),
});

export default function Scene() { return null; }
""".strip()
    assert lint_scene(ok) == []


def test_lint_skips_comment_lines():
    code = """
// fontFamily: "Inter"
// fontSize: 48
const ok = "not a violation";

export default function Scene() { return null; }
""".strip()
    assert lint_scene(code) == []


def test_lint_catches_raw_easing_call():
    bad = """
import { Easing } from "remotion";
const x = interpolate(frame, [0, 30], [0, 1], {
  easing: Easing.step(2),
});

export default function Scene() { return null; }
""".strip()
    violations = lint_scene(bad)
    assert any(v.rule == "no-raw-easing" for v in violations)


def test_lint_catches_missing_default_export():
    named_only = """
import React from "react";
export const Foo: React.FC = () => <div />;
""".strip()
    violations = lint_scene(named_only)
    assert any(v.rule == "missing-default-export" for v in violations)


def test_format_violations_empty():
    assert format_violations([]) == ""


def test_format_violations_rendered():
    violations = lint_scene('const bad = "#fff";')
    formatted = format_violations(violations)
    assert "no-hardcoded-color" in formatted
    assert "line 1" in formatted
