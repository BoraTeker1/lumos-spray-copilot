"use client";

import { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Leaf, Sprout, ClipboardList, MessageSquare, PanelLeft } from "lucide-react";
import { Sheet, SheetContent, SheetTitle, SheetTrigger } from "@/components/ui/sheet";
import { cn } from "@/lib/utils";

const MAIN_NAV = [
  { href: "/", label: "Farms", icon: Sprout },
  { href: "/pilot/new", label: "Pilot setup", icon: ClipboardList },
];
const BOTTOM_NAV = [{ href: "/feedback", label: "Feedback", icon: MessageSquare }];

const DISCLAIMER =
  "Decision support only. Always confirm PHI, REI, rates, crop use, and restrictions with the product label and a licensed PCA / agronomist.";

function isActive(pathname, href) {
  if (href === "/") return pathname === "/" || pathname.startsWith("/farms");
  return pathname === href || pathname.startsWith(`${href}/`);
}

function NavLink({ item, pathname, collapsed, onNavigate }) {
  const active = isActive(pathname, item.href);
  const Icon = item.icon;
  return (
    <Link
      href={item.href}
      onClick={onNavigate}
      title={collapsed ? item.label : undefined}
      className={cn(
        "flex items-center gap-2.5 rounded-md px-2.5 py-2 text-sm font-medium transition-colors",
        active ? "bg-gray-100 text-gray-900" : "text-gray-600 hover:bg-gray-50 hover:text-gray-900",
        collapsed && "justify-center px-0"
      )}
    >
      <Icon className="h-4 w-4 shrink-0" />
      {!collapsed && <span>{item.label}</span>}
    </Link>
  );
}

function Brand({ collapsed }) {
  return (
    <Link href="/" className="flex items-center gap-2 px-1">
      <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-leaf text-white">
        <Leaf className="h-4 w-4" />
      </span>
      {!collapsed && (
        <span className="min-w-0">
          <span className="block truncate text-sm font-semibold text-gray-900">
            Lumos Spray Copilot
          </span>
          <span className="block text-[11px] leading-tight text-gray-500">
            Decision &amp; compliance
          </span>
        </span>
      )}
    </Link>
  );
}

function SidebarNav({ pathname, collapsed = false, onNavigate }) {
  return (
    <>
      <nav className="flex flex-1 flex-col gap-1 px-2 py-3">
        {MAIN_NAV.map((item) => (
          <NavLink
            key={item.href}
            item={item}
            pathname={pathname}
            collapsed={collapsed}
            onNavigate={onNavigate}
          />
        ))}
      </nav>
      <nav className="flex flex-col gap-1 border-t border-gray-200 px-2 py-3">
        {BOTTOM_NAV.map((item) => (
          <NavLink
            key={item.href}
            item={item}
            pathname={pathname}
            collapsed={collapsed}
            onNavigate={onNavigate}
          />
        ))}
      </nav>
    </>
  );
}

// Global application frame: collapsible sidebar on desktop, sheet sidebar on
// mobile, one decision-support disclaimer in the footer.
export default function AppShell({ children }) {
  const pathname = usePathname();
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);

  return (
    <div className="flex min-h-screen">
      {/* Desktop sidebar */}
      <aside
        className={cn(
          "sticky top-0 hidden h-screen flex-col border-r border-gray-200 bg-white transition-[width] duration-150 md:flex",
          collapsed ? "w-14" : "w-60"
        )}
      >
        <div className={cn("border-b border-gray-200 px-2 py-3", collapsed && "px-1.5")}>
          <Brand collapsed={collapsed} />
        </div>
        <SidebarNav pathname={pathname} collapsed={collapsed} />
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        {/* Top bar: mobile nav trigger + desktop collapse toggle */}
        <header className="sticky top-0 z-40 flex h-12 items-center gap-2 border-b border-gray-200 bg-white px-3">
          <Sheet open={mobileOpen} onOpenChange={setMobileOpen}>
            <SheetTrigger
              className="rounded-md p-1.5 text-gray-500 hover:bg-gray-100 hover:text-gray-900 md:hidden"
              aria-label="Open navigation"
            >
              <PanelLeft className="h-4 w-4" />
            </SheetTrigger>
            <SheetContent side="left" className="p-0">
              <SheetTitle className="sr-only">Navigation</SheetTitle>
              <div className="flex h-full flex-col">
                <div className="border-b border-gray-200 px-2 py-3">
                  <Brand collapsed={false} />
                </div>
                <SidebarNav pathname={pathname} onNavigate={() => setMobileOpen(false)} />
              </div>
            </SheetContent>
          </Sheet>
          <button
            onClick={() => setCollapsed((v) => !v)}
            className="hidden rounded-md p-1.5 text-gray-500 hover:bg-gray-100 hover:text-gray-900 md:inline-flex"
            aria-label="Toggle sidebar"
          >
            <PanelLeft className="h-4 w-4" />
          </button>
          <span className="text-sm font-semibold text-gray-900 md:hidden">
            Lumos Spray Copilot
          </span>
        </header>

        <main className="flex-1 px-4 py-5 md:px-6">
          <div className="mx-auto w-full max-w-6xl">{children}</div>
        </main>

        <footer className="border-t border-gray-200 bg-white px-4 py-2.5 text-xs text-gray-500 md:px-6">
          {DISCLAIMER}
        </footer>
      </div>
    </div>
  );
}
