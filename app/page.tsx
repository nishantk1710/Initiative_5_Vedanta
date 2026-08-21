"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import SampleSOWs from "@/components/SampleSOWs";
import SOWUploader from "@/components/SOWUploader";
import Stepper from "@/components/Stepper";
import ProcessingStatus, { type ProcessingPhase } from "@/components/ProcessingStatus";
import type { PageRegionsEntry, PageRoute, ProcessingProgress, SampleMetadata, SelectedSource, UploadResponse } from "@/lib/types";

const POLL_INTERVAL_MS = 1500;
import sampleMetadata from "@/lib/sample-metadata.json";

const SAMPLE_METADATA = sampleMetadata as Record<string, SampleMetadata>;

function formatBytes(bytes: number): string {
  if (bytes < 1024 * 1024) {
    return `${(bytes / 1024).toFixed(0)} KB`;
  }
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export default function Home() {
  const router = useRouter();
  const [selected, setSelected] = useState<SelectedSource | null>(null);
  const [sampleSize, setSampleSize] = useState<number | null>(null);
  const [previewThumbUrl, setPreviewThumbUrl] = useState<string | null>(null);
  const [documentId, setDocumentId] = useState<string | null>(null);
  const [isBusy, setIsBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [view, setView] = useState<"home" | "processing">("home");
  const [phase, setPhase] = useState<ProcessingPhase>("preparing");
  const [pages, setPages] = useState<PageRoute[] | null>(null);
  const [regionsByPage, setRegionsByPage] = useState<Map<number, PageRegionsEntry>>(new Map());
  const [currentPage, setCurrentPage] = useState(1);
  const [processingStartedAt, setProcessingStartedAt] = useState<number | null>(null);
  const [progress, setProgress] = useState<ProcessingProgress | null>(null);
  // Set once POST /api/process has accepted the job — starts the polling
  // effect below. Cleared when the job reaches a terminal state.
  const [pollingJobId, setPollingJobId] = useState<string | null>(null);

  const busyRef = useRef(false);
  // Caches the in-flight upload+prepare call for the CURRENT `selected`
  // source, so the eager preview-thumbnail effect and handleProcess() never
  // upload the same file twice even if both fire close together.
  const uploadRef = useRef<{ source: SelectedSource; promise: Promise<{ documentId: string; pages: PageRoute[] }> } | null>(null);

  function ensureUploaded(source: SelectedSource): Promise<{ documentId: string; pages: PageRoute[] }> {
    if (uploadRef.current?.source === source) {
      return uploadRef.current.promise;
    }

    const promise = (async () => {
      const formData = new FormData();
      if (source.type === "upload") {
        formData.append("file", source.file);
      } else {
        const res = await fetch(source.file);
        const blob = await res.blob();
        const filename = source.file.split("/").pop() ?? "sample.pdf";
        formData.append("file", new File([blob], filename, { type: "application/pdf" }));
      }

      const uploadRes = await fetch("/api/upload", { method: "POST", body: formData });
      if (!uploadRes.ok) {
        const body = await uploadRes.json().catch(() => ({}));
        throw new Error(body.error ?? `Upload failed (${uploadRes.status})`);
      }
      const uploadData = (await uploadRes.json()) as UploadResponse;

      const prepareRes = await fetch("/api/prepare", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ documentId: uploadData.documentId }),
      });
      if (!prepareRes.ok) {
        const body = await prepareRes.json().catch(() => ({}));
        throw new Error(body.error ?? `Preparation failed (${prepareRes.status})`);
      }
      const prepareData = (await prepareRes.json()) as { pages: PageRoute[] };

      return { documentId: uploadData.documentId, pages: prepareData.pages };
    })();

    uploadRef.current = { source, promise };
    return promise;
  }

  useEffect(() => {
    setDocumentId(null);
    setError(null);
    setSampleSize(null);
    setPreviewThumbUrl(null);
    uploadRef.current = null;

    if (selected?.type === "sample") {
      const filename = selected.file.split("/").pop() ?? "";
      // real, precomputed thumbnail — no fetch needed, unlike uploads
      setPreviewThumbUrl(SAMPLE_METADATA[filename]?.thumbnail ?? null);

      fetch(selected.file, { method: "HEAD" })
        .then((res) => {
          const len = res.headers.get("content-length");
          if (len) setSampleSize(Number(len));
        })
        .catch(() => {
          // size unavailable, fall back to "sample document" label
        });
    }

    if (selected?.type === "upload") {
      // fetch the real page-1 thumbnail as soon as the file is selected —
      // before the user even clicks Process SOW — per the "no fake preview"
      // requirement. A failure here is non-fatal; the thumbnail just stays
      // blank and Process SOW will surface the real error if the upload is
      // genuinely broken.
      ensureUploaded(selected)
        .then(({ documentId: id }) => {
          setDocumentId(id);
          setPreviewThumbUrl(`/api/result/${id}/page/1`);
        })
        .catch(() => {
          // leave previewThumbUrl null — Process SOW will retry and surface the real error
        });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
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
      // reuses the same upload+prepare call the eager thumbnail fetch
      // already kicked off on selection, if it's still the same file
      const { documentId: currentDocumentId, pages: routedPages } = await ensureUploaded(selected);
      setDocumentId(currentDocumentId);
      setPages(routedPages);
      setRegionsByPage(new Map());
      // default to the first scanned page (real table/handwriting to show)
      // rather than forcing the user through boring digital-only pages
      setCurrentPage(routedPages.find((p) => p.type === "scanned")?.page ?? routedPages[0]?.page ?? 1);
      setProcessingStartedAt(Date.now());
      setProgress(null);
      setPhase("processing");
      setView("processing");

      // Returns immediately with the job's real page count — the actual
      // pipeline runs as a background task on the Python service, so a
      // 10+ page scanned document (10-15+ min) never times out an HTTP
      // request. Real per-page progress arrives via the polling effect.
      const processRes = await fetch("/api/process", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ documentId: currentDocumentId }),
      });
      if (!processRes.ok) {
        const body = await processRes.json().catch(() => ({}));
        throw new Error(body.error ?? `Failed to start processing (${processRes.status})`);
      }

      setPollingJobId(currentDocumentId);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
      setView("home");
    } finally {
      busyRef.current = false;
      setIsBusy(false);
    }
  }

  // Polls real job status while the background pipeline runs. Every value
  // shown in the processing view comes from these responses — nothing is
  // simulated with a timer, so the UI reads correctly whether a page's
  // stage takes 200ms (digital) or 90s (scanned).
  useEffect(() => {
    if (!pollingJobId) return;
    let cancelled = false;

    async function poll() {
      const res = await fetch(`/api/status/${pollingJobId}`);
      if (!res.ok || cancelled) return;
      const data = (await res.json()) as ProcessingProgress;
      if (cancelled) return;
      setProgress(data);

      if (data.status === "completed" || data.status === "error") {
        setPollingJobId(null);
        if (data.status === "error") {
          setError(data.error ?? "Processing failed");
          setView("home");
          return;
        }
        // regions.json is written by the pipeline, so it only exists now
        // that the job genuinely completed
        const pagesRes = await fetch(`/api/result/${pollingJobId}/pages`);
        if (pagesRes.ok && !cancelled) {
          const pagesData = (await pagesRes.json()) as PageRegionsEntry[];
          setRegionsByPage(new Map(pagesData.map((p) => [p.page, p])));
        }
        if (!cancelled) setPhase("done");
      }
    }

    poll().catch(() => {
      // a single failed poll is not fatal — the interval will retry
    });
    const interval = setInterval(() => {
      poll().catch(() => {});
    }, POLL_INTERVAL_MS);

    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [pollingJobId]);

  const digitalCount = pages?.filter((p) => p.type === "digital").length ?? 0;
  const scannedCount = pages?.filter((p) => p.type === "scanned").length ?? 0;

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
                    <div className="thumb-mock" style={{ width: 52, aspectRatio: "3/4" }}>
                      {previewThumbUrl && (
                        // eslint-disable-next-line @next/next/no-img-element
                        <img
                          src={previewThumbUrl}
                          alt={`${fileName ?? "Selected document"} preview`}
                          style={{ width: "100%", height: "100%", objectFit: "cover" }}
                        />
                      )}
                    </div>
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

        {view === "processing" && documentId && pages && (
          <section className="card">
            <ProcessingStatus
              documentId={documentId}
              fileName={fileName ?? documentId}
              pages={pages}
              currentPage={currentPage}
              onPageChange={setCurrentPage}
              regionsByPage={regionsByPage}
              digitalCount={digitalCount}
              scannedCount={scannedCount}
              phase={phase}
              startedAt={processingStartedAt}
              progress={progress}
            />
            {phase === "done" && (
              <div style={{ padding: "0 38px 30px" }}>
                <button
                  type="button"
                  className="process-btn"
                  onClick={() => router.push(`/results/${documentId}`)}
                >
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
                    <path d="M5 12h14M13 6l6 6-6 6" />
                  </svg>
                  View Results
                </button>
              </div>
            )}
          </section>
        )}
      </div>
    </>
  );
}
