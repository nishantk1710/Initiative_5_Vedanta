"use client";

import type { BoqField, BoqRow } from "@/lib/types";

const VIEWPORT_WIDTH = 380;
const VIEWPORT_HEIGHT = 260;
const CROP_PADDING = 1.6; // show ~60% margin around the field's bbox for context

const ENGINE_LABEL: Record<BoqField["source"], string> = {
  pymupdf: "PyMuPDF",
  paddleocr: "PaddleOCR",
  tesseract: "Tesseract",
};

export default function SourceViewer({
  documentId,
  row,
  fieldName,
  pageWidth,
  pageHeight,
  onClose,
}: {
  documentId: string;
  row: BoqRow;
  fieldName: "description" | "quantity" | "unit" | "rate" | "amount";
  pageWidth: number;
  pageHeight: number;
  onClose: () => void;
}) {
  const field = row[fieldName];
  const [x0, y0, x1, y1] = field.bbox;

  const bboxWidthFrac = Math.max((x1 - x0) / pageWidth, 0.01);
  const bboxHeightFrac = Math.max((y1 - y0) / pageHeight, 0.01);
  const cropWidthFrac = bboxWidthFrac * CROP_PADDING;
  const cropHeightFrac = bboxHeightFrac * CROP_PADDING;

  const scaleX = VIEWPORT_WIDTH / (cropWidthFrac * pageWidth);
  const scaleY = VIEWPORT_HEIGHT / (cropHeightFrac * pageHeight);
  const scale = Math.max(scaleX, scaleY);

  const displayedWidth = scale * pageWidth;
  const displayedHeight = scale * pageHeight;
  const centerX = ((x0 + x1) / 2) * scale;
  const centerY = ((y0 + y1) / 2) * scale;
  const offsetX = VIEWPORT_WIDTH / 2 - centerX;
  const offsetY = VIEWPORT_HEIGHT / 2 - centerY;

  return (
    <div
      className="modal-overlay open"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="modal">
        <div className="modal-head">
          <h3>Source region</h3>
          <button className="modal-close" onClick={onClose}>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
              <path d="M6 6l12 12M18 6l-12 12" />
            </svg>
          </button>
        </div>
        <div className="modal-body">
          <div className="scan-crop">
            <div
              className="crop-viewport"
              style={{ width: VIEWPORT_WIDTH, height: VIEWPORT_HEIGHT }}
            >
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={`/api/result/${documentId}/page/${field.page}`}
                alt="Source page crop"
                style={{
                  width: displayedWidth,
                  height: displayedHeight,
                  left: offsetX,
                  top: offsetY,
                }}
              />
            </div>
          </div>
          <dl className="prov-grid">
            <div>
              <dt>Field</dt>
              <dd>{fieldName}</dd>
            </div>
            <div>
              <dt>Engine</dt>
              <dd>{ENGINE_LABEL[field.source]}</dd>
            </div>
            <div>
              <dt>Confidence</dt>
              <dd>{Math.round(field.confidence * 100)}%</dd>
            </div>
            <div>
              <dt>Page</dt>
              <dd>{field.page}</dd>
            </div>
          </dl>
        </div>
      </div>
    </div>
  );
}
