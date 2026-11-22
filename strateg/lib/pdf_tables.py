"""Дополнительный вид таблиц исходного PDF с исходным порядком строк и столбцов."""
from __future__ import annotations

import io

import pdfplumber


def table_views(data: bytes) -> str:
    """Позиционная копия таблиц с видимой сеткой. Объединённые ячейки не угадываем."""
    views = []
    with pdfplumber.open(io.BytesIO(data)) as document:
        for page in document.pages:
            try:
                for index, table in enumerate(page.find_tables(), start=1):
                    if len(table.rows) < 2 or len(table.columns) < 2:
                        continue
                    crop = page.crop(table.bbox)
                    lines = crop.extract_text(layout=True, x_density=5).splitlines()
                    grid = "\n".join(line.rstrip() for line in lines if line.strip())
                    if grid.strip():
                        views.append(f"Страница {page.page_number}, таблица {index}\n\n```text\n{grid}\n```")
            finally:
                page.close()
    return "\n\n".join(views)
