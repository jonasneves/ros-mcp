import * as esbuild from 'esbuild';
import { readFileSync, writeFileSync, mkdirSync, copyFileSync } from 'fs';
import { createHash } from 'crypto';

mkdirSync('dist', { recursive: true });

const js = await esbuild.transform(readFileSync('ros-webmcp.js', 'utf8'), {
  loader: 'js',
  minify: true,
});
const jsHash = createHash('sha256').update(js.code).digest('hex').slice(0, 8);
const jsFile = `ros-webmcp.${jsHash}.js`;
writeFileSync(`dist/${jsFile}`, js.code);

const css = await esbuild.transform(readFileSync('style.css', 'utf8'), {
  loader: 'css',
  minify: true,
});
const cssHash = createHash('sha256').update(css.code).digest('hex').slice(0, 8);
const cssFile = `style.${cssHash}.css`;
writeFileSync(`dist/${cssFile}`, css.code);

let html = readFileSync('index.html', 'utf8');
html = html.replace('href="style.css"', `href="${cssFile}"`);
html = html.replace('src="ros-webmcp.js"', `src="${jsFile}"`);
writeFileSync('dist/index.html', html);

copyFileSync('logo.jpg', 'dist/logo.jpg');

const logoB64 = readFileSync('logo.jpg').toString('base64');
const faviconSvg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><defs><clipPath id="c"><circle cx="50" cy="50" r="50"/></clipPath></defs><image href="data:image/jpeg;base64,${logoB64}" width="100" height="100" clip-path="url(#c)"/></svg>`;
writeFileSync('dist/favicon.svg', faviconSvg);

console.log(`dist/ → ${jsFile}, ${cssFile}, index.html, logo.jpg, favicon.svg`);
