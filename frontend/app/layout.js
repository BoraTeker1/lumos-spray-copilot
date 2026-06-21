import "./globals.css";
import Link from "next/link";

export const metadata = {
  title: "Lumos Spray Copilot",
  description:
    "AI-assisted, agronomist-in-the-loop spray decisions for greenhouse tomatoes.",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body className="min-h-screen flex flex-col">
        <header className="border-b bg-white shadow-sm">
          <div className="mx-auto max-w-5xl px-4 py-3 flex items-center justify-between">
            <Link href="/" className="flex items-center gap-2">
              <span className="text-xl">🍅</span>
              <span className="text-lg font-semibold text-leaf">
                Lumos Spray Copilot
              </span>
            </Link>
            <span className="hidden sm:inline text-xs text-gray-500">
              Greenhouse tomato spray decisions · agronomist-in-the-loop
            </span>
          </div>
        </header>

        <main className="mx-auto w-full max-w-5xl flex-1 px-4 py-6">
          {children}
        </main>

        <footer className="border-t bg-white">
          <div className="mx-auto max-w-5xl px-4 py-3 text-xs text-gray-500">
            ⚠️ Cautious decision support only — not a prescription and not a
            diagnosis. Final spray decisions should be confirmed with a qualified
            agronomist.
          </div>
        </footer>
      </body>
    </html>
  );
}
