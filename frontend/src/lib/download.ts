/** Save in-memory content as a file download (used where the endpoint needs the auth header). */
export function downloadBlob(content: Blob, fileName: string): void {
  const url = URL.createObjectURL(content)
  const link = document.createElement('a')
  link.href = url
  link.download = fileName
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}
