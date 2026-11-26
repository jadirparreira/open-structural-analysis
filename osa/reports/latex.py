"""Utilitários para gerar documentos LaTeX no estilo dos laudos técnicos.

O visual segue um laudo típico em ``article``: Latin Modern, tabelas com
``booktabs``, cabeçalho e rodapé com ``fancyhdr`` e legendas em negrito.
Quando há um compilador LaTeX instalado, o PDF é gerado diretamente; caso
contrário, a pasta com o ``.tex`` e as figuras fica pronta para compilar
em outra máquina (ou no Overleaf).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from math import isfinite
from pathlib import Path

# Ordem de preferência dos compiladores. O pdflatex é o mais comum e não
# depende de fontes do sistema; o tectonic baixa os pacotes sozinho.
_ENGINES = ("pdflatex", "lualatex", "xelatex", "tectonic")

_LATEX_SPECIAL = {
    "\\": r"\textbackslash{}",
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}

# Caracteres que o pdflatex com T1/utf8 não reconhece sozinho.
_UNICODE_TEXT = {
    "²": r"\textsuperscript{2}",
    "³": r"\textsuperscript{3}",
    "⁴": r"\textsuperscript{4}",
    "⁶": r"\textsuperscript{6}",
    "⁻": r"\textsuperscript{$-$}",
    "¹": r"\textsuperscript{1}",
    "₀": r"\textsubscript{0}",
    "₁": r"\textsubscript{1}",
    "₂": r"\textsubscript{2}",
    "—": "---",
    "–": "--",
    "−": "$-$",
    "≤": r"$\leq$",
    "≥": r"$\geq$",
    "≠": r"$\neq$",
    "≈": r"$\approx$",
    "×": r"$\times$",
    "·": r"$\cdot$",
    "∞": r"$\infty$",
    "√": r"$\surd$",
    "∑": r"$\sum$",
    "→": r"$\rightarrow$",
    "Δ": r"$\Delta$",
    "α": r"$\alpha$",
    "β": r"$\beta$",
    "γ": r"$\gamma$",
    "δ": r"$\delta$",
    "ε": r"$\varepsilon$",
    "η": r"$\eta$",
    "θ": r"$\theta$",
    "λ": r"$\lambda$",
    "μ": r"$\mu$",
    "ν": r"$\nu$",
    "π": r"$\pi$",
    "ρ": r"$\rho$",
    "σ": r"$\sigma$",
    "τ": r"$\tau$",
    "φ": r"$\phi$",
    "χ": r"$\chi$",
    "ψ": r"$\psi$",
    "ω": r"$\omega$",
    "Ø": r"\O{}",
    "ø": r"\o{}",
    "°": r"$^\circ$",
    " ": "~",
    " ": r"\,",
    " ": r"\,",
    "￼": "",
}


def tex_escape(text: object) -> str:
    """Escapa texto comum para LaTeX, incluindo símbolos Unicode usuais."""
    result = []
    for character in str(text):
        if character in _LATEX_SPECIAL:
            result.append(_LATEX_SPECIAL[character])
        elif character in _UNICODE_TEXT:
            result.append(_UNICODE_TEXT[character])
        else:
            result.append(character)
    return "".join(result)


def number(value: object, decimals: int = 2, *, thousands: bool = True) -> str:
    """Formata números no padrão brasileiro (vírgula decimal, espaço fino nos milhares)."""
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return "--"
    if not isfinite(numeric):
        return r"$\infty$"
    text = f"{numeric:,.{decimals}f}"
    integer, _, fraction = text.partition(".")
    integer = integer.replace(",", r"\," if thousands else "")
    if integer.startswith("-"):
        integer = "$-$" + integer[1:]
    return f"{integer},{fraction}" if fraction else integer


def percent(value: object, decimals: int = 1) -> str:
    try:
        return f"{number(float(value) * 100.0, decimals)}\\,\\%"
    except (TypeError, ValueError):
        return "--"


def unit(value: object, symbol: str, decimals: int = 2) -> str:
    """Valor com unidade separada por espaço fino, como no laudo de referência."""
    formatted = number(value, decimals)
    return formatted if formatted == "--" else f"{formatted}\\,{symbol}"


@dataclass(frozen=True)
class DocumentStyle:
    """Dados do cabeçalho, do rodapé e do PDF gerado."""

    header_left: str = ""
    footer_left: str = ""
    footer_right: str = ""
    pdf_title: str = ""
    pdf_author: str = ""


def preamble(style: DocumentStyle) -> str:
    """Preâmbulo comum aos documentos (laudo da estrutura e memorial de elemento)."""
    return rf"""\documentclass[11pt,a4paper]{{article}}
\usepackage{{iftex}}
\ifPDFTeX
  \usepackage[utf8]{{inputenc}}
  \usepackage[T1]{{fontenc}}
  \usepackage{{lmodern}}
\else
  % XeTeX/LuaTeX (incluindo o Tectonic): Latin Modern via fontspec.
  \usepackage{{fontspec}}
