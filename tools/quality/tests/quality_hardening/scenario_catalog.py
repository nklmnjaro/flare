from tools.quality.tests.quality_hardening.reporting import ScenarioMetadata

QH_N01 = ScenarioMetadata(
    "QH-N01",
    "Принять все поддерживаемые формы callable",
    "Политика исходного кода",
)
QH_N02 = ScenarioMetadata(
    "QH-N02",
    "Отклонить callable длиннее 80 строк",
    "Политика исходного кода",
)
QH_N03 = ScenarioMetadata(
    "QH-N03",
    "Считать decorators и nested callable физически",
    "Политика исходного кода",
)
QH_N04 = ScenarioMetadata(
    "QH-N04",
    "Различить границу строки 120 и 121",
    "Политика исходного кода",
)
QH_N05 = ScenarioMetadata(
    "QH-N05",
    "Принять корректные Conventional Commits",
    "Политика commit message",
)
QH_N06 = ScenarioMetadata(
    "QH-N06",
    "Отклонить нарушения commit-контракта",
    "Политика commit message",
)
QH_N07 = ScenarioMetadata(
    "QH-N07",
    "Проверить обязательную структуру и PR title",
    "Политика репозитория",
)
QH_N08 = ScenarioMetadata(
    "QH-N08",
    "Защитить local env и повреждённый Git index",
    "Политика репозитория",
)
QH_N09 = ScenarioMetadata(
    "QH-N09",
    "Сохранить read-only doctor и canonical facade",
    "Политика репозитория",
)
QH_N10 = ScenarioMetadata(
    "QH-N10",
    "Зафиксировать архитектуру тестов через AST",
    "Политика архитектуры тестов",
)
QH_N11 = ScenarioMetadata(
    "QH-N11",
    "Проверить полезность Quality Allure evidence",
    "Политика Allure evidence",
)
QH_N12 = ScenarioMetadata(
    "QH-N12",
    "Сохранить корректность синхронной и асинхронной отчётности",
    "Корректность отчётности",
)
QH_N13 = ScenarioMetadata(
    "QH-N13",
    "Принять плоский и вложенный dependency bundle",
    "Целостность dependency bundle",
)
QH_N14 = ScenarioMetadata(
    "QH-N14",
    "Отклонить неполный или неоднозначный внутренний manifest",
    "Целостность dependency bundle",
)
QH_N15 = ScenarioMetadata(
    "QH-N15",
    "Отклонить небезопасную топологию tar-архива",
    "Целостность dependency bundle",
)
QH_N16 = ScenarioMetadata(
    "QH-N16",
    "Отклонить неоднозначную detached checksum",
    "Целостность dependency bundle",
)
QH_N17 = ScenarioMetadata(
    "QH-N17",
    "Защитить границу source discovery и типов файлов",
    "Политика исходного кода",
)
QH_N18 = ScenarioMetadata(
    "QH-N18",
    "Отклонить suppression-директивы закреплённых инструментов",
    "Политика исходного кода",
)

QUALITY_SCENARIOS = (
    QH_N01,
    QH_N02,
    QH_N03,
    QH_N04,
    QH_N05,
    QH_N06,
    QH_N07,
    QH_N08,
    QH_N09,
    QH_N10,
    QH_N11,
    QH_N12,
    QH_N13,
    QH_N14,
    QH_N15,
    QH_N16,
    QH_N17,
    QH_N18,
)
