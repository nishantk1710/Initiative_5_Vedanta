"use client";

import Image from "next/image";
import sampleMetadata from "@/lib/sample-metadata.json";
import type { SampleMetadata, SelectedSource } from "@/lib/types";

const METADATA = sampleMetadata as Record<string, SampleMetadata>;

const SAMPLES = [
  { label: "SOW 1", file: "sow-1.pdf" },
  { label: "SOW 2", file: "sow-2.pdf" },
  { label: "SOW 3", file: "sow-3.pdf" },
];

function routeInfo(meta: SampleMetadata): { cls: "digital" | "mixed" | "scanned"; meta: string } {
  const total = meta.pages.length;
  if (meta.digitalCount > 0 && meta.scannedCount > 0) {
    return { cls: "mixed", meta: `${meta.digitalCount} digital · ${meta.scannedCount} scanned` };
  }
  if (meta.scannedCount > 0) {
    return { cls: "scanned", meta: `${total}/${total} pages scanned` };
  }
  return { cls: "digital", meta: `${total}/${total} pages digital` };
}

export default function SampleSOWs({
  onSelect,
  selectedFile,
}: {
  onSelect: (source: SelectedSource) => void;
  selectedFile?: string;
}) {
  return (
    <div className="samples">
      {SAMPLES.map((sample) => {
        const meta = METADATA[sample.file];
        const route = routeInfo(meta);
        const isActive = selectedFile === `/samples/${sample.file}`;
        return (
          <button
            key={sample.file}
            type="button"
            className={`sample-card${isActive ? " active" : ""}`}
            onClick={() => onSelect({ type: "sample", file: `/samples/${sample.file}` })}
          >
            <div className="thumb-mock">
              <Image
                src={meta.thumbnail}
                alt={`${sample.label} preview`}
                width={300}
                height={400}
                style={{ width: "100%", height: "100%", objectFit: "cover" }}
              />
            </div>
            <span className="name">{sample.label}</span>
            <span className="meta">{route.meta}</span>
            <span className={`route-tag ${route.cls}`}>
              <span className="rdot" />
              {route.cls}
            </span>
          </button>
        );
      })}
    </div>
  );
}
