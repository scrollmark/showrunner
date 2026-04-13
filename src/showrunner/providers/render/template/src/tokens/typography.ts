import { preset } from "./preset.generated";
import type { TypeRole, TypeRoleKey } from "./schema";

// Resolve a typography role into a ready-to-spread CSSProperties object.
// Scene code MUST route all text styling through this helper rather than
// hardcoding fontSize / fontWeight / fontFamily.
export function typeStyle(role: TypeRoleKey): React.CSSProperties {
  const t: TypeRole = preset.typography[role];
  const style: React.CSSProperties = {
    fontFamily: `"${t.family}"`,
    fontWeight: t.weight,
    fontSize: t.size,
    lineHeight: t.lineHeight,
  };
  if (t.tracking !== undefined) style.letterSpacing = `${t.tracking}em`;
  if (t.uppercase) style.textTransform = "uppercase";
  if (t.italic) style.fontStyle = "italic";
  return style;
}

export const typography = preset.typography;
