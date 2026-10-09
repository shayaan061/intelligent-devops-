# IDF sources

`content.js` is the full text of the revised Invention Disclosure Form; `build.js`
turns it into `../IDF_final.docx` and `../IDF_final.txt` (same words in both);
`figures.js` draws Fig. 1 and Fig. 2.

```bash
cd docs/idf_source
npm install docx@9.7.1                 # once
node figures.js                        # writes fig1.html, fig2.html
# render each to PNG at 2x with headless Chrome (window 1200x1580 and 1400x1760), save as fig1.png / fig2.png
node build.js ..                       # writes ../IDF_final.docx and ../IDF_final.txt
```
