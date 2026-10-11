"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";
import {
  ACCEPTED_TYPES,
  MAX_BYTES,
  analyzeImage,
  type AnalysisResponse,
  type ConditionStatus,
} from "@/lib/api";

const CATEGORY_LABELS: Record<string, string> = {
  plastic: "Plastic",
  paper_cardboard: "Paper / Cardboard",
  metal: "Metal",
  glass: "Glass",
  organic: "Organic",
  general: "General waste",
  electronic: "Electronic",
  unknown: "Unknown",
};

const CONDITION_ROWS: { key: "cracks_fractures" | "holes_leaks_breakage" | "severe_deformation"; label: string }[] = [
  { key: "cracks_fractures", label: "Cracks / fractures" },
  { key: "holes_leaks_breakage", label: "Holes / leaks / breakage" },
  { key: "severe_deformation", label: "Severe deformation" },
];

function statusBadge(status: ConditionStatus) {
  switch (status) {
    case "detected":
      return <Badge variant="destructive">Detected</Badge>;
    case "not_detected":
      return <Badge variant="secondary">Not detected</Badge>;
    default:
      return <Badge variant="outline">Unable to assess</Badge>;
  }
}

function findingText(f: unknown): string {
  if (typeof f === "string") return f;
  if (f && typeof f === "object") {
    const o = f as Record<string, unknown>;
    const parts = [o.type, o.description ?? o.detail ?? o.evidence].filter(
      (p): p is string => typeof p === "string"
    );
    if (parts.length) return parts.join(": ");
  }
  return JSON.stringify(f);
}

