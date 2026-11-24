"""Memorial de cálculo de elemento em LaTeX, no mesmo estilo do laudo da estrutura.

Reaproveita o HTML que o diálogo do memorial já monta (o mesmo usado na
exportação DOCX) e o LaTeX de cada equação, convertendo-os em seções,
tabelas ``booktabs`` e equações exibidas.
"""

from __future__ import annotations

import re
import shutil
from datetime import date, datetime
from pathlib import Path

from .latex import (
    DocumentStyle,
    LatexCompilationError,
    clean_auxiliary_files,
    compile_latex,
    find_latex_engine,
    preamble,
    tex_escape,
)
from .structure_report import ReportExport, software_version

_EQUATION_MARKER = re.compile(r"OSA_EQUATION_OBJECT_\d{4}_END")
_DECIMAL_COMMA = re.compile(r"(?<=\d),(?=\d)")
_SECTION_NUMBER = re.compile(r"^\s*\d+(\.\d+)*\.?\s+")


def _parse(html: str):
    from osa.ui.memorial_docx_export import _MemorialParser

    parser = _MemorialParser()
    parser.feed(html)
    return parser.root


def _is_bold(node) -> bool:
    style = node.attributes.get("style", "")
    return bool(re.search(r"(?:^|;)\s*font-weight\s*:\s*(?:bold|[6-9]00)\b", style, re.IGNORECASE))


def _is_centered(node) -> bool:
    style = node.attributes.get("style", "")
    return node.attributes.get("align") == "center" or "text-align:center" in style.replace(" ", "")


def math_latex(expression: str) -> str:
    """Ajusta o LaTeX do MathText ao LaTeX real (vírgula decimal sem espaço)."""
    return _DECIMAL_COMMA.sub("{,}", expression.strip())


def _plain_text(node) -> str:
    parts = []
    for child in node.children:
        parts.append(child if isinstance(child, str) else "\n" if child.tag == "br" else _plain_text(child))
    return "".join(parts)


def _inline(node, equations: dict[str, str]) -> str:
    """Texto com equações em linha (``$...$``) e negrito preservado."""
    output = []
    for child in node.children:
        if isinstance(child, str):
            cursor = 0
            for match in _EQUATION_MARKER.finditer(child):
                output.append(tex_escape(child[cursor:match.start()]))
                latex = equations.get(match.group())
                output.append(f"${math_latex(latex)}$" if latex else "")
                cursor = match.end()
            output.append(tex_escape(child[cursor:]))
        elif child.tag == "br":
            output.append("\\\\\n")
        elif child.tag in {"b", "strong"}:
            output.append(f"\\textbf{{{_inline(child, equations)}}}")
        else:
            output.append(_inline(child, equations))
    return "".join(output)


def _display_equations(node, equations: dict[str, str]) -> str | None:
    """Parágrafo composto só de equações: vira um bloco de equações centralizadas."""
    text = _plain_text(node)
    markers = _EQUATION_MARKER.findall(text)
    if not markers or _EQUATION_MARKER.sub("", text).strip():
        return None
    lines = []
    for marker in markers:
        latex = equations.get(marker)
        if latex:
            # Equações longas (FLT, flexocompressão) são reduzidas para caber na linha.
            lines.append(
                "\\resizebox{\\ifdim\\width>\\linewidth\\linewidth\\else\\width\\fi}{!}"
                f"{{$\\displaystyle {math_latex(latex)}$}}"
            )
    if not lines:
        return None
    return "\\begin{center}\n" + "\\\\[4pt]\n".join(lines) + "\n\\end{center}"


def _table(node, equations: dict[str, str]) -> str:
    from osa.ui.memorial_docx_export import _table_rows

    rows = []
    for row in _table_rows(node):
        cells = [child for child in row.children if not isinstance(child, str) and child.tag in {"td", "th"}]
        if not cells:
            continue
        values = [_inline(cell, equations).strip() or "--" for cell in cells[:2]]
        values += ["--"] * (2 - len(values))
        rows.append(f"{values[0]} & {values[1]}\\\\")
    if not rows:
        return ""
    return (
        "{\\small\n\\begin{longtable}{@{}p{0.58\\textwidth}p{0.36\\textwidth}@{}}\n\\toprule\n"
        "Parâmetro & Valor\\\\\n\\midrule\n\\endfirsthead\n\\toprule\nParâmetro & Valor\\\\\n\\midrule\n\\endhead\n"
        "\\bottomrule\n\\endfoot\n" + "\n".join(rows) + "\n\\end{longtable}\n}"
    )


