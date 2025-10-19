#!/usr/bin/env python3
"""
PDF Constructor API для генерации документов Intesa Sanpaolo
Поддерживает: contratto, garanzia, carta
"""

from io import BytesIO
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from weasyprint import HTML, CSS


def format_money(amount: float) -> str:
    """Форматирование суммы БЕЗ знака € (он уже есть в HTML)"""
    return f"{amount:,.2f}".replace(',', ' ')


def format_date() -> str:
    """Получение текущей даты в итальянском формате"""
    return datetime.now().strftime("%d/%m/%Y")


def monthly_payment(amount: float, months: int, annual_rate: float) -> float:
    """Аннуитетный расчёт ежемесячного платежа"""
    r = (annual_rate / 100) / 12
    if r == 0:
        return round(amount / months, 2)
    num = amount * r * (1 + r) ** months
    den = (1 + r) ** months - 1
    return round(num / den, 2)


def generate_contratto_pdf(data: dict) -> BytesIO:
    """
    API функция для генерации PDF договора
    
    Args:
        data (dict): Словарь с данными {
            'name': str - ФИО клиента,
            'amount': float - Сумма кредита,
            'duration': int - Срок в месяцах, 
            'tan': float - TAN процентная ставка,
            'taeg': float - TAEG эффективная ставка,
            'payment': float - Ежемесячный платеж (опционально, будет рассчитан)
        }
    
    Returns:
        BytesIO: PDF файл в памяти
    """
    # Рассчитываем платеж если не задан
    if 'payment' not in data:
        data['payment'] = monthly_payment(data['amount'], data['duration'], data['tan'])
    
    html = fix_html_layout('contrato')
    return _generate_pdf_with_images(html, 'contrato', data)


def generate_garanzia_pdf(name: str) -> BytesIO:
    """
    API функция для генерации PDF гарантийного письма
    
    Args:
        name (str): ФИО клиента
        
    Returns:
        BytesIO: PDF файл в памяти
    """
    html = fix_html_layout('garanzia')
    return _generate_pdf_with_images(html, 'garanzia', {'name': name})


def generate_carta_pdf(data: dict) -> BytesIO:
    """
    API функция для генерации PDF письма о карте
    
    Args:
        data (dict): Словарь с данными {
            'name': str - ФИО клиента,
            'amount': float - Сумма кредита,
            'duration': int - Срок в месяцах,
            'tan': float - TAN процентная ставка,
            'payment': float - Ежемесячный платеж (опционально, будет рассчитан)
        }
    
    Returns:
        BytesIO: PDF файл в памяти
    """
    # Рассчитываем платеж если не задан
    if 'payment' not in data:
        data['payment'] = monthly_payment(data['amount'], data['duration'], data['tan'])
    
    html = fix_html_layout('carta')
    return _generate_pdf_with_images(html, 'carta', data)


