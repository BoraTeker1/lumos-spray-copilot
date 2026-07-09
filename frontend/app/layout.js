import "./globals.css";
import AppShell from "@/components/AppShell";

export const metadata = {
  title: "Lumos Spray Copilot",
  description:
    "AI-assisted, PCA/agronomist-in-the-loop pesticide decision and compliance copilot for specialty crops.",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body className="min-h-screen">
        <AppShell>{children}</AppShell>
      </body>
    </html>
  );
}
