# Paper

Overleaf project for the judgeman write-up.

1. Zip this folder (`main.tex`, `refs.bib`, `figures/`).
2. Overleaf: New Project, Upload Project, pick the zip.
3. Menu (top left): Compiler = pdfLaTeX, Main document = `main.tex`. Recompile.

Figures are d2 source. Re-render after editing:

```bash
d2 --pad 10 figures/layered.d2 figures/layered.pdf
d2 --layout elk --pad 10 figures/agreement.d2 figures/agreement.pdf
```

Check the bibliography entries against the real papers before submitting; they were written from memory.
