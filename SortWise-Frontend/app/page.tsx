
import { Reveal } from "@/components/Motion";
import { RedirectionButton } from "@/components/RedirectionButton";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import Image from "next/image";
import Link from "next/link";

const NAV = [
  { href: "/analyze", label: "Analyze" },
  { href: "#how-it-works", label: "How it works" },
  { href: "#categories", label: "Categories" },
  { href: "#limits", label: "Good to know" },
];

const STATS = [
  { value: "8", label: "Result categories" },
  { value: "3", label: "Condition checks" },
  { value: "10 MiB", label: "Max upload size" },
  { value: "4", label: "Image formats" },
];

const STEPS = [
  {
    step: "01",
    title: "Upload a photo",
    body: "Add a clear picture of one item. An optional description, such as “empty glass jar”, gives the model extra context.",
  },
  {
    step: "02",
    title: "Identify and inspect",
    body: "Vision models name the item and its material, then check separately for cracks, holes or leaks, and severe deformation.",
  },
  {
    step: "03",
    title: "Get guidance",
    body: "Disposal advice, preparation steps and warnings come from fixed rules in the backend, never from the model's own wording.",
  },
];

const CATEGORIES = [
  { name: "Plastic", note: "Bottles, containers, packaging film" },
  { name: "Paper / Cardboard", note: "Boxes, newspapers, paper bags" },
  { name: "Metal", note: "Cans, tins, foil, utensils" },
  { name: "Glass", note: "Jars, bottles, drinking glasses" },
  { name: "Organic", note: "Food scraps, garden waste" },
  { name: "Electronic", note: "Cables, chargers, small devices" },
  { name: "General waste", note: "Items that fit no recycling stream" },
  { name: "Unknown", note: "Shown whenever identification is unreliable" },
];

const LIMITS = [
  {
    title: "Confidence is an estimate",
    body: "The percentage is not measured accuracy. Anything below the backend's threshold is reported as unknown rather than guessed.",
  },
  {
    title: "Local rules always win",
    body: "Guidance is general. Recycling programs differ by city, so check your local waste authority before disposing.",
  },
  {
    title: "“Unable to assess” is not “fine”",
    body: "If condition checks fail or the photo is unclear, the result says so. It never implies an item is undamaged.",
  },
  {
    title: "Photo quality matters",
    body: "Use good light, keep the item centred, and avoid piles. One item per photo gives the most reliable result.",
  },
];

export default function Home() {
  return (
    <div className="flex min-h-screen flex-col">
      <header className="sticky top-0 z-10 border-b bg-background/80 backdrop-blur">
        <div className="mx-auto flex h-14 max-w-5xl items-center justify-between px-4">
          <div className="flex items-center relative">
            <Image
              height={70}
              width={70}
              src="/icon.png"
              alt="icon"
              className="w-[70px]"
            />
            <Link href="#top" className="font-semibold -ml-3">
              SortWise AI
            </Link>
          </div>
          <nav aria-label="Primary" className="hidden gap-6 text-sm sm:flex">
            {NAV.map((n) => (
              <Link
                key={n.href}
                href={n.href}
                className="text-muted-foreground transition-colors hover:text-foreground"
              >
                {n.label}
              </Link>
            ))}
          </nav>
        </div>
      </header>

      <main id="top" className="mx-auto w-full max-w-5xl flex-1 space-y-10 px-4 py-12">
        {/* Hero */}
        <section className="space-y-6 text-center" id="analyze">
          <Reveal><Badge variant="secondary">Waste identification assistant</Badge></Reveal>
          <Reveal delay={0.1}>
            <h1 className="text-4xl font-bold tracking-tight sm:text-5xl">
              Know what it is. Know how to sort it.
            </h1>
          </Reveal>
          <Reveal delay={0.2}>
            <p className="mx-auto max-w-2xl text-muted-foreground">
              Snap a photo of a waste item to identify it, check its visible
              condition, and get general sorting guidance.
            </p>
          </Reveal>
          <dl className="mx-auto grid max-w-2xl grid-cols-2 gap-4 pt-2 sm:grid-cols-4">
            {STATS.map((s, i) => (
              <Reveal key={s.label} delay={0.3 + i * 0.08} className="space-y-1">
                <dt className="text-2xl font-semibold">{s.value}</dt>
                <dd className="text-xs text-muted-foreground">{s.label}</dd>
              </Reveal>
            ))}
          </dl>
        </section>

        {/* Analyzer */}
        <section id="analyze">
          <RedirectionButton link="/analyze" text="Ready To Analyze" />
        </section>

        <Separator />

        {/* How it works */}
        <section id="how-it-works" className="scroll-mt-20 space-y-6">
          <div className="space-y-1">
            <h2 className="text-2xl font-semibold tracking-tight">
              How it works
            </h2>
            <p className="text-sm text-muted-foreground">
              Three steps from photo to guidance.
            </p>
          </div>
          <div className="grid gap-4 md:grid-cols-3">

            {STEPS.map((s, i) => (
              <Reveal key={s.step} delay={i * 0.1} className="h-full">
                <Card key={s.step} className="h-full">
                  <CardHeader>
                    <span className="font-mono text-xs text-muted-foreground">
                      {s.step}
                    </span>
                    <CardTitle>{s.title}</CardTitle>
                  </CardHeader>
                  <CardContent className="text-sm text-muted-foreground">
                    {s.body}
                  </CardContent>
                </Card>
              </Reveal>
            ))}
          </div>
        </section>

        {/* Categories */}
        <section id="categories" className="scroll-mt-20 space-y-6">
          <div className="space-y-1">
            <h2 className="text-2xl font-semibold tracking-tight">
              What it can tell you
            </h2>
            <p className="text-sm text-muted-foreground">
              Every result falls into one of these categories.
            </p>
          </div>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {CATEGORIES.map((c, i) => (
              <Reveal key={c.name} delay={i * 0.1} className="h-full">

                <Card key={c.name} size="sm" className="h-full">
                  <CardHeader>
                    <CardTitle className="text-base">{c.name}</CardTitle>
                    <CardDescription>{c.note}</CardDescription>
                  </CardHeader>
                </Card>
              </Reveal>
            ))}
          </div>
        </section>

        {/* Limits */}
        <section id="limits" className="scroll-mt-20 space-y-6">
          <div className="space-y-1">
            <h2 className="text-2xl font-semibold tracking-tight">
              Good to know
            </h2>
            <p className="text-sm text-muted-foreground">
              Honest limits, so you can use the results sensibly.
            </p>
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            {LIMITS.map((l, i) => (
              <Reveal key={l.title} delay={i * 0.1} className="h-full">

                <Card key={l.title} className="h-full">
                  <CardHeader>
                    <CardTitle className="text-base">{l.title}</CardTitle>
                  </CardHeader>
                  <CardContent className="text-sm text-muted-foreground">
                    {l.body}
                  </CardContent>
                </Card>
              </Reveal>
            ))}
          </div>
        </section>
      </main>

      <footer className="border-t">
        <div className="mx-auto flex max-w-5xl flex-col gap-1 px-4 py-6 text-xs text-muted-foreground sm:flex-row sm:items-center sm:justify-between">
          <p>© SortWise AI</p>
          <p>
            Guidance is general and not a local authority ruling. Check your
            local waste rules.
          </p>
        </div>
      </footer>
    </div>
  );
}