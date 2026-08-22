/**
 * What an uploaded file is, and which pipeline it belongs to.
 *
 * Mirrors backend/specledger/file_types.py. The browser decides which
 * endpoint to call; the server decides whether to accept it. If the two
 * disagree, a file is either sent to the wrong pipeline or rejected after
 * upload with nothing useful said about why.
 *
 * Two kinds of upload exist and they are not interchangeable:
 *   catalogue — structured rows that become enriched 252-column records
 *   document  — a datasheet read for labelled specifications, creating no rows
 */

export type UploadKind = "catalogue" | "document" | "unsupported";

export interface UploadClassification {
  kind: UploadKind;
  extension: string;
  reason: string;
  /** What the format is, for the UI to explain itself. */
  description: string;
}

export const CATALOGUE_EXTENSIONS = [".csv", ".tsv", ".xlsx", ".json", ".xml"] as const;
export const DOCUMENT_EXTENSIONS = [".pdf", ".txt", ".docx", ".rtf"] as const;

const CATALOGUE_DESCRIPTIONS: Record<string, string> = {
  ".csv": "Comma-separated rows. The most common distributor feed.",
  ".tsv": "Tab-separated rows.",
  ".xlsx": "Excel workbook. The first sheet is read unless another is named.",
  ".json": "An array of product objects, or an object wrapping one.",
  ".xml": "Repeated elements, one per product.",
};

const DOCUMENT_DESCRIPTIONS: Record<string, string> = {
  ".pdf": "Manufacturer datasheets and specification sheets.",
  ".txt": "Plain text with no formatting.",
  ".docx": "Word document.",
  ".rtf": "Rich text.",
};

/** Refused, each with the reason and the remedy. */
const REJECTIONS: Record<string, string> = {
  ".xls": "Legacy Excel is not readable here — re-save it as .xlsx.",
  ".doc": "Legacy Word is not readable here — re-save it as .docx.",
  ".jpg": "An image carries no machine-readable text. Send the datasheet as a PDF.",
  ".jpeg": "An image carries no machine-readable text. Send the datasheet as a PDF.",
  ".png": "An image carries no machine-readable text. Send the datasheet as a PDF.",
  ".gif": "An image carries no machine-readable text. Send the datasheet as a PDF.",
  ".svg": "An image carries no machine-readable text. Send the datasheet as a PDF.",
  ".mp3": "Audio carries no product specifications SpecLedger can verify.",
  ".wav": "Audio carries no product specifications SpecLedger can verify.",
  ".mp4": "Video carries no product specifications SpecLedger can verify.",
  ".avi": "Video carries no product specifications SpecLedger can verify.",
  ".mov": "Video carries no product specifications SpecLedger can verify.",
  ".zip": "Archives are not opened. Upload the files inside it individually.",
  ".exe": "Executables are never accepted.",
  ".iso": "Disk images are never accepted.",
};

/** The file picker's filter — exactly what the app accepts. */
export const ACCEPT_ATTRIBUTE = [...CATALOGUE_EXTENSIONS, ...DOCUMENT_EXTENSIONS].join(",");

const SUPPORTED_LIST = [...CATALOGUE_EXTENSIONS, ...DOCUMENT_EXTENSIONS].join(", ");

function extensionOf(filename: string): string {
  const name = String(filename ?? "");
  const dot = name.lastIndexOf(".");
  // A dot in a directory name is not an extension.
  if (dot <= name.lastIndexOf("/") || dot === -1) return "";
  return name.slice(dot).toLowerCase();
}

export function classifyUpload(filename: string): UploadClassification {
  const extension = extensionOf(filename);

  if (extension in CATALOGUE_DESCRIPTIONS) {
    return { kind: "catalogue", extension, reason: "", description: CATALOGUE_DESCRIPTIONS[extension] };
  }
  if (extension in DOCUMENT_DESCRIPTIONS) {
    return { kind: "document", extension, reason: "", description: DOCUMENT_DESCRIPTIONS[extension] };
  }
  if (extension in REJECTIONS) {
    return { kind: "unsupported", extension, reason: REJECTIONS[extension], description: "" };
  }
  if (!extension) {
    return {
      kind: "unsupported", extension: "", description: "",
      reason: `The file has no extension, so its format is unknown. Supported: ${SUPPORTED_LIST}.`,
    };
  }
  return {
    kind: "unsupported", extension, description: "",
    reason: `'${extension}' is not a supported format. Supported: ${SUPPORTED_LIST}.`,
  };
}
