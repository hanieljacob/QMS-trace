import type { LotReport, LotSummary, SerialSummary, SerialTree } from "./types";

const BASE = "/api";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
    this.name = "ApiError";
  }
}

async function getJson<T>(path: string): Promise<T> {
  let res: Response;
  try {
    res = await fetch(BASE + path, { headers: { Accept: "application/json" } });
  } catch {
    throw new ApiError(0, "Cannot reach the qmstrace API.");
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      if (body?.detail) detail = body.detail;
    } catch {
      /* keep statusText */
    }
    throw new ApiError(res.status, detail);
  }
  return res.json() as Promise<T>;
}

export const api = {
  searchSerials(q: string): Promise<SerialSummary[]> {
    return getJson(`/serials?q=${encodeURIComponent(q)}&limit=25`);
  },
  serialGenealogy(serialNumber: string): Promise<SerialTree> {
    return getJson(`/serials/${encodeURIComponent(serialNumber)}/genealogy`);
  },
  searchLots(q: string): Promise<LotSummary[]> {
    return getJson(`/lots?q=${encodeURIComponent(q)}&limit=25`);
  },
  lotReport(lotNumber: string): Promise<LotReport> {
    return getJson(`/lots/${encodeURIComponent(lotNumber)}/report`);
  },
};
