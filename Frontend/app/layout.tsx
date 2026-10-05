import type { Metadata } from "next";
import "./globals.css";
import { GreyAgentProvider } from "@/core/grey-agent";

export const metadata: Metadata = {
  title: "Grey — FYP Companion",
  description: "Discover a real-world FYP idea with evidence-backed guidance.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>
        {/*
          GreyAgentProvider is a client component that holds GreyUIState.
          It wraps the entire app so any page or component can read the
          current workflow stage and trigger actions.
        */}
        <GreyAgentProvider>
          <div className="flex h-screen overflow-hidden bg-gray-50">
            {/* Sidebar placeholder — populated in a future step */}
            <aside className="hidden md:flex w-56 flex-col border-r border-gray-200 bg-white px-4 py-6 shrink-0">
              <p className="text-sm font-semibold text-gray-900 mb-6">Grey</p>
              <nav className="flex flex-col gap-1 text-sm text-gray-500">
                <span className="px-2 py-1 rounded hover:bg-gray-100 cursor-pointer">
                  + New FYP
                </span>
                <span className="px-2 py-1 rounded text-gray-300">My Projects</span>
                <span className="px-2 py-1 rounded text-gray-300">Project Brain</span>
                <span className="px-2 py-1 rounded text-gray-300">Evidence</span>
                <span className="px-2 py-1 rounded text-gray-300">Proposal</span>
              </nav>
            </aside>

            {/* Main content area */}
            <main className="flex-1 flex flex-col overflow-hidden">
              {children}
            </main>
          </div>
        </GreyAgentProvider>
      </body>
    </html>
  );
}
