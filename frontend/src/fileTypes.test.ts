import { describe, it, expect } from "vitest";
import { classifyUpload, ACCEPT_ATTRIBUTE, CATALOGUE_EXTENSIONS, DOCUMENT_EXTENSIONS } from "./fileTypes";

// This mirrors backend/specledger/file_types.py. The two must agree: the
// browser decides which endpoint to call, and the server decides whether to
// accept it. If they disagree, a file is either sent to the wrong pipeline
// or rejected after upload with no explanation.

describe("catalogue formats", () => {
  it("routes spreadsheets and structured data to the catalogue path", () => {
    for (const name of ["feed.csv", "feed.tsv", "feed.xlsx", "feed.json", "feed.xml"]) {
      expect(classifyUpload(name).kind, name).toBe("catalogue");
    }
  });

  it("ignores case and surrounding path", () => {
    expect(classifyUpload("My Feed.CSV").kind).toBe("catalogue");
  });
});

describe("document formats", () => {
  it("routes datasheets and prose to the document path", () => {
    for (const name of ["a.pdf", "a.txt", "a.docx", "a.rtf"]) {
      expect(classifyUpload(name).kind, name).toBe("document");
    }
  });
});

describe("refusals", () => {
  it("refuses images, audio and video with a reason", () => {
    for (const name of ["a.jpg", "a.jpeg", "a.png", "a.gif", "a.svg", "a.mp3", "a.wav", "a.mp4", "a.avi", "a.mov"]) {
      const result = classifyUpload(name);
      expect(result.kind, name).toBe("unsupported");
      expect(result.reason.length, name).toBeGreaterThan(0);
    }
  });

  it("refuses archives, executables and disk images", () => {
    for (const name of ["a.zip", "a.exe", "a.iso"]) {
      expect(classifyUpload(name).kind, name).toBe("unsupported");
    }
  });

  it("tells a legacy format what to save as instead", () => {
    expect(classifyUpload("book.xls").reason).toContain(".xlsx");
    expect(classifyUpload("spec.doc").reason).toContain(".docx");
  });

  it("refuses an unknown extension and a file with none", () => {
    expect(classifyUpload("mystery.qqq").kind).toBe("unsupported");
    expect(classifyUpload("README").kind).toBe("unsupported");
  });
});

describe("the file picker filter", () => {
  it("offers exactly what the app accepts, and nothing it refuses", () => {
    for (const extension of [...CATALOGUE_EXTENSIONS, ...DOCUMENT_EXTENSIONS]) {
      expect(ACCEPT_ATTRIBUTE, extension).toContain(extension);
    }
    for (const refused of [".jpg", ".mp4", ".zip", ".exe", ".iso", ".xls", ".doc"]) {
      expect(ACCEPT_ATTRIBUTE.split(",")).not.toContain(refused);
    }
  });
});