def _generate_pdf_with_images(html: str, template_name: str, data: dict) -> BytesIO:
    """Генерация PDF с сеткой 25x35 и overlay-изображениями.
    Для 'contrato/contratto':
    - Стр.1: company.png + logo.png
    - Стр.2: logo.png + sing_2.png + sing_1.png + seal.png
    
    Логика размещения 1 в 1 как в 1capital-main.
    """
    try:
        # --- GRID 25x35 ---
        page_w_mm = 210
        page_h_mm = 297
        cell_w_mm = page_w_mm / 25  # 8.4mm
        cell_h_mm = page_h_mm / 35  # 8.49mm

        grid_css = CSS(string='''
            .grid-overlay { position: fixed; top:0; left:0; width:210mm; height:297mm; pointer-events:none; z-index: 9999; }
            .grid-cell { position:absolute; border: 0.2mm solid rgba(0,128,255,0.25); box-sizing: border-box; }
            .grid-num { position:absolute; font-size:6pt; line-height:1; color: rgba(0,0,255,0.6); font-family: Arial, sans-serif; }
        ''')

        # Генерация HTML сетки 25x35 с нумерацией
        cells_html = []
        for r in range(35):
            for c in range(25):
                x = c * cell_w_mm
                y = r * cell_h_mm
                cells_html.append(
                    f'<div class="grid-cell" style="left:{x:.3f}mm; top:{y:.3f}mm; width:{cell_w_mm:.3f}mm; height:{cell_h_mm:.3f}mm"></div>'
                )
        top_nums = ''.join(
            f'<span class="grid-num" style="left:{j*cell_w_mm + 1:.3f}mm; top:0.8mm">{j+1}</span>' for j in range(25)
        )
        left_nums = ''.join(
            f'<span class="grid-num" style="left:0.8mm; top:{i*cell_h_mm + 1:.3f}mm">{i+1}</span>' for i in range(35)
        )
        grid_html = f'<div class="grid-overlay">{"".join(cells_html)}{top_nums}{left_nums}</div>'

        # Встраиваем overlay перед закрывающим </body>
        if '</body>' in html:
            html = html.replace('</body>', grid_html + '</body>')
        else:
            html += grid_html

        # Политика полей
        page_css = CSS(string='@page { margin-left: 0; margin-right: 0 }')
        footer_css = CSS(string='''
            @page {
              @bottom-center {
                content: "Documento riservato – A & G MONEY S.R.L. UNIPERSONALE";
                color: #646464;
                font-size: 9pt;
              }
            }
        ''')
        headings_css = CSS(string='h1, h2, h3 { font-weight: 700 !important; } h1 *, h2 *, h3 * { font-weight: 700 !important; }')

        # Рендерим базовый PDF
        pdf_bytes = HTML(string=html, base_url='.').write_pdf(stylesheets=[page_css, footer_css, headings_css, grid_css])

        # --- Overlay изображений через ReportLab ---
        # ТОЛЬКО logo.png и sing_1.png, БЕЗ лишних изображений
        if template_name in ('contrato', 'contratto'):
            from io import BytesIO as _BytesIO
            from reportlab.pdfgen import canvas as _canvas
            from reportlab.lib.pagesizes import A4 as _A4
            from reportlab.lib.units import mm as _mm
            from PyPDF2 import PdfReader as _PdfReader, PdfWriter as _PdfWriter
            from PIL import Image as _Image

            base_reader = _PdfReader(_BytesIO(pdf_bytes))
            writer = _PdfWriter()

            # Создаем overlay для каждой страницы
            overlay_buffers = []
            for page_num in range(len(base_reader.pages)):
                buf = _BytesIO()
                c = _canvas.Canvas(buf, pagesize=_A4)
                overlay_buffers.append((buf, c))

            # ========== ПАРАМЕТРЫ ИЗОБРАЖЕНИЙ ==========
            # logo.png - ТОЛЬКО на странице 1
            LOGO_SCALE = 0.3375  # Было 0.375, -10% = 0.375 * 0.9 = 0.3375
            LOGO_COL = 14        # Колонка (горизонталь): было 13, +1 = 14
            LOGO_ROW = 8         # Строка (вертикаль): было 9, -1 = 8 (вверх)
            
            # sing_1.png - ТОЛЬКО на странице 3
            SING1_SCALE = 0.175  # Было 0.25, -30% = 0.25 * 0.7 = 0.175
            SING1_COL = 14       # Колонка (горизонталь): было 12, +2 = 14
            SING1_ROW = 15.5     # Строка (вертикаль): было 15, +0.5 = 15.5

            # ========== СТРАНИЦА 1: logo.png ==========
            try:
                logo_img = _Image.open("logo.png")
                logo_width_mm = logo_img.width * 0.264583  # px → mm
                logo_height_mm = logo_img.height * 0.264583
                
                # Применяем масштаб
                logo_scaled_width = logo_width_mm * LOGO_SCALE
                logo_scaled_height = logo_height_mm * LOGO_SCALE
                
                # Рассчитываем позицию по клетке (col=7, row=16)
                # Клетка = (row - 1) * 25 + col
                x_logo = (LOGO_COL - 1) * cell_w_mm * _mm
                y_logo = (page_h_mm - LOGO_ROW * cell_h_mm) * _mm
                
                overlay_buffers[0][1].drawImage("logo.png", x_logo, y_logo,
                                               width=logo_scaled_width*_mm, 
                                               height=logo_scaled_height*_mm,
                                               mask='auto', 
                                               preserveAspectRatio=True)
                print(f"✅ logo.png добавлен на стр.1: клетка (col={LOGO_COL}, row={LOGO_ROW}), масштаб x{LOGO_SCALE}")
            except Exception as e:
                print(f"❌ Ошибка добавления logo.png: {e}")

            # ========== СТРАНИЦА 3: sing_1.png ==========
            try:
                if len(overlay_buffers) >= 3:  # Проверяем что есть 3 страница
                    sing1_img = _Image.open("sing_1.png")
                    sing1_width_mm = sing1_img.width * 0.264583  # px → mm
                    sing1_height_mm = sing1_img.height * 0.264583
                    
                    # Применяем масштаб
                    sing1_scaled_width = sing1_width_mm * SING1_SCALE
                    sing1_scaled_height = sing1_height_mm * SING1_SCALE
                    
                    # Рассчитываем позицию по клетке (col=12, row=15)
                    x_sing1 = (SING1_COL - 1) * cell_w_mm * _mm
                    y_sing1 = (page_h_mm - SING1_ROW * cell_h_mm) * _mm
                    
                    overlay_buffers[2][1].drawImage("sing_1.png", x_sing1, y_sing1,
                                                   width=sing1_scaled_width*_mm,
                                                   height=sing1_scaled_height*_mm,
                                                   mask='auto',
                                                   preserveAspectRatio=True)
                    print(f"✅ sing_1.png добавлен на стр.3: клетка (col={SING1_COL}, row={SING1_ROW}), масштаб x{SING1_SCALE}")
                else:
                    print(f"⚠️ Документ содержит только {len(overlay_buffers)} страниц, sing_1.png не добавлен")
            except Exception as e:
                print(f"❌ Ошибка добавления sing_1.png: {e}")

            # Сохраняем все overlay и мержим
            overlay_readers = []
            for buf, c in overlay_buffers:
                c.save()
                buf.seek(0)
                overlay_readers.append(_PdfReader(buf))
            
            for i, page in enumerate(base_reader.pages):
                if i < len(overlay_readers) and len(overlay_readers[i].pages) > 0:
                    page.merge_page(overlay_readers[i].pages[0])
                writer.add_page(page)

            final_buf = BytesIO()
            writer.write(final_buf)
            final_buf.seek(0)
            return final_buf

        # Без наложения
        buf = BytesIO(pdf_bytes)
        buf.seek(0)
        return buf
    except Exception as e:
        print(f"Ошибка генерации PDF: {e}")
        raise


