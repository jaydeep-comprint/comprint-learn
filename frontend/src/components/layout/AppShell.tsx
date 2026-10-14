import { GraduationCap, Menu } from "lucide-react";
import { useState } from "react";
import { Outlet } from "react-router";

import { navItems } from "@/components/layout/nav";
import { NavLinks } from "@/components/layout/NavLinks";
import { UserMenu } from "@/components/layout/UserMenu";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetDescription, SheetTitle } from "@/components/ui/sheet";
import { useMe } from "@/features/auth/useMe";

/** Top bar + left sidebar on desktop; hamburger sheet on phones. Rendered inside RequireAuth. */
export function AppShell() {
  const { data: me } = useMe();
  const [menuOpen, setMenuOpen] = useState(false);
  if (!me) return null;
  const items = navItems(me);

  return (
    <div className="flex min-h-dvh flex-col">
      <header className="sticky top-0 z-40 flex h-14 items-center gap-2 border-b bg-background/95 px-3 backdrop-blur print:hidden sm:px-4">
        <Button
          variant="ghost"
          size="icon"
          className="md:hidden"
          aria-label="Open menu"
          onClick={() => setMenuOpen(true)}
        >
          <Menu />
        </Button>
        <GraduationCap className="hidden size-5 md:block" aria-hidden />
        <span className="truncate font-semibold">{me.org.name}</span>
        <div className="ml-auto">
          <UserMenu me={me} />
        </div>
      </header>

      <Sheet open={menuOpen} onOpenChange={setMenuOpen}>
        <SheetContent side="left" className="p-4">
          <SheetTitle className="pr-8">{me.org.name}</SheetTitle>
          <SheetDescription className="sr-only">Navigation</SheetDescription>
          <NavLinks items={items} onNavigate={() => setMenuOpen(false)} />
        </SheetContent>
      </Sheet>

      <div className="flex flex-1">
        <aside className="hidden w-56 shrink-0 border-r p-3 md:block print:hidden">
          <NavLinks items={items} />
        </aside>
        <main className="min-w-0 flex-1 px-4 py-6 sm:px-6 print:p-0">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
