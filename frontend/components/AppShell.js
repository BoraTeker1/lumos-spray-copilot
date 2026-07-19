"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Building2,
  CalendarClock,
  ClipboardList,
  Droplets,
  Eye,
  FileCheck,
  LayoutDashboard,
  Leaf,
  MessageSquare,
  PanelLeft,
  ShieldCheck,
  ShoppingCart,
  Sprout,
} from "lucide-react";
import { Sheet, SheetContent, SheetTitle, SheetTrigger } from "@/components/ui/sheet";
import { FarmProvider, useFarmContext } from "@/lib/farm-context";
import { cn } from "@/lib/utils";

// Sidebar sections. Every farm-scoped page reads the active farm from
// FarmProvider; /internal stays deliberately unlinked (operator tooling).
// The primary group IS the wedge — the pre-spray decision loop (scout → check →
// review → apply → evidence). Everything else, including the Phase-1 procurement
// module, lives in the secondary group: reachable, never co-equal.
const MAIN_NAV = [
  { href: "/", label: "Operations", icon: LayoutDashboard, exact: true },
  { href: "/farms", label: "Farms & fields", icon: Sprout },
  { href: "/decisions", label: "Decisions", icon: ShieldCheck },
  { href: "/scouting", label: "Scouting", icon: Eye },
  { href: "/applications", label: "Applications", icon: Droplets },
  { href: "/evidence", label: "Evidence & compliance", icon: FileCheck },
];
const BOTTOM_NAV = [
  { href: "/inputs", label: "Inputs & finance", icon: ShoppingCart },
  { href: "/pilot/new", label: "Pilot setup", icon: ClipboardList },
  { href: "/feedback", label: "Feedback", icon: MessageSquare },
];

const DISCLAIMER =
  "Decision support only. Always confirm PHI, REI, rates, crop use, and restrictions with the product label and a licensed PCA / agronomist.";

function isActive(pathname, item) {
  if (item.exact) return pathname === item.href;
  return pathname === item.href || pathname.startsWith(`${item.href}/`);
}

function NavLink({ item, pathname, collapsed, onNavigate }) {
  const active = isActive(pathname, item);
  const Icon = item.icon;
  return (
    <Link
      href={item.href}
      onClick={onNavigate}
      title={collapsed ? item.label : undefined}
      className={cn(
        // Active route: subtle green pill. Keyboard focus: blue focus-visible ring
        // ONLY (mouse clicks never leave a persistent outline).
        "flex items-center gap-2.5 rounded-md px-2.5 py-1.5 text-sm font-medium transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-1",
        active
          ? "bg-leaf-50 text-leaf-700 ring-1 ring-inset ring-green-200"
          : "text-gray-600 hover:bg-gray-50 hover:text-gray-900",
        collapsed && "justify-center px-0"
      )}
    >
      <Icon className={cn("h-4 w-4 shrink-0", active && "text-leaf-700")} />
      {!collapsed && <span>{item.label}</span>}
    </Link>
  );
}

function Brand({ collapsed }) {
  return (
    <Link href="/" className="flex items-center gap-2 px-1">
      <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-leaf text-white">
        <Leaf className="h-4 w-4" />
      </span>
      {!collapsed && (
        <span className="min-w-0">
          <span className="block truncate text-sm font-semibold text-gray-900">Lumos</span>
          <span className="block text-[11px] leading-tight text-gray-500">Spray Copilot</span>
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

// Farm switcher chip — real farms from /farms-overview (secondary demo farms
// excluded by the shared visibility rule). A styled native select: zero deps,
// keyboard- and mobile-friendly.
function FarmSwitcher() {
  const { farms, activeFarm, setActiveFarmId } = useFarmContext();
  if (!farms.length) return null;
  return (
    <label className="hidden items-center gap-1.5 rounded-full border border-gray-200 bg-white py-1 pl-2.5 pr-1 text-xs text-gray-700 sm:inline-flex">
      <Building2 className="h-3.5 w-3.5 shrink-0 text-gray-400" />
      <select
        aria-label="Active farm"
        value={activeFarm?.id ?? ""}
        onChange={(e) => setActiveFarmId(e.target.value)}
        className="max-w-[180px] cursor-pointer truncate bg-transparent pr-1 text-xs font-medium focus:outline-none"
      >
        {farms.map((f) => (
          <option key={f.id} value={f.id}>
            {f.name}
          </option>
        ))}
      </select>
    </label>
  );
}

// Today's date chip — rendered after mount only (SSR-safe).
function DateChip() {
  const [today, setToday] = useState(null);
  useEffect(() => {
    setToday(
      new Date().toLocaleDateString("en-GB", {
        day: "numeric",
        month: "short",
        year: "numeric",
      })
    );
  }, []);
  if (!today) return null;
  return (
    <span className="hidden items-center gap-1.5 rounded-full border border-gray-200 bg-white px-2.5 py-1 text-xs font-medium text-gray-700 sm:inline-flex">
      <CalendarClock className="h-3.5 w-3.5 text-gray-400" />
      {today}
    </span>
  );
}

function ShellFrame({ children }) {
  const pathname = usePathname();
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);

  return (
    <div className="flex min-h-screen">
      {/* Desktop sidebar */}
      <aside
        className={cn(
          "sticky top-0 hidden h-screen flex-col border-r border-gray-200 bg-white transition-[width] duration-150 md:flex",
          collapsed ? "w-[72px]" : "w-[248px]"
        )}
      >
        <div className={cn("border-b border-gray-200 px-2 py-3", collapsed && "px-1.5")}>
          <Brand collapsed={collapsed} />
        </div>
        <SidebarNav pathname={pathname} collapsed={collapsed} />
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        {/* Top bar: nav triggers left, farm switcher + date right */}
        <header className="sticky top-0 z-40 flex h-16 items-center gap-2 border-b border-gray-200 bg-white px-3 md:px-6">
          <Sheet open={mobileOpen} onOpenChange={setMobileOpen}>
            <SheetTrigger
              className="rounded-md p-1.5 text-gray-500 hover:bg-gray-100 hover:text-gray-900 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 md:hidden"
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
            className="hidden rounded-md p-1.5 text-gray-500 hover:bg-gray-100 hover:text-gray-900 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 md:inline-flex"
            aria-label="Toggle sidebar"
          >
            <PanelLeft className="h-4 w-4" />
          </button>
          <span className="text-sm font-semibold text-gray-900 md:hidden">
            Lumos Spray Copilot
          </span>
          <div className="ml-auto flex items-center gap-2">
            <FarmSwitcher />
            <DateChip />
          </div>
        </header>

        <main className="flex-1 px-4 py-6 md:px-8">
          <div className="mx-auto w-full max-w-6xl">{children}</div>
        </main>

        <footer className="border-t border-gray-200 bg-white px-4 py-2.5 text-xs text-gray-500 md:px-6">
          {DISCLAIMER}
        </footer>
      </div>
    </div>
  );
}

// Global application frame: collapsible sidebar on desktop, sheet sidebar on
// mobile, one decision-support disclaimer in the footer.
export default function AppShell({ children }) {
  return (
    <FarmProvider>
      <ShellFrame>{children}</ShellFrame>
    </FarmProvider>
  );
}
