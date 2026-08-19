export function downloadBlob(blob: Blob, filename: string): void {
  const url = window.URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.URL.revokeObjectURL(url);
}

export function downloadJson(value: unknown, filename: string): void {
  downloadBlob(
    new Blob([JSON.stringify(value, null, 2)], { type: "application/json;charset=utf-8" }),
    filename,
  );
}
