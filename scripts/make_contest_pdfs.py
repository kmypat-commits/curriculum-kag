from pathlib import Path
import csv
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'output' / 'pdf'
OUT.mkdir(parents=True, exist_ok=True)
FONT = 'C:/Windows/Fonts/arial.ttf'
FONT_BOLD = 'C:/Windows/Fonts/arialbd.ttf'
pdfmetrics.registerFont(TTFont('Arial', FONT))
pdfmetrics.registerFont(TTFont('Arial-Bold', FONT_BOLD))

styles = getSampleStyleSheet()
styles.add(ParagraphStyle(name='TitleRu', parent=styles['Title'], fontName='Arial-Bold', fontSize=21, leading=26, textColor=colors.HexColor('#183b56'), spaceAfter=14))
styles.add(ParagraphStyle(name='H2Ru', parent=styles['Heading2'], fontName='Arial-Bold', fontSize=14, leading=18, textColor=colors.HexColor('#1268d5'), spaceBefore=13, spaceAfter=7))
styles.add(ParagraphStyle(name='BodyRu', parent=styles['BodyText'], fontName='Arial', fontSize=10.5, leading=15, textColor=colors.HexColor('#172033'), spaceAfter=8))
styles.add(ParagraphStyle(name='SmallRu', parent=styles['BodyText'], fontName='Arial', fontSize=8.5, leading=11, textColor=colors.HexColor('#425466')))

def footer(canvas, doc):
    canvas.saveState(); canvas.setFont('Arial', 8); canvas.setFillColor(colors.HexColor('#617089'))
    canvas.drawString(18*mm, 12*mm, 'Curriculum-KAG | конкурсные материалы')
    canvas.drawRightString(192*mm, 12*mm, f'{doc.page}')
    canvas.restoreState()

def make_doc(path, title, story):
    doc = SimpleDocTemplate(str(path), pagesize=A4, rightMargin=18*mm, leftMargin=18*mm, topMargin=17*mm, bottomMargin=20*mm, title=title, author='Curriculum-KAG')
    doc.build([Paragraph(title, styles['TitleRu']), Paragraph('Подготовлено для конкурсной заявки. Данные разделены на подтверждённые и планируемые к измерению.', styles['SmallRu']), Spacer(1, 7), *story], onFirstPage=footer, onLaterPages=footer)

def p(text, style='BodyRu'): return Paragraph(text, styles[style])

story = [p('Curriculum-KAG предназначен для вузов, разработчиков образовательных программ, руководителей образовательных направлений, методистов и экспертных комиссий.'), p('Система помогает проектировать программы бакалавриата, магистратуры и докторантуры, проверять результаты обучения, дисциплины, пререквизиты, кредиты и семестровую нагрузку.'), p('Для демонстрации и институциональных пилотов предусмотрен бесплатный demo-доступ. Интерфейс локализован на русском, казахском и английском языках. Поддерживаются междисциплинарные программы и bridge-модули для выравнивания входного уровня.'), p('В пилотах условия доступа могут адаптироваться для вузов с ограниченными ресурсами. Подтверждённые отзывы и кейсы конечных пользователей будут собраны после завершения пилотного внедрения.')]
make_doc(OUT/'01_cel_avaya_auditoriya_i_inklyuzivnost.pdf', 'Целевая аудитория и инклюзивность', story)

story = [p('Curriculum-KAG измеряет качество проектируемых программ по покрытию результатов обучения дисциплинами, соответствию кредитов и семестровой нагрузки, корректности цепочек пререквизитов, релевантности дисциплин, качеству bridge-модулей, доле рекомендаций AI, принятых экспертами, и времени подготовки программы.'), p('На текущем этапе подтверждены результаты исследовательской проверки AI-модели на 114 образовательных программах и 6 000 тестовых парах. Эти данные относятся к качеству рекомендаций и не являются статистикой успеваемости реальных студентов.'), p('Сравнение «до/после внедрения», пользовательская завершённость курсов, успеваемость и среднее время обучения будут измеряться на институциональных пилотах. Для пилотов предусмотрены показатели времени подготовки программы, доли принятых экспертами рекомендаций, количества исправлений и покрытия результатов обучения.')]
make_doc(OUT/'02_effektivnost_obucheniya.pdf', 'Эффективность обучения', story)

