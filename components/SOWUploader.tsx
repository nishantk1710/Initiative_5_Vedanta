"use client";

import { useRef, useState } from "react";
import type { SelectedSource } from "@/lib/types";

export default function SOWUploader({
  onSelect,
}: {
  onSelect: (source: SelectedSource) => void;
}) {
  const [isDragging, setIsDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  function handleFile(file: File | undefined) {
    if (!file) return;
    onSelect({ type: "upload", file });
  }

  return (
    <div
      className={`dropzone${isDragging ? " drag" : ""}`}
      onDragOver={(e) => {
        e.preventDefault();
        setIsDragging(true);
      }}
      onDragLeave={() => setIsDragging(false)}
      onDrop={(e) => {
        e.preventDefault();
        setIsDragging(false);
        handleFile(e.dataTransfer.files?.[0]);
      }}
      onClick={(e) => {
        if ((e.target as HTMLElement).closest(".browse-btn")) return;
        inputRef.current?.click();
      }}
    >
      <div className="dz-icon">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8}>
          <path d="M12 16V4M12 4l-4 4M12 4l4 4" />
          <path d="M4 16v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3" />
        </svg>
      </div>
      <p className="primary">Drag &amp; drop your SOW</p>
      <p className="secondary">PDF, PNG, or JPEG · up to 25MB</p>
      <button type="button" className="browse-btn" onClick={() => inputRef.current?.click()}>
        Browse file
      </button>
      <input
        ref={inputRef}
        id="fileInput"
        type="file"
        accept="application/pdf,.pdf,image/png,.png,image/jpeg,.jpg,.jpeg"
        onChange={(e) => handleFile(e.target.files?.[0])}
      />
    </div>
  );
}
