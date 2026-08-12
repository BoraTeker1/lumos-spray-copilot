"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Building2,
  CalendarClock,
  ClipboardList,
  Droplets,
  Ellipsis,
  Eye,
  FileCheck,
  Landmark,
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
//
// The group headings mirror that hierarchy: TODAY is what you act on now,
// FARM OPERATIONS is the loop itself, RECORDS is what the loop produced.
const NAV_GROUPS = [
  {
    label: "Today",
    items: [{ href: "/", label: "Operations", icon: LayoutDashboard, exact: true }],
  },
  {
    label: "Farm operations",
    items: [
      { href: "/farms", label: "Farms & fields", icon: Sprout },
      { href: "/decisions", label: "Decisions", icon: ShieldCheck },
      { href: "/scouting", label: "Scouting", icon: Eye },
      { href: "/applications", label: "Applications", icon: Droplets },
    ],
  },
  {
    label: "Records",
    items: [
      { href: "/evidence", label: "Evidence & compliance", icon: FileCheck },
      // Financing is linked (2026-08-12), where the old lender console never was.
      // The difference is what it now shows: an evidence package assembled from the
      // farm's own records, which is useful on the day it is opened. The old page
      // was four tables that all refused until a lender document was transcribed.
      { href: "/financing", label: "Financing", icon: Landmark },
    ],
  },
];
const BOTTOM_NAV = [
  { href: "/inputs", label: "Inputs & procurement", icon: ShoppingCart },
  { href: "/pilot/new", label: "Pilot setup", icon: ClipboardList },
  { href: "/feedback", label: "Feedback", icon: MessageSquare },
];

// The four routes that fit a phone's thumb reach. "More" opens the same drawer
// that already holds every route, so nothing becomes unreachable on mobile.
const MOBILE_NAV = [
  { href: "/", label: "Today", icon: LayoutDashboard, exact: true },
  { href: "/decisions", label: "Decisions", icon: ShieldCheck },
  { href: "/scouting", label: "Scouting", icon: Eye },
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
      aria-current={active ? "page" : undefined}
      className={cn(
        // Active route: subtle green pill. Keyboard focus: blue focus-visible ring
        // ONLY (mouse clicks never leave a persistent outline).
        "flex items-center gap-2.5 rounded-control px-2.5 py-2 text-sm font-medium transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-focus focus-visible:ring-offset-2",
        active
          ? "bg-leaf-50 text-leaf-700 ring-1 ring-inset ring-ok-line"
          : "text-muted hover:bg-canvas hover:text-ink",
        collapsed && "justify-center px-0"
      )}
    >
      <Icon className={cn("h-4 w-4 shrink-0", active && "text-leaf-700")} />
      {!collapsed && <span className="truncate">{item.label}</span>}
    </Link>
  );
}

function GroupLabel({ children, collapsed }) {
  if (collapsed) return <div className="mx-2 my-2 border-t border-line" aria-hidden />;
  return (
    <div className="px-2.5 pb-1 pt-3 text-[11px] font-semibold uppercase tracking-wider text-muted">
      {children}
    </div>
  );
}

function Brand({ collapsed }) {
  return (
    <Link
      href="/"
      className="flex items-center gap-2 rounded-control px-1 focus:outline-none focus-visible:ring-2 focus-visible:ring-focus focus-visible:ring-offset-2"
    >
      <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-card bg-leaf text-white">
        <Leaf className="h-4 w-4" />
      </span>
      {!collapsed && (
        <span className="min-w-0">
          <span className="block truncate text-sm font-semibold text-ink">Lumos</span>
          <span className="block text-[11px] leading-tight text-muted">Spray Copilot</span>
        </span>
      )}
    </Link>
  );
}

function SidebarNav({ pathname, collapsed = false, onNavigate }) {
  return (
    <>
      <nav className="flex flex-1 flex-col gap-0.5 overflow-y-auto px-2 pb-3">
        {NAV_GROUPS.map((group) => (
          <div key={group.label} className="flex flex-col gap-0.5">
            <GroupLabel collapsed={collapsed}>{group.label}</GroupLabel>
            {group.items.map((item) => (
              <NavLink
                key={item.href}
                item={item}
                pathname={pathname}
                collapsed={collapsed}
                onNavigate={onNavigate}
              />
            ))}
          </div>
        ))}
      </nav>
      <nav className="flex flex-col gap-0.5 border-t border-line px-2 py-3">
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
    <label className="hidden items-center gap-1.5 rounded-control border border-line bg-surface py-1.5 pl-2.5 pr-1 text-xs text-ink sm:inline-flex">
      <Building2 className="h-3.5 w-3.5 shrink-0 text-muted" />
      <select
        aria-label="Active farm"
        value={activeFarm?.id ?? ""}
        onChange={(e) => setActiveFarmId(e.target.value)}
        className="max-w-[200px] cursor-pointer truncate bg-transparent pr-1 text-xs font-medium text-ink focus:outline-none"
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
    <span className="tabular hidden items-center gap-1.5 rounded-control border border-line bg-surface px-2.5 py-1.5 text-xs font-medium text-ink sm:inline-flex">
      <CalendarClock className="h-3.5 w-3.5 text-muted" />
      {today}
    </span>
  );
}