export function Analyzer() {
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [description, setDescription] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [data, setData] = useState<AnalysisResponse | null>(null);
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    if (!file) return setPreview(null);
    const url = URL.createObjectURL(file);
    setPreview(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);

  const pick = useCallback((f: File | undefined | null) => {
    if (!f) return;
    setData(null);
    if (!ACCEPTED_TYPES.includes(f.type)) {
      setFile(null);
      return setError("Unsupported format. Use JPEG, PNG, WEBP, or GIF.");
    }
    if (f.size > MAX_BYTES) {
      setFile(null);
      return setError("File is larger than 10 MiB.");
    }
    setError(null);
    setFile(f);
  }, []);

  async function submit() {
    if (!file) return;
    abortRef.current?.abort();
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    setLoading(true);
    setError(null);
    setData(null);
    try {
      setData(await analyzeImage(file, description, ctrl.signal));
    } catch (e) {
      if ((e as Error).name === "AbortError") return;
      setError(
        e instanceof TypeError
          ? "Could not reach the server. Is the backend running and CORS enabled?"
          : (e as Error).message
      );
    } finally {
      setLoading(false);
    }
  }

  function reset() {
    abortRef.current?.abort();
    setFile(null);
    setDescription("");
    setData(null);
    setError(null);
    setLoading(false);
    if (inputRef.current) inputRef.current.value = "";
  }

  const result = data?.result;
  const cond = result?.condition;

  return (
    <div className="grid gap-6 lg:grid-cols-2">
      {/* Upload */}
      <Card>
        <CardHeader>
          <CardTitle>Upload an item</CardTitle>
          <CardDescription>
            JPEG, PNG, WEBP or GIF, up to 10 MiB.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div
            role="button"
            tabIndex={0}
            onClick={() => inputRef.current?.click()}
            onKeyDown={(e) =>
              (e.key === "Enter" || e.key === " ") && inputRef.current?.click()
            }
            onDragOver={(e) => {
              e.preventDefault();
              setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={(e) => {
              e.preventDefault();
              setDragging(false);
              pick(e.dataTransfer.files?.[0]);
            }}
            className={cn(
              "flex min-h-64 cursor-pointer flex-col items-center justify-center rounded-lg border-2 border-dashed p-4 text-center text-sm text-muted-foreground transition-colors",
              dragging && "border-primary bg-muted"
            )}
          >
            {preview ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={preview}
                alt="Selected item preview"
                className="max-h-72 rounded-md object-contain"
              />
            ) : (
              <p>Drag and drop an image here, or click to browse</p>
            )}
            <input
              ref={inputRef}
              type="file"
              accept={ACCEPTED_TYPES.join(",")}
              className="hidden"
              onChange={(e) => pick(e.target.files?.[0])}
            />
          </div>
          {file && (
            <p className="truncate text-xs text-muted-foreground">
              {file.name} · {(file.size / 1024).toFixed(0)} KB
            </p>
          )}
          <div className="space-y-2">
            <Label htmlFor="description">Description (optional)</Label>
            <Textarea
              id="description"
              placeholder="e.g. Empty glass jar"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              maxLength={500}
            />
          </div>
          {error && (
            <Alert variant="destructive">
              <AlertTitle>Something went wrong</AlertTitle>
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}
        </CardContent>
        <CardFooter className="gap-2">
          <Button onClick={submit} disabled={!file || loading}>
            {loading ? "Analyzing…" : "Analyze"}
          </Button>
          <Button variant="outline" onClick={reset} disabled={!file && !data}>
            Reset
          </Button>
        </CardFooter>
      </Card>

      {/* Results */}
      <Card>
        <CardHeader>
          <CardTitle>Result</CardTitle>
          <CardDescription>
            General guidance only. Check your local waste authority.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {loading && (
            <div className="space-y-3">
              <Skeleton className="h-8 w-2/3" />
              <Skeleton className="h-4 w-full" />
              <Skeleton className="h-4 w-5/6" />
              <Skeleton className="h-24 w-full" />
            </div>
          )}

          {!loading && !result && (
            <p className="text-sm text-muted-foreground">
              Upload an image and press Analyze to see the result here.
            </p>
          )}

          {!loading && result && (
            <>
              <div className="space-y-2">
                <div className="flex flex-wrap items-center gap-2">
                  <h2 className="text-xl font-semibold">{result.item_name}</h2>
                  <Badge
                    variant={result.category === "unknown" ? "outline" : "default"}
                  >
                    {CATEGORY_LABELS[result.category] ?? result.category}
                  </Badge>
                </div>
                <p className="text-sm text-muted-foreground">
                  Material: {result.material} · Confidence (estimate):{" "}
                  {Math.round(result.confidence * 100)}%
                </p>
                <p className="text-sm">{result.evidence}</p>
              </div>

              <Separator />

              <section className="space-y-1">
                <h3 className="text-sm font-medium">Disposal guidance</h3>
                <p className="text-sm">{result.disposal_guidance}</p>
              </section>

              {result.preparation_steps.length > 0 && (
                <section className="space-y-1">
                  <h3 className="text-sm font-medium">Preparation</h3>
                  <ul className="list-disc space-y-1 pl-5 text-sm">
                    {result.preparation_steps.map((s, i) => (
                      <li key={i}>{s}</li>
                    ))}
                  </ul>
                </section>
              )}

              <Separator />

              <section className="space-y-2">
                <h3 className="text-sm font-medium">Condition</h3>
                {cond ? (
                  <>
                    {CONDITION_ROWS.map(({ key, label }) => (
                      <div
                        key={key}
                        className="flex items-center justify-between text-sm"
                      >
                        <span>{label}</span>
                        {statusBadge(cond[key])}
                      </div>
                    ))}
                    {cond.image_unclear && (
                      <p className="text-xs text-muted-foreground">
                        The image was unclear, so condition may be incomplete.
                      </p>
                    )}
                    {cond.findings.length > 0 && (
                      <ul className="list-disc space-y-1 pl-5 text-sm">
                        {cond.findings.map((f, i) => (
                          <li key={i}>{findingText(f)}</li>
                        ))}
                      </ul>
                    )}
                  </>
                ) : (
                  <p className="text-sm text-muted-foreground">
                    Condition assessment unavailable.
                  </p>
                )}
              </section>

              {result.warnings.length > 0 && (
                <Alert>
                  <AlertTitle>Warnings</AlertTitle>
                  <AlertDescription>
                    <ul className="list-disc space-y-1 pl-4">
                      {result.warnings.map((w, i) => (
                        <li key={i}>{w}</li>
                      ))}
                    </ul>
                  </AlertDescription>
                </Alert>
              )}
            </>
          )}
        </CardContent>
      </Card>
    </div>
  );
}