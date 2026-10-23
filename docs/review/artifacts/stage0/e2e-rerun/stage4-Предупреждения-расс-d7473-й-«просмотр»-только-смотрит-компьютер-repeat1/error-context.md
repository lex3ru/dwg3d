# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: stage4.spec.ts >> Предупреждения расстановки: стена, дверь, вне помещений; «просмотр» только смотрит
- Location: tests\stage4.spec.ts:171:1

# Error details

```
Error: expect(locator).toHaveCount(expected) failed

Locator:  getByRole('img', { name: 'План этажа' }).locator('[data-item]')
Expected: 3
Received: 0
Timeout:  5000ms

Call log:
  - Expect "toHaveCount" getByRole('img', { name: 'План этажа' }).locator('[data-item]') with timeout 5000ms
  - waiting for getByRole('img', { name: 'План этажа' }).locator('[data-item]')
    14 × locator resolved to 0 elements
       - unexpected value "0"

```

# Page snapshot

```yaml
- generic [ref=f1e3]:
  - navigation "Разделы" [ref=f1e4]:
    - generic [ref=f1e6]:
      - generic [ref=f1e7]: Планировка и учёт
      - generic [ref=f1e8]: имущества здания
    - generic [ref=f1e9]:
      - generic [ref=f1e10]: Здание
      - combobox "Здание" [ref=f1e11]:
        - option "8.2-mvht8hnd"
        - option "8.2-расчёты-mvht8od2"
        - option "Инвентаризация-mvht9z68"
        - option "Инвентаризация-mvhta06j"
        - option "Инвентаризация-mvhta1f7"
        - option "Инвентаризация-mvhta2b9"
        - option "Инвентаризация-mvhtabf0"
        - option "Проекты-mvht9qt0"
        - option "Проекты-mvhtbvkx"
        - option "Просмотр-mvht8uyk"
        - option "Расчёты-mvht9ocr"
        - option "Расчёты-mvht9pdf"
        - option "С1-mvht8xvh"
        - option "С2-mvht8sej"
        - option "С3-mvht8u6v"
        - option "С4-mvht93nm"
        - option "С6-mvht949j"
        - option "С6-mvht9659"
        - option "С6-mvht974x"
        - option "С6-mvht9er5"
        - option "С6-mvhtbkc3"
        - option "С6-mvhtbm7t"
        - option "С6-mvhtbn99"
        - option "С6-mvhtbuly"
        - option "С6-mvhtcse8"
        - option "С6-mvhtcuc6"
        - option "С6-mvhtcv6z" [selected]
        - option "Связь-mvht9ksk"
        - option "Связь-mvht9my1"
        - option "Связь-mvhta9zs"
        - option "Учёт-mvht9fpz"
        - option "Учёт-mvht9idp"
    - generic [ref=f1e12]:
      - link "Главная" [ref=f1e14] [cursor=pointer]:
        - /url: /
      - generic [ref=f1e19]:
        - generic [ref=f1e20]: Планировка
        - link "План и расстановка" [ref=f1e21] [cursor=pointer]:
          - /url: /plan
        - link "Проекты" [ref=f1e30] [cursor=pointer]:
          - /url: /projects
      - generic [ref=f1e34]:
        - generic [ref=f1e35]: Учёт имущества
        - link "Имущество" [ref=f1e36] [cursor=pointer]:
          - /url: /property
        - link "Склад" [ref=f1e42] [cursor=pointer]:
          - /url: /warehouse
        - link "Документы" [ref=f1e47] [cursor=pointer]:
          - /url: /documents
        - link "Инвентаризация" [ref=f1e52] [cursor=pointer]:
          - /url: /inventory
      - link "Отчёты" [ref=f1e59] [cursor=pointer]:
        - /url: /reports
      - generic [ref=f1e63]:
        - generic [ref=f1e64]: Справочники
        - link "Каталог" [ref=f1e65] [cursor=pointer]:
          - /url: /catalog
        - link "Назначения помещений" [ref=f1e69] [cursor=pointer]:
          - /url: /purposes
      - generic [ref=f1e74]:
        - generic [ref=f1e75]: Управление
        - link "Здания" [ref=f1e76] [cursor=pointer]:
          - /url: /buildings
        - link "Пользователи" [ref=f1e82] [cursor=pointer]:
          - /url: /users
        - link "Ссылки на просмотр" [ref=f1e89] [cursor=pointer]:
          - /url: /links
        - link "Журнал" [ref=f1e94] [cursor=pointer]:
          - /url: /journal
        - link "Настройки" [ref=f1e100] [cursor=pointer]:
          - /url: /settings
    - button "Свернуть меню" [ref=f1e105] [cursor=pointer]: Свернуть
  - generic [ref=f1e109]:
    - banner [ref=f1e110]:
      - navigation "Где я" [ref=f1e111]:
        - generic [ref=f1e112]: Планировка
        - generic [ref=f1e114]: План и расстановка
        - generic [ref=f1e118]: С6-mvhtcv6z · 2 этаж
      - generic [ref=f1e122]:
        - generic [ref=f1e123]: Поиск
        - searchbox "Поиск" [ref=f1e124]
      - link "QR-сканер" [ref=f1e125] [cursor=pointer]:
        - /url: /scan
      - button "Справка" [ref=f1e132]
      - 'button "Пользователь: Администратор, администратор" [ref=f1e136] [cursor=pointer]':
        - generic [ref=f1e137]: А
        - generic [ref=f1e138]:
          - generic [ref=f1e139]: Администратор
          - generic [ref=f1e140]: администратор
    - main [ref=f1e142]:
      - generic [ref=f1e143]:
        - generic [ref=f1e144]:
          - generic [ref=f1e145]:
            - generic [ref=f1e149]: Этаж
            - combobox "Этаж" [ref=f1e150]:
              - option "2 этаж" [selected]
          - button "этаж" [ref=f1e151] [cursor=pointer]
          - combobox "Расстановка или проект" [ref=f1e153]:
            - option "Как есть" [selected]
          - tablist "Режим" [ref=f1e154]:
            - tab "Строительство" [ref=f1e155] [cursor=pointer]
            - tab "Расстановка" [active] [selected] [ref=f1e156] [cursor=pointer]
          - radiogroup "Вид" [ref=f1e157]:
            - radio "2D" [checked] [ref=f1e158] [cursor=pointer]
            - radio "3D" [ref=f1e159] [cursor=pointer]
            - radio "оба" [ref=f1e160] [cursor=pointer]
          - button "Отменить (Ctrl+Z)" [disabled]
          - button "Повторить (Ctrl+Y)" [disabled]
          - group "Привязки" [ref=f1e161]:
            - generic [ref=f1e162] [cursor=pointer]:
              - checkbox "к стенам" [checked] [ref=f1e163]
              - text: к стенам
            - generic [ref=f1e164] [cursor=pointer]:
              - checkbox "углы 45°" [checked] [ref=f1e165]
              - text: углы 45°
            - generic [ref=f1e166] [cursor=pointer]:
              - checkbox "сетка 100 мм" [checked] [ref=f1e167]
              - text: сетка 100 мм
          - button "Показать весь этаж" [ref=f1e168] [cursor=pointer]
          - button "Печать и выгрузка" [ref=f1e174] [cursor=pointer]
          - button "Подсказка по клавишам" [ref=f1e179] [cursor=pointer]
          - generic [ref=f1e183]: Расстановка сохраняется сразу
          - button "Сохранить план" [disabled]
        - generic [ref=f1e184]:
          - complementary "Слои и каталог" [ref=f1e185]:
            - generic [ref=f1e186]:
              - tablist "Панель расстановки" [ref=f1e187]:
                - tab "Каталог" [selected] [ref=f1e188] [cursor=pointer]
                - tab "Слои" [ref=f1e194] [cursor=pointer]
                - tab "Учёт" [ref=f1e199] [cursor=pointer]
                - tab "Расчёты" [ref=f1e205] [cursor=pointer]
              - region "Каталог" [ref=f1e209]:
                - textbox "Поиск в каталоге" [ref=f1e214]:
                  - /placeholder: Поиск
                - generic [ref=f1e215]:
                  - button "все" [pressed] [ref=f1e216] [cursor=pointer]
                  - button "Мебель" [ref=f1e217] [cursor=pointer]
                  - button "Оборудование" [ref=f1e218] [cursor=pointer]
                  - button "Видеонаблюдение" [ref=f1e219] [cursor=pointer]
                  - button "Освещение" [ref=f1e220] [cursor=pointer]
                  - button "СКУД mvht90yt" [ref=f1e221] [cursor=pointer]
                - list "Типы для расстановки" [ref=f1e222]:
                  - listitem [ref=f1e223]:
                    - button "Автоклав" [ref=f1e224]
                  - listitem [ref=f1e227]:
                    - button "Авторефкератометр" [ref=f1e228]
                  - listitem [ref=f1e231]:
                    - button "Аппарат Рота (таблица Сивцева) на стену" [ref=f1e232]:
                      - generic [ref=f1e234]: Аппарат Рота (таблица Сивцева)
                      - generic [ref=f1e235]: на стену
                  - listitem [ref=f1e236]:
                    - button "Аппарат УЗИ" [ref=f1e237]
                  - listitem [ref=f1e240]:
                    - button "Аппарат УЗИ mvht8zom" [ref=f1e241]
                  - listitem [ref=f1e244]:
                    - button "Аспиратор хирургический" [ref=f1e245]
                  - listitem [ref=f1e248]:
                    - button "Весы медицинские" [ref=f1e249]
                  - listitem [ref=f1e252]:
                    - button "Вешалка гардеробная" [ref=f1e253]
                  - listitem [ref=f1e256]:
                    - button "Вешалка напольная" [ref=f1e257]
                  - listitem [ref=f1e260]:
                    - button "Видеорегистратор во вместилище" [ref=f1e261]:
                      - generic [ref=f1e263]: Видеорегистратор
                      - generic [ref=f1e264]: во вместилище
                  - listitem [ref=f1e265]:
                    - button "Глюкометр во вместилище" [ref=f1e266]:
                      - generic [ref=f1e268]: Глюкометр
                      - generic [ref=f1e269]: во вместилище
                  - listitem [ref=f1e270]:
                    - button "гцврпжсшмрпк" [ref=f1e271]
                  - listitem [ref=f1e274]:
                    - button "Дефибриллятор на стену" [ref=f1e275]:
                      - generic [ref=f1e277]: Дефибриллятор
                      - generic [ref=f1e278]: на стену
                  - listitem [ref=f1e279]:
                    - button "Диван" [ref=f1e280]
                  - listitem [ref=f1e283]:
                    - button "ИБП" [ref=f1e284]
                  - listitem [ref=f1e287]:
                    - button "Информационная панель на стену" [ref=f1e288]:
                      - generic [ref=f1e290]: Информационная панель
                      - generic [ref=f1e291]: на стену
                  - listitem [ref=f1e292]:
                    - button "Камера «рыбий глаз» на потолок" [ref=f1e293]:
                      - generic [ref=f1e295]: Камера «рыбий глаз»
                      - generic [ref=f1e296]: на потолок
                  - listitem [ref=f1e297]:
                    - button "Камера купольная на потолок" [ref=f1e298]:
                      - generic [ref=f1e300]: Камера купольная
                      - generic [ref=f1e301]: на потолок
                  - listitem [ref=f1e302]:
                    - button "Камера поворотная (PTZ) на стену" [ref=f1e303]:
                      - generic [ref=f1e305]: Камера поворотная (PTZ)
                      - generic [ref=f1e306]: на стену
                  - listitem [ref=f1e307]:
                    - button "Камера цилиндрическая на стену" [ref=f1e308]:
                      - generic [ref=f1e310]: Камера цилиндрическая
                      - generic [ref=f1e311]: на стену
                  - listitem [ref=f1e312]:
                    - button "Каталка медицинская" [ref=f1e313]
                  - listitem [ref=f1e316]:
                    - button "Кольпоскоп" [ref=f1e317]
                  - listitem [ref=f1e320]:
                    - button "Коммутатор во вместилище" [ref=f1e321]:
                      - generic [ref=f1e323]: Коммутатор
                      - generic [ref=f1e324]: во вместилище
                  - listitem [ref=f1e325]:
                    - button "Компьютер" [ref=f1e326]
                  - listitem [ref=f1e329]:
                    - button "Кондиционер (сплит-система) на стену" [ref=f1e330]:
                      - generic [ref=f1e332]: Кондиционер (сплит-система)
                      - generic [ref=f1e333]: на стену
                  - listitem [ref=f1e334]:
                    - button "Кресло врача" [ref=f1e335]
                  - listitem [ref=f1e338]:
                    - button "Кресло гинекологическое" [ref=f1e339]
                  - listitem [ref=f1e342]:
                    - button "Кресло офисное" [ref=f1e343]
                  - listitem [ref=f1e346]:
                    - button "Кресло руководителя" [ref=f1e347]
                  - listitem [ref=f1e350]:
                    - button "Кресло-коляска" [ref=f1e351]
                  - listitem [ref=f1e354]:
                    - button "Кровать функциональная" [ref=f1e355]
                  - listitem [ref=f1e358]:
                    - button "Кулер для воды" [ref=f1e359]
                  - listitem [ref=f1e362]:
                    - button "Кушетка массажная" [ref=f1e363]
                  - listitem [ref=f1e366]:
                    - button "Кушетка смотровая" [ref=f1e367]
                  - listitem [ref=f1e370]:
                    - button "Микроволновая печь во вместилище" [ref=f1e371]:
                      - generic [ref=f1e373]: Микроволновая печь
                      - generic [ref=f1e374]: во вместилище
                  - listitem [ref=f1e375]:
                    - button "Молоток неврологический во вместилище" [ref=f1e376]:
                      - generic [ref=f1e378]: Молоток неврологический
                      - generic [ref=f1e379]: во вместилище
                  - listitem [ref=f1e380]:
                    - button "Монитор 24″" [ref=f1e381]
                  - listitem [ref=f1e384]:
                    - button "Монитор видеонаблюдения" [ref=f1e385]
                  - listitem [ref=f1e388]:
                    - button "Монитор пациента" [ref=f1e389]
                  - listitem [ref=f1e392]:
                    - button "Моноблок" [ref=f1e393]
                  - listitem [ref=f1e396]:
                    - button "МФУ лазерное" [ref=f1e397]
                  - listitem [ref=f1e400]:
                    - button "Небулайзер во вместилище" [ref=f1e401]:
                      - generic [ref=f1e403]: Небулайзер
                      - generic [ref=f1e404]: во вместилище
                  - listitem [ref=f1e405]:
                    - button "Негатоскоп на стену" [ref=f1e406]:
                      - generic [ref=f1e408]: Негатоскоп
                      - generic [ref=f1e409]: на стену
                  - listitem [ref=f1e410]:
                    - button "Носилки во вместилище" [ref=f1e411]:
                      - generic [ref=f1e413]: Носилки
                      - generic [ref=f1e414]: во вместилище
                  - listitem [ref=f1e415]:
                    - button "Ноутбук во вместилище" [ref=f1e416]:
                      - generic [ref=f1e418]: Ноутбук
                      - generic [ref=f1e419]: во вместилище
                  - listitem [ref=f1e420]:
                    - button "Облучатель бактерицидный настенный на стену" [ref=f1e421]:
                      - generic [ref=f1e423]: Облучатель бактерицидный настенный
                      - generic [ref=f1e424]: на стену
                  - listitem [ref=f1e425]:
                    - button "Облучатель-рециркулятор на стену" [ref=f1e426]:
                      - generic [ref=f1e428]: Облучатель-рециркулятор
                      - generic [ref=f1e429]: на стену
                  - listitem [ref=f1e430]:
                    - button "Отоскоп во вместилище" [ref=f1e431]:
                      - generic [ref=f1e433]: Отоскоп
                      - generic [ref=f1e434]: во вместилище
                  - listitem [ref=f1e435]:
                    - button "Офтальмоскоп во вместилище" [ref=f1e436]:
                      - generic [ref=f1e438]: Офтальмоскоп
                      - generic [ref=f1e439]: во вместилище
                  - listitem [ref=f1e440]:
                    - button "Принтер этикеток" [ref=f1e441]
                  - listitem [ref=f1e444]:
                    - button "Проектор знаков на стену" [ref=f1e445]:
                      - generic [ref=f1e447]: Проектор знаков
                      - generic [ref=f1e448]: на стену
                  - listitem [ref=f1e449]:
                    - button "Пульсоксиметр во вместилище" [ref=f1e450]:
                      - generic [ref=f1e452]: Пульсоксиметр
                      - generic [ref=f1e453]: во вместилище
                  - listitem [ref=f1e454]:
                    - button "Ростомер" [ref=f1e455]
                  - listitem [ref=f1e458]:
                    - button "Светильник аварийный «Выход» на стену" [ref=f1e459]:
                      - generic [ref=f1e461]: Светильник аварийный «Выход»
                      - generic [ref=f1e462]: на стену
                  - listitem [ref=f1e463]:
                    - button "Светильник для чистых помещений на потолок" [ref=f1e464]:
                      - generic [ref=f1e466]: Светильник для чистых помещений
                      - generic [ref=f1e467]: на потолок
                  - listitem [ref=f1e468]:
                    - button "Светильник круглый накладной на потолок" [ref=f1e469]:
                      - generic [ref=f1e471]: Светильник круглый накладной
                      - generic [ref=f1e472]: на потолок
                  - listitem [ref=f1e473]:
                    - button "Светильник линейный 1200 на потолок" [ref=f1e474]:
                      - generic [ref=f1e476]: Светильник линейный 1200
                      - generic [ref=f1e477]: на потолок
                  - listitem [ref=f1e478]:
                    - button "Светильник настенный на стену" [ref=f1e479]:
                      - generic [ref=f1e481]: Светильник настенный
                      - generic [ref=f1e482]: на стену
                  - listitem [ref=f1e483]:
                    - button "Светильник настольный во вместилище" [ref=f1e484]:
                      - generic [ref=f1e486]: Светильник настольный
                      - generic [ref=f1e487]: во вместилище
                  - listitem [ref=f1e488]:
                    - button "Светильник светодиодный 600×600 на потолок" [ref=f1e489]:
                      - generic [ref=f1e491]: Светильник светодиодный 600×600
                      - generic [ref=f1e492]: на потолок
                  - listitem [ref=f1e493]:
                    - button "Светильник смотровой передвижной" [ref=f1e494]
                  - listitem [ref=f1e497]:
                    - button "Светильник хирургический передвижной" [ref=f1e498]
                  - listitem [ref=f1e501]:
                    - button "Сейф для лекарственных средств" [ref=f1e502]
                  - listitem [ref=f1e505]:
                    - button "Секция стульев трёхместная" [ref=f1e506]
                  - listitem [ref=f1e509]:
                    - button "Сервер во вместилище" [ref=f1e510]:
                      - generic [ref=f1e512]: Сервер
                      - generic [ref=f1e513]: во вместилище
                  - listitem [ref=f1e514]:
                    - button "Сканер штрихкода во вместилище" [ref=f1e515]:
                      - generic [ref=f1e517]: Сканер штрихкода
                      - generic [ref=f1e518]: во вместилище
                  - listitem [ref=f1e519]:
                    - button "Спирометр во вместилище" [ref=f1e520]:
                      - generic [ref=f1e522]: Спирометр
                      - generic [ref=f1e523]: во вместилище
                  - listitem [ref=f1e524]:
                    - button "Стеллаж" [ref=f1e525]
                  - listitem [ref=f1e528]:
                    - button "Стерилизатор воздушный" [ref=f1e529]
                  - listitem [ref=f1e532]:
                    - button "Стойка регистратуры" [ref=f1e533]
                  - listitem [ref=f1e536]:
                    - button "Стол инструментальный" [ref=f1e537]
                  - listitem [ref=f1e540]:
                    - button "Стол манипуляционный" [ref=f1e541]
                  - listitem [ref=f1e544]:
                    - button "Стол пеленальный" [ref=f1e545]
                  - listitem [ref=f1e548]:
                    - button "Стол перевязочный" [ref=f1e549]
                  - listitem [ref=f1e552]:
                    - button "Стол письменный 1200×600" [ref=f1e553]
                  - listitem [ref=f1e556]:
                    - button "Стол письменный 1400×700" [ref=f1e557]
                  - listitem [ref=f1e560]:
                    - button "Стол приставной" [ref=f1e561]
                  - listitem [ref=f1e564]:
                    - button "Стол процедурный" [ref=f1e565]
                  - listitem [ref=f1e568]:
                    - button "Стол руководителя" [ref=f1e569]
                  - listitem [ref=f1e572]:
                    - button "Стул медицинский винтовой" [ref=f1e573]
                  - listitem [ref=f1e576]:
                    - button "Стул посетителя" [ref=f1e577]
                  - listitem [ref=f1e580]:
                    - button "Считыватель mvht91bs" [ref=f1e581]
                  - listitem [ref=f1e584]:
                    - button "Телефон IP" [ref=f1e585]
                  - listitem [ref=f1e588]:
                    - button "Терминал электронной очереди" [ref=f1e589]
                  - listitem [ref=f1e592]:
                    - button "Тонометр во вместилище" [ref=f1e593]:
                      - generic [ref=f1e595]: Тонометр
                      - generic [ref=f1e596]: во вместилище
                  - listitem [ref=f1e597]:
                    - button "Точка доступа Wi-Fi на потолок" [ref=f1e598]:
                      - generic [ref=f1e600]: Точка доступа Wi-Fi
                      - generic [ref=f1e601]: на потолок
                  - listitem [ref=f1e602]:
                    - button "Тумба подкатная" [ref=f1e603]
                  - listitem [ref=f1e606]:
                    - button "УФ-камера для хранения инструментов" [ref=f1e607]
                  - listitem [ref=f1e610]:
                    - button "Фонендоскоп во вместилище" [ref=f1e611]:
                      - generic [ref=f1e613]: Фонендоскоп
                      - generic [ref=f1e614]: во вместилище
                  - listitem [ref=f1e615]:
                    - button "Холодильник бытовой" [ref=f1e616]
                  - listitem [ref=f1e619]:
                    - button "Холодильник фармацевтический" [ref=f1e620]
                  - listitem [ref=f1e623]:
                    - button "Холтеровский монитор во вместилище" [ref=f1e624]:
                      - generic [ref=f1e626]: Холтеровский монитор
                      - generic [ref=f1e627]: во вместилище
                  - listitem [ref=f1e628]:
                    - button "Ширма медицинская" [ref=f1e629]
                  - listitem [ref=f1e632]:
                    - button "Шкаф для документов" [ref=f1e633]
                  - listitem [ref=f1e636]:
                    - button "Шкаф для одежды" [ref=f1e637]
                  - listitem [ref=f1e640]:
                    - button "Шкаф медицинский двухстворчатый" [ref=f1e641]
                  - listitem [ref=f1e644]:
                    - button "Шкаф медицинский одностворчатый" [ref=f1e645]
                  - listitem [ref=f1e648]:
                    - button "Шкаф телекоммуникационный 19″" [ref=f1e649]
                  - listitem [ref=f1e652]:
                    - button "Шкаф телекоммуникационный настенный на стену" [ref=f1e653]:
                      - generic [ref=f1e655]: Шкаф телекоммуникационный настенный
                      - generic [ref=f1e656]: на стену
                  - listitem [ref=f1e657]:
                    - button "Щелевая лампа" [ref=f1e658]
                  - listitem [ref=f1e661]:
                    - button "Электрозамок mvht91i8" [ref=f1e662]
                  - listitem [ref=f1e665]:
                    - button "Электрокардиограф" [ref=f1e666]
                  - listitem [ref=f1e669]:
                    - button "Электрокоагулятор во вместилище" [ref=f1e670]:
                      - generic [ref=f1e672]: Электрокоагулятор
                      - generic [ref=f1e673]: во вместилище
                - paragraph [ref=f1e674]: Перетащите на план — или выберите и щёлкните по плану (Shift — несколько раз).
          - img "План этажа" [ref=f1e677]:
            - generic [ref=f1e705]:
              - generic:
                - generic: "215"
                - generic: Кабинет
                - generic: 21,94 м²
              - generic:
                - generic: 1К
                - generic: Коридор
                - generic: 20,94 м²
              - generic:
                - generic: "214"
                - generic: Кабинет
                - generic: 21,94 м²
            - generic: 2 м
          - complementary "Свойства" [ref=f1e706]:
            - generic [ref=f1e707]:
              - heading "Расстановка этажа" [level=3] [ref=f1e708]
              - paragraph [ref=f1e709]: "Предметов: 3. Перетащите тип из каталога слева на план; выбранный предмет двигается мышью, поворачивается ручкой (шаг 15°, Alt — свободно), Delete — убрать, Ctrl+D — копия."
            - region "Предупреждения расстановки" [ref=f1e710]:
              - 'heading "Предупреждения предметов: 3" [level=3] [ref=f1e711]':
                - text: Предупреждения
                - generic [ref=f1e712]: "предметов: 3"
              - list [ref=f1e713]:
                - listitem [ref=f1e714]:
                  - generic [ref=f1e716]:
                    - text: Стол письменный 1200×600
                    - generic [ref=f1e717]: пересекает стену, стоит вне помещений · вне помещений
                  - button "Показать" [ref=f1e718] [cursor=pointer]
                - listitem [ref=f1e719]:
                  - generic [ref=f1e721]:
                    - text: Стол письменный 1200×600
                    - generic [ref=f1e722]: перекрывает проём двери · 214 Кабинет
                  - button "Показать" [ref=f1e723] [cursor=pointer]
                - listitem [ref=f1e724]:
                  - generic [ref=f1e726]:
                    - text: Стол письменный 1200×600
                    - generic [ref=f1e727]: стоит вне помещений · вне помещений
                  - button "Показать" [ref=f1e728] [cursor=pointer]
```