def _convert(node, equations: dict[str, str], output: list[str]) -> None:
    for child in node.children:
        if isinstance(child, str):
            if child.strip():
                output.append(tex_escape(child.strip()))
            continue
        tag = child.tag
        if tag == "h2":
            continue  # O título vai para o cabeçalho do documento.
        if tag == "h3":
            title = _SECTION_NUMBER.sub("", _plain_text(child)).strip()
            output.append(f"\\section{{{tex_escape(title)}}}")
        elif tag == "p":
            if _is_bold(child):
                output.append(f"\\subsection{{{_inline(child, equations).strip()}}}")
                continue
            display = _display_equations(child, equations)
            if display:
                output.append(display)
            elif _is_centered(child):
                output.append(f"\\begin{{center}}\n{_inline(child, equations).strip()}\n\\end{{center}}")
            else:
                text = _inline(child, equations).strip()
                if text:
                    output.append(text + "\n")
        elif tag == "table":
            output.append(_table(child, equations))
        else:
            _convert(child, equations, output)


def memorial_to_latex(
    html: str,
    equation_latex: dict[str, str],
    *,
    element: str = "",
    members: tuple[str, ...] = (),
    issue_date: date | None = None,
) -> str:
    """Converte o HTML do memorial (com marcadores de equação) em um documento LaTeX."""
    issue_date = issue_date or datetime.now().astimezone().date()
    root = _parse(html)
    title = "Memória de cálculo de elemento estrutural"
    for node in root.children:
        if not isinstance(node, str):
            heading = next((item for item in [node, *node.children] if not isinstance(item, str) and item.tag == "h2"), None)
            if heading is not None:
                title = _plain_text(heading).strip() or title
                break
    subject = element or (", ".join(members) if members else "")
    software = f"Open Structural Analysis {software_version()}".strip()
    header = f"Memorial de cálculo – {subject}" if subject else "Memorial de cálculo"
    body: list[str] = []
    _convert(root, equation_latex, body)
    member_line = (
        f"{{\\large Barra{'s' if len(members) > 1 else ''}: {tex_escape(', '.join(members))}\\par}}\n"
        if members else ""
    )
    return (
        preamble(DocumentStyle(
            header_left=header,
            footer_left=tex_escape(software),
            footer_right=f"Emissão: {issue_date:%d/%m/%Y}",
            pdf_title=title,
        ))
        + "\\begin{document}\n\\begin{center}\n"
        + f"{{\\LARGE\\bfseries {tex_escape(title)}\\par}}\n\\vspace{{0.4cm}}\n"
        + (f"{{\\Large {tex_escape(element)}\\par}}\n\\vspace{{0.2cm}}\n" if element else "")
        + member_line
        + f"{{\\small ABNT NBR 8800:2024 -- {issue_date:%d/%m/%Y}\\par}}\n\\end{{center}}\n\\vspace{{0.4cm}}\n"
        + "\n\n".join(body)
        + "\n\\end{document}\n"
    )


def export_element_memorial(
    html: str,
    equation_latex: dict[str, str],
    destination: str | Path,
    *,
    element: str = "",
    members: tuple[str, ...] = (),
) -> ReportExport:
    """Grava o memorial em ``.tex`` ou compila direto para ``.pdf`` (como o laudo)."""
    destination = Path(destination)
    as_pdf = destination.suffix.lower() == ".pdf"
    folder = destination.with_name(f"{destination.stem}_latex") if as_pdf else destination.parent
    folder.mkdir(parents=True, exist_ok=True)
    tex_path = folder / "memorial.tex" if as_pdf else destination
    tex_path.write_text(
        memorial_to_latex(html, equation_latex, element=element, members=members), encoding="utf-8",
    )
    export = ReportExport(tex_path=tex_path)
    if not as_pdf:
        return export
    engine = find_latex_engine()
    export.engine = engine
    if engine is None:
        export.error = (
            "Nenhum compilador LaTeX foi encontrado. "
            f"O arquivo .tex foi salvo em {folder} para compilar depois (por exemplo, no Overleaf)."
        )
        return export
    try:
        pdf = compile_latex(tex_path, engine)
    except LatexCompilationError as exc:
        export.error = str(exc)
        return export
    clean_auxiliary_files(tex_path)
    shutil.copyfile(pdf, destination)
    export.pdf_path = destination
    return export
