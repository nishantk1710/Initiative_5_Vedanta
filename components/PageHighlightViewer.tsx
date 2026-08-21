"use client";

import type { PageRegionsEntry } from "@/lib/types";

export interface Highlight {
  page: number;
  bbox: [number, number, number, number];
}

export default function PageHighlightViewer({
  documentId,
  pages,
  highlight,
  viewedPage,
  onPageChange,
}: {
  documentId: string;
  pages: PageRegionsEntry[];
  highlight: Highlight | null;
  viewedPage: number;
  onPageChange: (page: number) => void;
}) {
  // A hovered field on a different page takes over the view so its box is
  // actually visible — this is the whole point of hovering it.
  const shownPage = highlight?.page ?? viewedPage;
  const entry = pages.find((p) => p.page === shownPage);

  const box =
    entry && entry.width && entry.height && highlight && highlight.page === shownPage
      ? {
          left: (highlight.bbox[0] / entry.width) * 100,
          top: (highlight.bbox[1] / entry.height) * 100,
          width: ((highlight.bbox[2] - highlight.bbox[0]) / entry.width) * 100,
          height: ((highlight.bbox[3] - highlight.bbox[1]) / entry.height) * 100,
        }
      : null;

  return (
    <div className="doc-panel">
      <div className="page-frame">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src={`/api/result/${documentId}/page/${shownPage}`} alt={`Document page ${shownPage}`} className="page-image" />
        {box && (
          <div
            className="region-box visible"
            data-kind="table"
            data-state="active"
            style={{ top: `${box.top}%`, left: `${box.left}%`, width: `${box.width}%`, height: `${box.height}%` }}
          />
        )}
      </div>

      {pages.length > 1 && (
        <div className="page-nav">
          <button type="button" className="page-nav-btn" disabled={viewedPage <= pages[0].page} onClick={() => onPageChange(viewedPage - 1)}>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.2}>
              <path d="M15 18l-6-6 6-6" />
            </svg>
          </button>
          <span className="page-nav-label">
            Page {shownPage} of {pages.length}
          </span>
          <button
            type="button"
            className="page-nav-btn"
            disabled={viewedPage >= pages[pages.length - 1].page}
            onClick={() => onPageChange(viewedPage + 1)}
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.2}>
              <path d="M9 18l6-6-6-6" />
            </svg>
          </button>
        </div>
      )}

      <p className="page-caption">
        {highlight ? "Hovered field's source region" : "Hover a field or row to locate its source"}
      </p>
    </div>
  );
}