\fi
\usepackage[brazil]{{babel}}
\usepackage[a4paper,margin=2.2cm,headheight=14pt]{{geometry}}
\usepackage{{graphicx}}
\usepackage{{booktabs}}
\usepackage{{float}}
\usepackage{{longtable}}
\usepackage[table]{{xcolor}}
\usepackage{{caption}}
\usepackage{{fancyhdr}}
\usepackage{{lastpage}}
\usepackage{{amsmath}}
\usepackage{{amssymb}}
\usepackage{{array}}
\usepackage[hidelinks]{{hyperref}}

\hypersetup{{pdftitle={{{tex_escape(style.pdf_title)}}},pdfauthor={{{tex_escape(style.pdf_author)}}}}}
\addto\captionsbrazil{{%
  \renewcommand{{\figurename}}{{Figura}}%
  \renewcommand{{\tablename}}{{Tabela}}%
  \renewcommand{{\contentsname}}{{Sumário}}%
}}
\captionsetup{{font=small,labelfont=bf}}
\setlength{{\parindent}}{{0pt}}
\setlength{{\parskip}}{{0.6em}}

\definecolor{{ok}}{{HTML}}{{1E8449}}
\definecolor{{nok}}{{HTML}}{{C0392B}}
\newcommand{{\OK}}{{\textcolor{{ok}}{{\textbf{{Atende}}}}}}
\newcommand{{\NOK}}{{\textcolor{{nok}}{{\textbf{{Não atende}}}}}}
\newcommand{{\NV}}{{\textcolor{{gray}}{{\textbf{{Não verificado}}}}}}

\pagestyle{{fancy}}
\fancyhf{{}}
\lhead{{\small {tex_escape(style.header_left)}}}
\rhead{{\small Página \thepage\ de \pageref{{LastPage}}}}
\lfoot{{\footnotesize {style.footer_left}}}
\rfoot{{\footnotesize {tex_escape(style.footer_right)}}}
"""


def bundled_tectonic() -> Path | None:
    """Tectonic distribuído com o instalador (ou preparado em ``build-tools`` no código-fonte)."""
    executable = "tectonic.exe" if sys.platform == "win32" else "tectonic"
    package = Path(__file__).resolve().parents[1]
    for candidate in (
        package / "resources" / "latex" / executable,
        package.parent / "build-tools" / "tectonic" / sys.platform / executable,
    ):
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate.resolve()
    return None


def find_latex_engine() -> str | None:
    """Compilador a usar: ``OSA_LATEX_ENGINE``, um LaTeX instalado no sistema ou o Tectonic embutido."""
    preferred = os.environ.get("OSA_LATEX_ENGINE")
    if preferred:
        return shutil.which(preferred) or (preferred if Path(preferred).is_file() else None)
    for engine in _ENGINES:
        found = shutil.which(engine)
        if found:
            return found
    bundled = bundled_tectonic()
    return str(bundled) if bundled else None


def engine_name(engine: str | None) -> str:
    return Path(engine).stem if engine else ""


class LatexCompilationError(RuntimeError):
    """Falha do compilador; a mensagem traz o final do log para diagnóstico."""


def compile_latex(tex_path: str | Path, engine: str | None = None, timeout: float = 240.0) -> Path:
    """Compila o ``.tex`` (duas passagens para sumário e total de páginas)."""
    tex_path = Path(tex_path)
    engine = engine or find_latex_engine()
    if engine is None:
        raise LatexCompilationError("Nenhum compilador LaTeX (pdflatex, lualatex, xelatex ou tectonic) foi encontrado.")
    executable = shutil.which(engine) or engine
    name = engine_name(engine)
    if name == "tectonic":
        commands = [[executable, "--keep-logs", tex_path.name]]
    else:
        command = [executable, "-interaction=nonstopmode", "-halt-on-error", "-file-line-error", tex_path.name]
        commands = [command, command]
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    for command in commands:
        try:
            completed = subprocess.run(
                command,
                cwd=tex_path.parent,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                creationflags=creation_flags,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise LatexCompilationError(f"Falha ao executar {name}: {exc}") from exc
        if completed.returncode != 0:
            log = tex_path.with_suffix(".log")
            text = log.read_text(encoding="utf-8", errors="replace") if log.is_file() else ""
            text = text or f"{completed.stdout}\n{completed.stderr}"
            tail = "\n".join(text.strip().splitlines()[-25:])
            hint = (
                "\n\nNa primeira compilação o Tectonic precisa de internet para baixar os pacotes LaTeX."
                if name == "tectonic" else ""
            )
            raise LatexCompilationError(f"{name} terminou com erro.\n\n{tail}{hint}")
    pdf = tex_path.with_suffix(".pdf")
    if not pdf.is_file():
        raise LatexCompilationError(f"{name} não gerou o arquivo {pdf.name}.")
    return pdf


def clean_auxiliary_files(tex_path: str | Path) -> None:
    tex_path = Path(tex_path)
    for suffix in (".aux", ".log", ".out", ".toc", ".lof", ".lot"):
        auxiliary = tex_path.with_suffix(suffix)
        if auxiliary.is_file():
            auxiliary.unlink()
