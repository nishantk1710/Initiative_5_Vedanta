"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import SampleSOWs from "@/components/SampleSOWs";
import SOWUploader from "@/components/SOWUploader";
import Stepper from "@/components/Stepper";
import ProcessingStatus, { type ProcessingPhase } from "@/components/ProcessingStatus";
import type { PageRegionsEntry, PageRoute, SelectedSource, UploadResponse } from "@/lib/types";

function formatBytes(bytes: number): string {
  const mb = bytes / (1024 * 1024);
  return `${mb.toFixed(1)} MB`;
}

export default function Home() {
  const router = useRouter();
  const [selected, setSelected] = useState<SelectedSource | null>(null);
  const [sampleSize, setSampleSize] = useState<number | null>(null);
  const [documentId, setDocumentId] = useState<string | null>(null);
  const [isBusy, setIsBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [view, setView] = useState<"home" | "processing">("home");
  const [phase, setPhase] = useState<ProcessingPhase>("preparing");
  const [pages, setPages] = useState<PageRoute[] | null>(null);
  const [pageRegions, setPageRegions] = useState<PageRegionsEntry | null>(null);

  const busyRef = useRef(false);

  useEffect(() => {
    setDocumentId(null);
    setError(null);
    setSampleSize(null);

    if (selected?.type === "sample") {
      fetch(selected.file, { method: "HEAD" })
        .then((res) => {
          const len = res.headers.get("content-length");
          if (len) setSampleSize(Number(len));
        })
        .catch(() => {
          // size unavailable, fall back to "sample document" label
        });
    }
  }, [selected]);

  const fileName =
    selected?.type === "sample"
      ? selected.file.split("/").pop() ?? "sample.pdf"
      : selected?.type === "upload"
        ? selected.file.name
        : null;

  const fileSizeLabel =
    selected?.type === "upload"
      ? formatBytes(selected.file.size)
      : selected?.type === "sample"
        ? sampleSize !== null
          ? formatBytes(sampleSize)
          : "sample document"
        : null;

  async function handleProcess() {
    if (!selected || busyRef.current) return;
    busyRef.current = true;
    setIsBusy(true);
    setError(null);

    try {
      let currentDocumentId = documentId;

      if (!currentDocumentId) {
        const formData = new FormData();
        if (selected.type === "upload") {
          formData.append("file", selected.file);
        } else {
          const res = await fetch(selected.file);
          const blob = await res.blob();
          const filename = selected.file.split("/").pop() ?? "sample.pdf";
          formData.append("file", new File([blob], filename, { type: "application/pdf" }));
        }

        const uploadRes = await fetch("/api/upload", { method: "POST", body: formData });
        if (!uploadRes.ok) {
          const body = await uploadRes.json().catch(() => ({}));
          throw new Error(body.error ?? `Upload failed (${uploadRes.status})`);
        }
        const uploadData = (await uploadRes.json()) as UploadResponse;
        currentDocumentId = uploadData.documentId;
        setDocumentId(uploadData.documentId);
      }

      // cheap pre-pass: real per-page routing + rendered page images,
      // available before the heavy /api/process call even starts
      const prepareRes = await fetch("/api/prepare", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ documentId: currentDocumentId }),
      });
      if (!prepareRes.ok) {
        const body = await prepareRes.json().catch(() => ({}));
        throw new Error(body.error ?? `Preparation failed (${prepareRes.status})`);
      }
      const prepareData = (await prepareRes.json()) as { pages: PageRoute[] };
      setPages(prepareData.pages);
      setPageRegions(null);
      setPhase("processing");
      setView("processing");

      const processRes = await fetch("/api/process", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ documentId: currentDocumentId }),
      });
      if (!processRes.ok) {
        const body = await processRes.json().catch(() => ({}));
        throw new Error(body.error ?? `Processing failed (${processRes.status})`);
      }

      // fetch the real detected regions for page 1 now that processing wrote regions.json
      const pagesRes = await fetch(`/api/result/${currentDocumentId}/pages`);
      if (pagesRes.ok) {
        const pagesData = (await pagesRes.json()) as PageRegionsEntry[];
        setPageRegions(pagesData.find((p) => p.page === 1) ?? null);
      }

      setPhase("done");
      setTimeout(() => router.push(`/results/${currentDocumentId}`), 700);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
      setView("home");
    } finally {
      busyRef.current = false;
      setIsBusy(false);
    }
  }

  const hasDigital = pages?.some((p) => p.type === "digital") ?? false;
  const hasScanned = pages?.some((p) => p.type === "scanned") ?? false;
  const digitalCount = pages?.filter((p) => p.type === "digital").length ?? 0;
  const scannedCount = pages?.filter((p) => p.type === "scanned").length ?? 0;
  const page1IsScanned = pages?.find((p) => p.page === 1)?.type === "scanned";

  return (
    <>
      <div className="header">
        <div className="wordmark">
          <div className="mark">
            <svg viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
              <path d="M4 20 L9 8 L13 15 L16 6 L20 20 Z" />
            </svg>
          </div>
          <h1>Mining SOW Extractor</h1>
        </div>
        <p className="tagline">Scope-of-work → structured BOQ</p>
        <p className="version-note">
          Watch the document itself get read: regions light up as each engine claims them — <b>PyMuPDF</b> for
          clean digital text, <b>PaddleOCR</b> for printed tables, <b>Tesseract</b> for handwriting.
        </p>
        <Stepper activeIndex={view === "home" ? 0 : 1} />
      </div>

      <div className="stage">
        {view === "home" && (
          <section className="card">
            <div className="home-inner">
              <p className="section-label">Sample documents</p>
              <SampleSOWs
                onSelect={setSelected}
                selectedFile={selected?.type === "sample" ? selected.file : undefined}
              />

              <div className="divider">or</div>

              <SOWUploader onSelect={setSelected} />

              {selected && (
                <div id="previewBlock">
                  <div className="preview-row">
                    <div className="thumb-mock" style={{ width: 52, aspectRatio: "3/4" }} />
                    <div className="info">
                      <span className="fname">{fileName}</span>
                      <span className="fmeta">{fileSizeLabel} · ready to process</span>
                    </div>
                    <button
                      type="button"
                      className="remove-btn"
                      onClick={() => setSelected(null)}
                    >
                      Remove
                    </button>
                  </div>

                  {error && (
                    <p style={{ color: "var(--hazard-rust)", fontSize: 12.5, marginTop: 10 }}>{error}</p>
                  )}

                  <button
                    type="button"
                    className="process-btn"
                    onClick={handleProcess}
                    disabled={isBusy}
                  >
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
                      <path d="M5 12h14M13 6l6 6-6 6" />
                    </svg>
                    {isBusy ? "Uploading…" : "Process SOW"}
                  </button>
                </div>
              )}
            </div>
          </section>
        )}

        {view === "processing" && documentId && (
          <section className="card">
            <ProcessingStatus
              fileName={fileName ?? documentId}
              pageImageUrl={`/api/result/${documentId}/page/1`}
              pageIsScanned={page1IsScanned}
              hasDigital={hasDigital}
              hasScanned={hasScanned}
              digitalCount={digitalCount}
              scannedCount={scannedCount}
              phase={phase}
              pageRegions={pageRegions}
            />
          </section>
        )}
      </div>
    </>
  );
}