csv_path = ROOT/'docs'/'CONTEST_USAGE_ANALYTICS.csv'
rows = list(csv.reader(csv_path.open(encoding='utf-8-sig')))
headers = ['Метрика', 'Значение', 'Единица', 'Период', 'Статус', 'Реальное подтверждение / источник', 'Комментарий']
source_map = {
    'https://frontend-kojanoff.vercel.app/login': 'Публичный demo-портал: https://frontend-kojanoff.vercel.app/login',
    '../README.md': 'README.md в репозитории проекта', '../DATASET_CARD.md': 'DATASET_CARD.md в репозитории проекта',
    '../backend/ml/EPVO_MODEL_RESULTS_RU.md': 'backend/ml/EPVO_MODEL_RESULTS_RU.md: отчёт результатов модели',
    '../docs/scientific_article/TEM_SUPPLEMENTARY_MATERIALS_EN.md': 'docs/scientific_article/TEM_SUPPLEMENTARY_MATERIALS_EN.md: supplementary materials',
    'https://frontend-kojanoff.vercel.app/': 'Публичный demo-портал: https://frontend-kojanoff.vercel.app/'
}
status_map = {'verified': 'подтверждено', 'not_collected': 'не измерено'}
metric_map = {'registered_users': 'Зарегистрированные пользователи', 'MAU': 'MAU', 'DAU': 'DAU', 'average_session_duration': 'Средняя длительность сессии', 'approved_course_cards': 'Одобренные карточки дисциплин', 'course_learning_outcome_links': 'Связи дисциплина - результат обучения', 'evaluation_programmes': 'Проверенные образовательные программы', 'evaluation_pairs': 'Тестовые пары', 'demo_programmes': 'Демо-программы', 'languages': 'Языки интерфейса'}
unit_map = {'users': 'пользователи', 'minutes': 'минуты', 'cards': 'карточки', 'links': 'связи', 'programmes': 'программы', 'pairs': 'пары', 'languages': 'языки'}
period_map = {'до институционального пилота': 'до институционального пилота', 'текущий frozen baseline': 'текущий зафиксированный baseline', 'замороженная модельная оценка': 'зафиксированная модельная оценка', 'текущий Vercel demo': 'текущий demo-контур', 'текущий frontend': 'текущий frontend'}
story = [p('Агрегированные показатели системы. Реальные подтверждения указаны в колонке источника. Нулевые пользовательские показатели означают отсутствие подключённой пилотной когорты, а не успешную пользовательскую аналитику.'), Spacer(1, 5)]
data = [[p(x, 'SmallRu') for x in headers]]
for row in rows[1:]:
    row = row + [''] * (7 - len(row))
    data.append([p(metric_map.get(row[0], row[0]), 'SmallRu'), p(row[1] or '—', 'SmallRu'), p(unit_map.get(row[2], row[2]), 'SmallRu'), p(period_map.get(row[3], row[3]), 'SmallRu'), p(status_map.get(row[4], row[4]), 'SmallRu'), p(source_map.get(row[5], row[5]), 'SmallRu'), p(row[6], 'SmallRu')])
table = Table(data, colWidths=[35*mm, 18*mm, 20*mm, 33*mm, 25*mm, 73*mm, 52*mm], repeatRows=1, splitByRow=1)
table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#183b56')),('TEXTCOLOR',(0,0),(-1,0),colors.white),('FONTNAME',(0,0),(-1,0),'Arial-Bold'),('GRID',(0,0),(-1,-1),0.25,colors.HexColor('#d9e2ec')),('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),5),('RIGHTPADDING',(0,0),(-1,-1),5),('TOPPADDING',(0,0),(-1,-1),5),('BOTTOMPADDING',(0,0),(-1,-1),5),('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white, colors.HexColor('#f5f8fb')])]))
story.append(table)
doc = SimpleDocTemplate(str(OUT/'03_analitika_i_podtverzhdenie.pdf'), pagesize=landscape(A4), rightMargin=12*mm, leftMargin=12*mm, topMargin=12*mm, bottomMargin=16*mm, title='Аналитика и подтверждение в CSV', author='Curriculum-KAG')
doc.build([Paragraph('Аналитика и подтверждение в CSV', styles['TitleRu']), Paragraph('Реальные источники подтверждения указаны в таблице.', styles['SmallRu']), Spacer(1, 5), table], onFirstPage=footer, onLaterPages=footer)
print('\n'.join(str(x) for x in sorted(OUT.glob('*.pdf'))))
