// Adapter-static fallbacks intentionally use absolute URLs. Ingress needs a relocatable entry.
import { readFile, writeFile } from 'node:fs/promises';
const path = new URL('../build/index.html', import.meta.url);
let html = await readFile(path, 'utf8');
html = html.replaceAll('"/_app/', '"./_app/').replaceAll("'/_app/", "'./_app/");
// The generated bootstrap otherwise derives base="" at a nested mount.
html = html.replace(/base:\s*(""|'')/g, 'base: location.pathname.replace(/\\/[^/]*$/, "")');
await writeFile(path, html);
if (/['"]\/_app\//.test(html)) throw new Error('Absolute asset URL in SPA entry');
