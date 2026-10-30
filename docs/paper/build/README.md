# Paper build

The paper is Paper A2 (EmergIN 2027): policy-guarded remediation of known and unknown faults.
Its text is in `a2_text.py` (title, abstract, contributions, Fig. 1 caption, body paragraphs in
order); `build_paper_a2.py` puts it into the conference template, using the layout code, tables,
references and figure handling of `build_paper.py` (kept as a library; the earlier Paper A files
were deleted 28 Oct 2026). Every number comes from the `run_eval.py score` outputs, so the paper is
rebuilt, not edited by hand. Citations are written `[@key]` and numbered in order of first use from
the `REFERENCES` dict in `build_paper.py`.

```bash
python3 docs/paper/build/figures.py experiments/results/eval_stage3_by_scenario.csv docs/paper/figures
python3 docs/paper/build/build_paper_a2.py --core experiments/results \
    --extra experiments/results/eval_extra_stage3_by_scenario.csv --novel experiments/results \
    --out docs/paper/EmergIN2027_paperA2.docx --txt docs/paper/EmergIN2027_paperA2.txt \
    --latex docs/paper/latex_ieee_a2
python3 docs/paper/build/make_chunks.py docs/paper/EmergIN2027_paperA2.txt docs/paper/paperA2_chunks paperA2
```

`--original-text` builds the wording from before the authors' rewording (28 Oct).

PDF of the Word version (no Word or LibreOffice on this Mac): build with `--literal-numbers --out <tmp>.docx`
(writes Fig./TABLE/[n]/heading numbers into the text, because Pages ignores the template's list numbering), open
it in Pages and export as PDF to `docs/paper/EmergIN2027_paperA2.pdf`.

LaTeX (Overleaf IEEE Conference Template): `cd docs/paper/latex_ieee_a2 && zip paperA2_overleaf.zip main.tex *.png`
and upload the zip to Overleaf (New Project > Upload Project).

Local LaTeX PDF (`latex_ieee_a2/main.pdf`, copied to `docs/paper/EmergIN2027_PaperA2_FINAL.pdf`): Tectonic
(Homebrew, installed 26 Oct 2026) uses XeTeX, where IEEEtran's Times (ptm) is missing, so compile a copy with
`\usepackage{fontspec}\setmainfont{texgyretermes}[Extension=.otf,UprightFont=*-regular,BoldFont=*-bold,ItalicFont=*-italic,BoldItalicFont=*-bolditalic]`
added after `\IEEEoverridecommandlockouts` (TeX Gyre Termes has Times metrics and small caps, so the section
headings come out in small caps as in the template; Times New Roman has none):
`tectonic -X compile main.tex`. The uploaded main.tex stays pdfLaTeX (Overleaf default). Check that it is 6 pages.

Figures in the .docx are 600-dpi LZW TIFFs (converted with `sips` at build time) in borderless frames, as the IEEE
template advises. The `--literal-numbers` build (Pages PDF) leaves the frames out, because Pages draws the caption above
a framed figure. The build reads `experiments/results/guard_decisions_long_run.csv` and `mttr_mwu_B1_B2.csv`; regenerate
them with `experiments/guard_decisions.py --out ...` and `experiments/mttr_significance.py --out ...`.
