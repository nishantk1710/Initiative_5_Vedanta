"use client";

import type { GenericTable, PageRegionsEntry } from "@/lib/types";

// Renders exactly one thumbnail per real page — never assumes a page
// count. Works identically at 1 page or 15 pages because it only ever maps
// over `pages`.
export default function PageStrip({
  documentId,
  pages,
  viewedPage,
  onSelect,
  tables,
}: {
  documentId: string;
  pages: PageRegionsEntry[];
  viewedPage: number;
  onSelect: (page: number) => void;
  // Real continuation data (python/continuation.py) — a page's amber dot
  // only appears when it's actually part of a multi-page table.
  tables: GenericTable[];
}) {
  const continuationPages = new Set(tables.filter((t) => t.pages.length > 1).flatMap((t) => t.pages));

  return (
    <div className="strip-wrap">
      <div className="strip-top">
        <span className="strip-label">Pages</span>
      </div>
      <div className="strip">
        {pages.map((p) => (
          <button
            key={p.page}
            type="button"
            className={`thumb${p.page === viewedPage ? " selected" : ""}`}
            onClick={() => onSelect(p.page)}
            title={`Page ${p.page} (${p.type})`}
          >
            <div className="thumb-box">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={`/api/result/${documentId}/page/${p.page}`} alt={`Page ${p.page}`} className="thumb-img" />
              <div className={`thumb-kind ${p.type}`} />
              {continuationPages.has(p.page) && <div className="cont-dot" />}
            </div>
            <div className="thumb-num">P{p.page}</div>
          </button>
        ))}
      </div>
    </div>
  );
}
