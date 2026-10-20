import { GraduationCap, Home, School, Users, type LucideIcon } from "lucide-react";

import type { Me } from "@/lib/types";

export type NavItem = { to: string; label: string; icon: LucideIcon };

/** Student: Home. Teacher: Classes, Students. Admin adds Teachers. */
export function navItems(me: Me): NavItem[] {
  if (me.role === "student") return [{ to: "/", label: "Home", icon: Home }];
  const items: NavItem[] = [
    { to: "/classes", label: "Classes", icon: School },
    { to: "/students", label: "Students", icon: GraduationCap },
  ];
  if (me.is_admin) items.push({ to: "/teachers", label: "Teachers", icon: Users });
  return items;
}
