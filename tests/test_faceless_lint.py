from showrunner.formats.faceless_explainer.lint import (
    format_violations,
    lint_scene,
)


CLEAN_SCENE = """
import React from "react";
import { CenterStack } from "../layouts";

export default function Scene() {
  return (
    <CenterStack
      title="Hello"
      body="A minimal scene using a layout primitive."
    />
  );
}
""".strip()


def test_lint_accepts_clean_scene():
    assert lint_scene(CLEAN_SCENE) == []


def test_lint_catches_hex_literal():
    # CLEAN_SCENE doesn't have colors.background; inject a hex in the body.
    code = CLEAN_SCENE.replace('title="Hello"', 'title="#ffffff"')
    violations = lint_scene(code)
    assert any(v.rule == "no-hardcoded-color" for v in violations)


def test_lint_catches_missing_layout_import():
    no_layout = """
import React from "react";
import { AbsoluteFill } from "remotion";
import { colors } from "../tokens";

export default function Scene() {
  return <AbsoluteFill style={{ background: colors.background }} />;
}
""".strip()
    violations = lint_scene(no_layout)
    assert any(v.rule == "missing-layout-import" for v in violations)


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
import { CenterStack } from "../layouts";
const x = interpolate(frame, [0, 30], [0, 1], {
    easing: curve("out-cubic"),
});

export default function Scene() { return <CenterStack title="x" />; }
""".strip()
    assert lint_scene(ok) == []


def test_lint_skips_comment_lines():
    code = """
// fontFamily: "Inter"
// fontSize: 48
import { CenterStack } from "../layouts";
const ok = "not a violation";

export default function Scene() { return <CenterStack title="x" />; }
""".strip()
    assert lint_scene(code) == []


def test_lint_catches_raw_easing_call():
    bad = """
import { Easing } from "remotion";
import { CenterStack } from "../layouts";
const x = interpolate(frame, [0, 30], [0, 1], {
  easing: Easing.step(2),
});

export default function Scene() { return <CenterStack title="x" />; }
""".strip()
    violations = lint_scene(bad)
    assert any(v.rule == "no-raw-easing" for v in violations)


def test_lint_catches_missing_default_export():
    named_only = """
import React from "react";
import { CenterStack } from "../layouts";
export const Foo: React.FC = () => <CenterStack title="x" />;
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
