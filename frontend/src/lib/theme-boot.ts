// Shared by the server root layout (inline <head> script) and lib/theme.ts. No "use client": the layout calls it on the server.
export const THEME_KEY = "fq-theme";

/** Inline script for <head>: same decision as above, before React loads. Kept tiny and dependency-free. */
export function themeBootScript(prefixes: string[]) {
  return `(function(){try{var p=location.pathname,a=${JSON.stringify(prefixes)};if(!a.some(function(h){return p===h||p.indexOf(h+"/")===0}))return;var d=document.documentElement;d.classList.add("fq-app");var m=localStorage.getItem("${THEME_KEY}");var k=m==="dark"||(m!=="light"&&matchMedia("(prefers-color-scheme: dark)").matches);d.dataset.theme=k?"dark":"light"}catch(e){}})()`;
}
