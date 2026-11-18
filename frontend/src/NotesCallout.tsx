// The model's notes about a document. They are untrusted (the model reads hostile documents and may copy their
// markup), so they are rendered as text, never as HTML. Line breaks are kept by CSS (white-space: pre-wrap).
export function NotesCallout({ notes }: { notes: string | null }) {
  if (!notes) return null;
  return (
    <div className="callout">
      <h3>Notes on the document</h3>
      <p className="notes-text">{notes}</p>
    </div>
  );
}