// Bottom tab bar (small screens only). `.no-print` so it never reaches paper —
// the print CSS in globals.css hides aside/header/footer by tag, and this is a
// <nav> that would otherwise survive.
function MobileTabBar({ pathname, onMore }) {
  return (
    <nav
      aria-label="Primary"
      className="no-print fixed inset-x-0 bottom-0 z-40 flex border-t border-line bg-surface md:hidden"
    >
      {MOBILE_NAV.map((item) => {
        const active = isActive(pathname, item);
        const Icon = item.icon;
        return (
          <Link
            key={item.href}
            href={item.href}
            aria-current={active ? "page" : undefined}
            className={cn(
              "flex min-h-[56px] flex-1 flex-col items-center justify-center gap-0.5 text-[11px] font-medium transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-focus",
              active ? "text-leaf-700" : "text-muted"
            )}
          >
            <Icon className="h-5 w-5" aria-hidden />
            {item.label}
          </Link>
        );
      })}
      <button
        type="button"
        onClick={onMore}
        aria-label="More navigation"
        className="flex min-h-[56px] flex-1 flex-col items-center justify-center gap-0.5 text-[11px] font-medium text-muted transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-focus"
      >
        <Ellipsis className="h-5 w-5" aria-hidden />
        More
      </button>
    </nav>
  );
}

function ShellFrame({ children }) {
  const pathname = usePathname();
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);

  return (
    <div className="flex min-h-screen">
      {/* Skip link. There are 14 navigation links plus the farm switcher ahead of
          the content on every page, so a keyboard user previously tabbed through
          all of them on each navigation. Visible only when focused, and
          `.no-print` so it never reaches paper. */}
      <a
        href="#main-content"
        className="no-print sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-50 focus:rounded-control focus:bg-leaf-700 focus:px-4 focus:py-2 focus:text-sm focus:font-medium focus:text-white focus:outline-none focus:ring-2 focus:ring-focus focus:ring-offset-2"
      >
        Skip to main content
      </a>

      {/* Desktop sidebar. Must stay an <aside> — the print CSS hides it by tag. */}
      <aside
        className={cn(
          "sticky top-0 hidden h-screen flex-col border-r border-line bg-surface transition-[width] duration-150 md:flex",
          collapsed ? "w-[72px]" : "w-[248px]"
        )}
      >
        <div className={cn("border-b border-line px-2 py-3", collapsed && "px-1.5")}>
          <Brand collapsed={collapsed} />
        </div>
        <SidebarNav pathname={pathname} collapsed={collapsed} />
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        {/* Top bar: nav triggers left, farm switcher + date right.
            Must stay a <header> — the print CSS hides it by tag. */}
        <header className="sticky top-0 z-40 flex h-16 items-center gap-2 border-b border-line bg-surface px-3 md:px-6">
          <Sheet open={mobileOpen} onOpenChange={setMobileOpen}>
            <SheetTrigger
              className="rounded-control p-1.5 text-muted hover:bg-canvas hover:text-ink focus:outline-none focus-visible:ring-2 focus-visible:ring-focus md:hidden"
              aria-label="Open navigation"
            >
              <PanelLeft className="h-4 w-4" />
            </SheetTrigger>
            <SheetContent side="left" className="p-0">
              <SheetTitle className="sr-only">Navigation</SheetTitle>
              <div className="flex h-full flex-col">
                <div className="border-b border-line px-2 py-3">
                  <Brand collapsed={false} />
                </div>
                <SidebarNav pathname={pathname} onNavigate={() => setMobileOpen(false)} />
              </div>
            </SheetContent>
          </Sheet>
          <button
            onClick={() => setCollapsed((v) => !v)}
            className="hidden rounded-control p-1.5 text-muted hover:bg-canvas hover:text-ink focus:outline-none focus-visible:ring-2 focus-visible:ring-focus md:inline-flex"
            aria-label="Toggle sidebar"
          >
            <PanelLeft className="h-4 w-4" />
          </button>
          <span className="text-sm font-semibold text-ink md:hidden">
            Lumos Spray Copilot
          </span>
          <div className="ml-auto flex items-center gap-2">
            <FarmSwitcher />
            <DateChip />
          </div>
        </header>

        <main id="main-content" tabIndex={-1} className="flex-1 px-4 py-6 md:px-8">
          <div className="mx-auto w-full max-w-[1360px]">{children}</div>
        </main>

        {/* Bottom padding on mobile keeps the tab bar from covering the
            disclaimer — it is a legal notice, not decoration.
            Must stay a <footer> — the print CSS hides it by tag. */}
        <footer className="border-t border-line bg-surface px-4 py-2.5 pb-[76px] text-meta text-muted md:px-6 md:pb-2.5">
          {DISCLAIMER}
        </footer>
      </div>

      <MobileTabBar pathname={pathname} onMore={() => setMobileOpen(true)} />
    </div>
  );
}

// Global application frame: collapsible sidebar on desktop, sheet sidebar plus a
// bottom tab bar on mobile, one decision-support disclaimer in the footer.
export default function AppShell({ children }) {
  return (
    <FarmProvider>
      <ShellFrame>{children}</ShellFrame>
    </FarmProvider>
  );
}
