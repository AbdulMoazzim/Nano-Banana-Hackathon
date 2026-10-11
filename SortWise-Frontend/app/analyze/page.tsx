import Link from "next/link";
import { Analyzer } from "@/components/Analyzer"; // adjust to your component
import { Reveal } from "@/components/Motion";
import { RedirectionButton } from "@/components/RedirectionButton";

export default function AnalyzePage() {
  return (
    <div className="flex min-h-screen flex-col">
      <header className="border-b">
        <div className="mx-auto flex h-14 max-w-5xl items-center justify-between px-4">
          <Link href="/" className="font-semibold tracking-tight">SortWise AI</Link>
          <RedirectionButton link="/" text="Back home"/>
        </div>
      </header>
      <main className="mx-auto w-full max-w-3xl flex-1 space-y-6 px-4 py-12">
        <Reveal className="space-y-1 text-center">
          <h1 className="text-3xl font-bold tracking-tight">Analyze an item</h1>
          <p className="text-sm text-muted-foreground">
            Upload one clear photo, with an optional description.
          </p>
        </Reveal>
        <Reveal delay={0.1}>
          <Analyzer />
        </Reveal>
      </main>
    </div>
  );
}