# Test source

```ts
  105 |   await placeAt(page, "Кушетка смотровая", 1000, 3800);
  106 |   // шкаф — посреди кабинета, потом к стене: прилипает спиной
  107 |   await placeAt(page, "Шкаф для документов", 4500, 4000);
  108 |   await expect.poll(async () => (await items(page, f.floor)).length).toBe(5);
  109 |   const cabinetType = await typeId(page, "Шкаф для документов");
  110 |   const cabinet = (await items(page, f.floor)).find((i) => i.type_id === cabinetType)!;
  111 |   expect(cabinet.angle).toBe(0);
  112 |   const from = await screen(page, 4500, 4000);
  113 |   const to = await screen(page, 4500, 5700);
  114 |   await page.mouse.move(from.x, from.y);
  115 |   await page.mouse.down();
  116 |   for (let k = 1; k <= 10; k++) await page.mouse.move(from.x, from.y + ((to.y - from.y) * k) / 10);
  117 |   await page.mouse.up();
  118 |   // спиной к стене кабинета: грань стены 6000 − 150, шкаф глубиной 400 — центр на 5650
  119 |   await expect.poll(async () => {
  120 |     const c = (await items(page, f.floor)).find((i) => i.id === cabinet.id)!;
  121 |     return [Math.round(c.y), c.angle];
  122 |   }).toEqual([5650, 180]);
  123 | 
  124 |   // кушетку поворачивает
  125 |   const couchType = await typeId(page, "Кушетка смотровая");
  126 |   const couch = (await items(page, f.floor)).find((i) => i.type_id === couchType)!;
  127 |   const c = await screen(page, couch.x, couch.y);
  128 |   await page.mouse.click(c.x, c.y);
  129 |   await expect(page.getByRole("heading", { name: "Кушетка смотровая" })).toBeVisible();
  130 |   await page.getByRole("button", { name: "+90°" }).click();
  131 |   await expect.poll(async () => (await items(page, f.floor)).find((i) => i.id === couch.id)!.angle).toBe(90);
  132 |   // отмена и повтор — тоже сразу на сервере
  133 |   await page.keyboard.press("Control+z");
  134 |   await expect.poll(async () => (await items(page, f.floor)).find((i) => i.id === couch.id)!.angle).toBe(0);
  135 |   await page.keyboard.press("Control+y");
  136 |   await expect.poll(async () => (await items(page, f.floor)).find((i) => i.id === couch.id)!.angle).toBe(90);
  137 | 
  138 |   // результат: расстановка кабинета на плане — всё в 214
  139 |   const placed = await items(page, f.floor);
  140 |   expect(placed.map((i) => i.room_id)).toEqual(Array(5).fill(f.rooms["214"]));
  141 |   // и в 3D
  142 |   await page.getByRole("radio", { name: "оба" }).click();
  143 |   await expect(page.locator("canvas")).toBeVisible();
  144 |   // журнал знает, кто и что ставил
  145 |   const history = (await (await page.request.get("/api/journal", { params: { ref: `room:${f.rooms["214"]}` } })).json()).items;
  146 |   expect(history.some((h: { summary: string }) => h.summary.includes("поставлены: Шкаф для документов"))).toBeTruthy();
  147 | });
  148 | 
  149 | test("С8: светильник на потолок коридора и ряд с шагом 3 м до конца коридора", async ({ page }) => {
  150 |   await loginAdmin(page);
  151 |   const f = await floorWithRooms(page);
  152 |   await page.goto(`/plan/${f.building}/${f.floor}`);
  153 |   await page.getByRole("tab", { name: "Расстановка" }).click();
  154 |   // освещение по умолчанию скрыто — включить
  155 |   await page.getByRole("tab", { name: "Слои" }).click();
  156 |   await page.getByRole("button", { name: "Показать слой Освещение" }).click();
  157 |   await placeAt(page, "Светильник светодиодный 600×600", 1500, 1000);
  158 |   await expect(page.getByRole("heading", { name: "Светильник светодиодный 600×600" })).toBeVisible();
  159 |   const step = page.getByRole("textbox", { name: /^Шаг вдоль/ });
  160 |   await step.fill("3000");
  161 |   await step.press("Enter");
  162 |   await page.getByRole("button", { name: "До конца помещения" }).click();
  163 |   await page.getByRole("button", { name: "Поставить копии (3)" }).click();
  164 |   await expect.poll(async () => (await items(page, f.floor)).length).toBe(4);
  165 |   const lamps = (await items(page, f.floor)).sort((a, b) => a.x - b.x);
  166 |   expect(lamps.map((l) => l.x)).toEqual([1500, 4500, 7500, 10500]);
  167 |   // на потолке: низ светильника — высота этажа минус его высота
  168 |   expect(lamps.every((l) => l.z === 3300 - 40 && l.room_id === f.rooms["1К"])).toBeTruthy();
  169 | });
  170 | 
  171 | test("Предупреждения расстановки: стена, дверь, вне помещений; «просмотр» только смотрит", async ({ page, browser }) => {
  172 |   await loginAdmin(page);
  173 |   const f = await floorWithRooms(page);
  174 |   const table = await typeId(page, "Стол письменный 1200×600");
  175 |   const r = await page.request.post(`/api/floors/${f.floor}/items/changes`, {
  176 |     headers: H,
  177 |     data: {
  178 |       create: [
  179 |         { type_id: table, x: 6000, y: 4000 }, // на перегородке
  180 |         { type_id: table, x: 4500, y: 2700 }, // в проёме двери
  181 |         { type_id: table, x: 15000, y: 4000 }, // за стенами
  182 |       ],
  183 |     },
  184 |   });
  185 |   expect(r.ok()).toBeTruthy();
  186 |   await page.goto(`/plan/${f.building}/${f.floor}`);
  187 |   await page.getByRole("tab", { name: "Расстановка" }).click();
  188 |   const list = page.getByRole("region", { name: "Предупреждения расстановки" });
  189 |   await expect(list.getByText("предметов: 3")).toBeVisible();
  190 |   await expect(list.getByText(/пересекает стену/)).toBeVisible();
  191 |   await expect(list.getByText(/перекрывает проём двери/)).toBeVisible();
  192 |   await expect(list.getByText(/^стоит вне помещений/)).toBeVisible();
  193 | 
  194 |   // «просмотр»: видит предметы и слои, каталога и правки нет
  195 |   const login1 = unique("v");
  196 |   await page.request.post("/api/users", { headers: H, data: { login: login1, full_name: "Петрова Е. А.", role: "viewer", building_ids: [f.building], password: "Temporary-1" } });
  197 |   const context = await browser.newContext();
  198 |   const viewer = await context.newPage();
  199 |   await login(viewer, login1, "Temporary-1");
  200 |   await viewer.getByLabel("Текущий пароль").fill("Temporary-1");
  201 |   await viewer.getByLabel("Новый пароль", { exact: true }).fill("Viewer-pass-12");
  202 |   await viewer.getByLabel("Новый пароль ещё раз").fill("Viewer-pass-12");
  203 |   await viewer.getByRole("button", { name: "Сменить и продолжить" }).click();
  204 |   await viewer.goto(`/plan/${f.building}/${f.floor}`);
> 205 |   await expect(viewer.getByRole("img", { name: "План этажа" }).locator("[data-item]")).toHaveCount(3);
      |                                                                                        ^ Error: expect(locator).toHaveCount(expected) failed
  206 |   await expect(viewer.getByRole("region", { name: "Слои" })).toBeVisible();
  207 |   await expect(viewer.getByRole("region", { name: "Каталог" })).toHaveCount(0);
  208 |   await expect(viewer.getByRole("tab", { name: "Расстановка" })).toHaveCount(0);
  209 |   await context.close();
  210 | });
  211 | 
  212 | test("Вложение: коммутатор — в стойку 19″, со стойкой и уходит", async ({ page }) => {
  213 |   await loginAdmin(page);
  214 |   const f = await floorWithRooms(page);
  215 |   await page.goto(`/plan/${f.building}/${f.floor}`);
  216 |   await page.getByRole("tab", { name: "Расстановка" }).click();
  217 |   await placeAt(page, "Шкаф телекоммуникационный 19″", 9000, 4000);
  218 |   await expect(page.getByRole("heading", { name: "Внутри (0)" })).toBeVisible();
  219 |   // мимо стойки — не ставится: сам он на план не встаёт
  220 |   await placeAt(page, "Коммутатор", 7000, 3000);
  221 |   await expect(page.getByRole("status")).toContainText("сам на план не ставится");
  222 |   await placeAt(page, "Коммутатор", 9000, 4000);
  223 |   await expect(page.getByRole("heading", { name: "Внутри (1)" })).toBeVisible();
  224 |   await expect.poll(async () => (await items(page, f.floor)).length).toBe(2);
  225 |   const placed = await items(page, f.floor);
  226 |   const rack = placed.find((i) => i.x !== null)!;
  227 |   expect(placed.find((i) => i.x === null)).toMatchObject({ room_id: f.rooms["215"] });
  228 |   await page.keyboard.press("Delete");
  229 |   await expect.poll(async () => (await items(page, f.floor)).length).toBe(0);
  230 |   expect(rack.room_id).toBe(f.rooms["215"]);
  231 | });
  232 | 
```