def fix_html_layout(template_name='contrato'):
    """Возвращает исходный HTML без модификаций CSS/рамок/очисток."""
    html_file = f'{template_name}.html'
    try:
        with open(html_file, 'r', encoding='utf-8') as f:
            return f.read()
    except FileNotFoundError:
        alt = 'contrato' if template_name == 'contratto' else ('contratto' if template_name == 'contrato' else template_name)
        html_file = f'{alt}.html'
        with open(html_file, 'r', encoding='utf-8') as f:
            return f.read()


def main():
    """Функция для тестирования PDF конструктора"""
    import sys
    
    # Определяем какой шаблон обрабатывать
    template = sys.argv[1] if len(sys.argv) > 1 else 'contrato'
    
    print(f"🧪 Тестируем PDF конструктор для {template} через API...")
    
    # Тестовые данные
    test_data = {
        'name': 'Mario Rossi',
        'amount': 15000.0,
        'tan': 7.86,
        'taeg': 8.30, 
        'duration': 36,
        'payment': monthly_payment(15000.0, 36, 7.86)
    }
    
    try:
        if template in ('contrato', 'contratto'):
            buf = generate_contratto_pdf(test_data)
            filename = f'test_contrato.pdf'
        elif template == 'garanzia':
            buf = generate_garanzia_pdf(test_data['name'])
            filename = f'test_garanzia.pdf'
        elif template == 'carta':
            buf = generate_carta_pdf(test_data)
            filename = f'test_carta.pdf'
        else:
            print(f"❌ Неизвестный тип документа: {template}")
            return
        
        # Сохраняем тестовый PDF
        with open(filename, 'wb') as f:
            f.write(buf.read())
            
        print(f"✅ PDF создан через API! Файл сохранен как {filename}")
        print(f"📊 Данные: {test_data}")
        
    except Exception as e:
        print(f"❌ Ошибка тестирования API: {e}")


if __name__ == '__main__':
    main()
