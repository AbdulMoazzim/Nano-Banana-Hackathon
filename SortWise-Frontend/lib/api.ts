export type Category =
  | "plastic"
  | "paper_cardboard"
  | "metal"
  | "glass"
  | "organic"
  | "general"
  | "electronic"
  | "unknown";

export type ConditionStatus = "detected" | "not_detected" | "unable_to_assess";

export interface Condition {
  cracks_fractures: ConditionStatus;
  holes_leaks_breakage: ConditionStatus;
  severe_deformation: ConditionStatus;
  image_unclear: boolean;
  findings: unknown[];
}

export interface AnalysisResult {
  item_name: string;
  category: Category;
  material: string;
  confidence: number;
  evidence: string;
  disposal_guidance: string;
  preparation_steps: string[];
  warnings: string[];
  condition: Condition | null;
}

export interface AnalysisResponse {
  request_id: string;
  status: string;
  result: AnalysisResult;
}

export const API_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

export const MAX_BYTES = 10 * 1024 * 1024;
export const ACCEPTED_TYPES = [
  "image/jpeg",
  "image/png",
  "image/webp",
  "image/gif",
];

export async function analyzeImage(
  image: File,
  description?: string,
  signal?: AbortSignal
): Promise<AnalysisResponse> {
  const form = new FormData();
  form.append("image", image);
  if (description?.trim()) form.append("description", description.trim());

  // Do not set Content-Type: the browser adds the multipart boundary.
  const res = await fetch(`${API_URL}/api/v1/analyses`, {
    method: "POST",
    body: form,
    signal,
  });

  if (!res.ok) {
    let message = `Request failed (${res.status})`;
    try {
      const body = await res.json();
      if (typeof body?.detail === "string") message = body.detail;
      else if (Array.isArray(body?.detail))
        message = body.detail.map((d: { msg?: string }) => d.msg).join("; ");
    } catch {
      /* non-JSON error body */
    }
    throw new Error(message);
  }
  return res.json();
}