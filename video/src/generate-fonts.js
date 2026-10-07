import fs from 'fs';
import path from 'path';

const weights = [400, 500, 600, 700];
let css = '';

for (const w of weights) {
  const viPath = path.resolve(`site/fonts/be-vietnam-pro-${w}-vietnamese.woff2`);
  const latPath = path.resolve(`site/fonts/be-vietnam-pro-${w}-latin.woff2`);
  const viBase64 = fs.readFileSync(viPath).toString('base64');
  const latBase64 = fs.readFileSync(latPath).toString('base64');

  css += `
@font-face {
  font-family: 'Be Vietnam Pro';
  font-style: normal;
  font-weight: ${w};
  font-display: swap;
  src: url('data:font/woff2;base64,${viBase64}') format('woff2');
  unicode-range: U+0102-0103, U+0110-0111, U+0128-0129, U+0168-0169, U+01A0-01A1, U+01AF-01B0, U+0300-0301, U+0303-0304, U+0308-0309, U+0323, U+0329, U+1EA0-1EF9, U+20AB;
}
@font-face {
  font-family: 'Be Vietnam Pro';
  font-style: normal;
  font-weight: ${w};
  font-display: swap;
  src: url('data:font/woff2;base64,${latBase64}') format('woff2');
  unicode-range: U+0000-00FF, U+0131, U+0152-0153, U+02BB-02BC, U+02C6, U+02DA, U+02DC, U+0304, U+0308, U+0329, U+2000-206F, U+20AC, U+2122, U+2191, U+2193, U+2212, U+2215, U+FEFF, U+FFFD;
}
`;
}

const outContent = `// Automatically generated from site/fonts/
export const FONT_STYLES = ${JSON.stringify(css)};
`;

fs.writeFileSync(path.resolve('video/src/fonts.js'), outContent, 'utf8');
console.log('Successfully generated video/src/fonts.js');
