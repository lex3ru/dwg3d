# 3D-модели базового каталога

Базовый каталог (5.2.6) поставляется с 3D-моделями для всех 80 типов, которые ставятся
на план: `server/app/modules/catalog/models3d/` (файлы GLB и опись `index.json`). При
запуске модель получает тип базового каталога, у которого своей модели нет и которую
администратор не загружал и не убирал; потом её можно заменить в карточке типа («Вид»).

Откуда модели:

- **Kenney, Furniture Kit** ([kenney.nl](https://kenney.nl/assets/furniture-kit)) и
  **Quaternius, CreativeTrio, MilkAndBanana** — общественное достояние (CC0);
- **Poly Pizza** ([poly.pizza](https://poly.pizza)) — модели Google Poly и авторов сайта под
  лицензией CC-BY 3.0: автор указан ниже и в карточке типа («Источник»);
- **свои модели** (26 шт.) — медицинское оборудование, для которого свободных моделей нет
  (кушетки, каталка, купольные камеры, ростомер, УЗИ, ЭКГ, негатоскоп, столы из нержавейки,
  светильники-панели и др.); собираются скриптом `server/tools/models3d.py`, CC0.

Всего: CC0 — 41, CC-BY 3.0 — 39. Изменения моделей CC-BY: повёрнуты передом к лицу
предмета, в системе вписываются в габариты типа, у некоторых уменьшены текстуры.

Как пересобрать комплект (нужны скачанные модели — см. `index.json`, поле `url`):
`uv run python tools/models3d.py <папка>` строит свои модели.

## Свои модели

Администратор загружает модель типа в карточке («Вид» → «Загрузить GLB»): GLB, glTF 2.0.
Подходят и сжатые модели — Draco (так часто выгружают Blender и Sketchfab) и meshopt.
Декодеры входят в сборку интерфейса (`web/src/catalog/gltf.ts`, DWG3D-15): внешние адреса
не нужны, модели открываются и в закрытой сети. Размер модели сервер считает при загрузке
по описанию сцены, сжатую геометрию он не распаковывает.

Если браузер не смог разобрать модель (файл повреждён, сжат незнакомым способом), в превью
карточки появится «Модель не загрузилась». В 3D предметы этого типа будут коробками в цвете
слоя, на плане — прямоугольниками. Помогает пересохранить модель в редакторе 3D.

Тестовая Draco-модель для e2e и тестов сервера — `e2e/fixtures/draco-box.glb`, её собирает
`e2e/fixtures/draco-box.mjs`.

| Тип | Файл | Источник | Лицензия |
|---|---|---|---|
| Автоклав | `avtoklav.glb` | [Electric Oven](https://poly.pizza/m/AwUZBbqleJ), MilkAndBanana | CC0 |
| Авторефкератометр | `avtorefkeratometr.glb` | собрана для каталога (`server/tools/models3d.py`) | CC0 |
| Аппарат Рота (таблица Сивцева) | `apparat-rota.glb` | собрана для каталога (`server/tools/models3d.py`) | CC0 |
| Аппарат УЗИ | `apparat-uzi.glb` | собрана для каталога (`server/tools/models3d.py`) | CC0 |
| Аспиратор хирургический | `aspirator.glb` | собрана для каталога (`server/tools/models3d.py`) | CC0 |
| Весы медицинские | `vesy-meditsinskie.glb` | [Bathroom scale](https://poly.pizza/m/bL_hCXI0e4s), Poly by Google | [CC-BY 3.0](https://creativecommons.org/licenses/by/3.0/) |
| Вешалка гардеробная | `veshalka-garderobnaya.glb` | собрана для каталога (`server/tools/models3d.py`) | CC0 |
| Вешалка напольная | `veshalka-napolnaya.glb` | [coatRackStanding](https://kenney.nl/assets/furniture-kit), Kenney | CC0 |
| Дефибриллятор | `defibrillyator.glb` | собрана для каталога (`server/tools/models3d.py`) | CC0 |
| Диван | `divan.glb` | [Sofa](https://poly.pizza/m/vuo7KBehok), Quaternius | CC0 |
| ИБП | `ibp.glb` | [Computer Tower](https://poly.pizza/m/4TZXM3lO5KK), Ethan Yawney | [CC-BY 3.0](https://creativecommons.org/licenses/by/3.0/) |
| Информационная панель | `informatsionnaya-panel.glb` | [Flat Screen TV](https://poly.pizza/m/cQ6pt8VHR7G), Alex Safayan | [CC-BY 3.0](https://creativecommons.org/licenses/by/3.0/) |
| Камера «рыбий глаз» | `kamera-rybiy-glaz.glb` | собрана для каталога (`server/tools/models3d.py`) | CC0 |
| Камера купольная | `kamera-kupolnaya.glb` | собрана для каталога (`server/tools/models3d.py`) | CC0 |
| Камера поворотная (PTZ) | `kamera-povorotnaya-ptz.glb` | [CCTV Camera](https://poly.pizza/m/79z-QarmPO7), Jörg H. | [CC-BY 3.0](https://creativecommons.org/licenses/by/3.0/) |
| Камера цилиндрическая | `kamera-tsilindricheskaya.glb` | [Security Camera](https://poly.pizza/m/a6J7IDufQP), J-Toastie | [CC-BY 3.0](https://creativecommons.org/licenses/by/3.0/) |
| Каталка медицинская | `katalka.glb` | собрана для каталога (`server/tools/models3d.py`) | CC0 |
| Кольпоскоп | `kolposkop.glb` | [Microscope](https://poly.pizza/m/q9zNs4U5NG), Username12 | [CC-BY 3.0](https://creativecommons.org/licenses/by/3.0/) |
| Компьютер | `kompyuter.glb` | [Computer](https://poly.pizza/m/7KNoiQlSxi), CreativeTrio | CC0 |
| Кондиционер (сплит-система) | `konditsioner-split-sistema.glb` | [Air conditioner](https://poly.pizza/m/5KohLH0xc8d), Poly by Google | [CC-BY 3.0](https://creativecommons.org/licenses/by/3.0/) |
| Кресло врача | `kreslo-vracha.glb` | [Office Chair](https://poly.pizza/m/3txPAhYeu-x), Ryan Donaldson | [CC-BY 3.0](https://creativecommons.org/licenses/by/3.0/) |
| Кресло гинекологическое | `kreslo-ginekologicheskoe.glb` | собрана для каталога (`server/tools/models3d.py`) | CC0 |
| Кресло офисное | `kreslo-ofisnoe.glb` | [Office Chair](https://poly.pizza/m/UfKvrZBK6C), Quaternius | CC0 |
| Кресло руководителя | `kreslo-rukovoditelya.glb` | [Office Chair](https://poly.pizza/m/dCEsSsJJ1Md), CMHT Oculus | [CC-BY 3.0](https://creativecommons.org/licenses/by/3.0/) |
| Кресло-коляска | `kreslo-kolyaska.glb` | [Wheelchair](https://poly.pizza/m/0gb5yuNcwbg), Poly by Google | [CC-BY 3.0](https://creativecommons.org/licenses/by/3.0/) |
| Кровать функциональная | `krovat-funktsionalnaya.glb` | [Bed Single](https://poly.pizza/m/ianC28eMOF), Quaternius | CC0 |
| Кулер для воды | `kuler-dlya-vody.glb` | [Water Cooler](https://poly.pizza/m/zWi9p5FSxD), J-Toastie | [CC-BY 3.0](https://creativecommons.org/licenses/by/3.0/) |
| Кушетка массажная | `kushetka-massazhnaya.glb` | собрана для каталога (`server/tools/models3d.py`) | CC0 |
| Кушетка смотровая | `kushetka-smotrovaya.glb` | собрана для каталога (`server/tools/models3d.py`) | CC0 |
| МФУ лазерное | `mfu-lazernoe.glb` | [Printer](https://poly.pizza/m/6uy3vUnmbCJ), Mikael Ganehag Brorsson | [CC-BY 3.0](https://creativecommons.org/licenses/by/3.0/) |
| Монитор 24″ | `monitor-24.glb` | [Monitor](https://poly.pizza/m/PvSjEbz11k), CreativeTrio | CC0 |
| Монитор видеонаблюдения | `monitor-videonablyudeniya.glb` | [Monitor](https://poly.pizza/m/fN_jLmrWXxq), Poly by Google | [CC-BY 3.0](https://creativecommons.org/licenses/by/3.0/) |
| Монитор пациента | `monitor-patsienta.glb` | [Monitor](https://poly.pizza/m/e8cELDeDuTr), Poly by Google | [CC-BY 3.0](https://creativecommons.org/licenses/by/3.0/) |
| Моноблок | `monoblok.glb` | [Monitor](https://poly.pizza/m/5qZ5IaClHHw), Poly by Google | [CC-BY 3.0](https://creativecommons.org/licenses/by/3.0/) |
| Негатоскоп | `negatoskop.glb` | собрана для каталога (`server/tools/models3d.py`) | CC0 |
| Облучатель бактерицидный настенный | `obluchatel-bakteritsidnyy-nastennyy.glb` | [Fluorescent Light](https://poly.pizza/m/J8dFHQHQJZ), Nick Slough | [CC-BY 3.0](https://creativecommons.org/licenses/by/3.0/) |
| Облучатель-рециркулятор | `obluchatel-retsirkulyator.glb` | собрана для каталога (`server/tools/models3d.py`) | CC0 |
| Принтер этикеток | `printer-etiketok.glb` | [Printer](https://poly.pizza/m/77K2TCL5Lz), CreativeTrio | CC0 |
| Проектор знаков | `proektor-znakov.glb` | собрана для каталога (`server/tools/models3d.py`) | CC0 |
| Ростомер | `rostomer.glb` | собрана для каталога (`server/tools/models3d.py`) | CC0 |
| Светильник аварийный «Выход» | `svetilnik-avariynyy-vykhod.glb` | [Fire Exit Sign](https://poly.pizza/m/gpft2tHZv4), J-Toastie | [CC-BY 3.0](https://creativecommons.org/licenses/by/3.0/) |
| Светильник для чистых помещений | `svetilnik-chistye-pomeshcheniya.glb` | собрана для каталога (`server/tools/models3d.py`) | CC0 |
| Светильник круглый накладной | `svetilnik-kruglyy-nakladnoy.glb` | [Ceiling Light](https://poly.pizza/m/7-ZyHe177WV), Jarlan Perez | [CC-BY 3.0](https://creativecommons.org/licenses/by/3.0/) |
| Светильник линейный 1200 | `svetilnik-lineynyy-1200.glb` | [Flourescent Fixture](https://poly.pizza/m/b434Bd1ozKE), Colin McKibben | [CC-BY 3.0](https://creativecommons.org/licenses/by/3.0/) |
| Светильник настенный | `svetilnik-nastennyy.glb` | [Lamp Wall](https://poly.pizza/m/74FEuNrLJ5), Kenney | CC0 |
| Светильник светодиодный 600×600 | `svetilnik-panel-600.glb` | собрана для каталога (`server/tools/models3d.py`) | CC0 |
| Светильник смотровой передвижной | `svetilnik-smotrovoy-peredvizhnoy.glb` | [Lamp](https://poly.pizza/m/OQ2HurCvOz), burunduk | [CC-BY 3.0](https://creativecommons.org/licenses/by/3.0/) |
| Светильник хирургический передвижной | `svetilnik-khirurgicheskiy.glb` | собрана для каталога (`server/tools/models3d.py`) | CC0 |
| Сейф для лекарственных средств | `seyf-dlya-lekarstvennykh-sredstv.glb` | [Safe](https://poly.pizza/m/N4egHD2Vms), CreativeTrio | CC0 |
| Секция стульев трёхместная | `sektsiya-stulev.glb` | собрана для каталога (`server/tools/models3d.py`) | CC0 |
| Стеллаж | `stellazh.glb` | [Shelves](https://poly.pizza/m/OD78iJOQoN), J-Toastie | [CC-BY 3.0](https://creativecommons.org/licenses/by/3.0/) |
| Стерилизатор воздушный | `sterilizator-vozdushnyy.glb` | [Oven Solo](https://poly.pizza/m/dxG130Ddm1), Zsky | [CC-BY 3.0](https://creativecommons.org/licenses/by/3.0/) |
| Стойка регистратуры | `stoyka-registratury.glb` | [Desk](https://poly.pizza/m/dptlMEX4tF_), Poly by Google | [CC-BY 3.0](https://creativecommons.org/licenses/by/3.0/) |
| Стол инструментальный | `stol-instrumentalnyy.glb` | собрана для каталога (`server/tools/models3d.py`) | CC0 |
| Стол манипуляционный | `stol-manipulyatsionnyy.glb` | собрана для каталога (`server/tools/models3d.py`) | CC0 |
| Стол пеленальный | `stol-pelenalnyy.glb` | собрана для каталога (`server/tools/models3d.py`) | CC0 |
| Стол перевязочный | `stol-perevyazochnyy.glb` | собрана для каталога (`server/tools/models3d.py`) | CC0 |
| Стол письменный 1200×600 | `stol-pismennyy-1200-600.glb` | [Desk](https://poly.pizza/m/YJyJam67hJ), CreativeTrio | CC0 |
| Стол письменный 1400×700 | `stol-pismennyy-1200-600.glb` | [Desk](https://poly.pizza/m/YJyJam67hJ), CreativeTrio | CC0 |
| Стол приставной | `stol-pristavnoy.glb` | [Computer Desk](https://poly.pizza/m/OhXey2fljr), Zsky | [CC-BY 3.0](https://creativecommons.org/licenses/by/3.0/) |
| Стол процедурный | `stol-protsedurnyy.glb` | [Lab Desk](https://poly.pizza/m/6KxaD6I6I48), Colonel Cthulu | [CC-BY 3.0](https://creativecommons.org/licenses/by/3.0/) |
| Стол руководителя | `stol-rukovoditelya.glb` | [Desk](https://poly.pizza/m/7zuvXWL0v7f), CMHT Oculus | [CC-BY 3.0](https://creativecommons.org/licenses/by/3.0/) |
| Стул медицинский винтовой | `stul-meditsinskiy-vintovoy.glb` | [Chair](https://poly.pizza/m/4i_KehfD3z1), CMHT Oculus | [CC-BY 3.0](https://creativecommons.org/licenses/by/3.0/) |
| Стул посетителя | `stul-posetitelya.glb` | [Chair](https://poly.pizza/m/iMNqRzPwwe), Quaternius | CC0 |
| Телефон IP | `telefon-ip.glb` | [Office Phone](https://poly.pizza/m/YxfMuchpUF), dook | [CC-BY 3.0](https://creativecommons.org/licenses/by/3.0/) |
| Терминал электронной очереди | `terminal-elektronnoy-ocheredi.glb` | [Voting machine](https://poly.pizza/m/aT0tlNvHr4f), jeremy | [CC-BY 3.0](https://creativecommons.org/licenses/by/3.0/) |
| Точка доступа Wi-Fi | `tochka-dostupa-wi-fi.glb` | [Modern Router](https://poly.pizza/m/6UHtXKKQJy), J-Toastie | [CC-BY 3.0](https://creativecommons.org/licenses/by/3.0/) |
| Тумба подкатная | `tumba-podkatnaya.glb` | [lisa's pedestals drawers 2 col](https://poly.pizza/m/c8RZOw_aDG0), Lisa Tixier | [CC-BY 3.0](https://creativecommons.org/licenses/by/3.0/) |
| УФ-камера для хранения инструментов | `uf-kamera-dlya-khraneniya-instrumentov.glb` | [Microwave](https://poly.pizza/m/5JVQaADip1h), Poly by Google | [CC-BY 3.0](https://creativecommons.org/licenses/by/3.0/) |
| Холодильник бытовой | `kholodilnik-bytovoy.glb` | [Kitchen Fridge](https://poly.pizza/m/8sjRm8fnHh), Quaternius | CC0 |
| Холодильник фармацевтический | `kholodilnik-farmatsevticheskiy.glb` | [Can Fridge](https://poly.pizza/m/8OHbykvREu), Quaternius | CC0 |
| Ширма медицинская | `shirma-meditsinskaya.glb` | собрана для каталога (`server/tools/models3d.py`) | CC0 |
| Шкаф для документов | `shkaf-dlya-dokumentov.glb` | [Closet](https://poly.pizza/m/2qdm7DZVG94), Poly by Google | [CC-BY 3.0](https://creativecommons.org/licenses/by/3.0/) |
| Шкаф для одежды | `shkaf-dlya-odezhdy.glb` | [Closet](https://poly.pizza/m/0Cuf7Rv4SfV), Poly by Google | [CC-BY 3.0](https://creativecommons.org/licenses/by/3.0/) |
| Шкаф медицинский двухстворчатый | `shkaf-meditsinskiy-dvukhstvorchatyy.glb` | [Tall Cabinet](https://poly.pizza/m/z9U3UyVGPu), Bouggles | [CC-BY 3.0](https://creativecommons.org/licenses/by/3.0/) |
| Шкаф медицинский одностворчатый | `shkaf-meditsinskiy-odnostvorchatyy.glb` | [Locker](https://poly.pizza/m/aGmZ4jQD2y), J-Toastie | [CC-BY 3.0](https://creativecommons.org/licenses/by/3.0/) |
| Шкаф телекоммуникационный 19″ | `shkaf-telekommunikatsionnyy-19.glb` | [server rack](https://poly.pizza/m/6ijQclm8jxw), Jeremy Eyring | [CC-BY 3.0](https://creativecommons.org/licenses/by/3.0/) |
| Шкаф телекоммуникационный настенный | `shkaf-telekommunikatsionnyy-nastennyy.glb` | [mixed rack](https://poly.pizza/m/0NOoJkllvPB), Silverstone78 | [CC-BY 3.0](https://creativecommons.org/licenses/by/3.0/) |
| Щелевая лампа | `shchelevaya-lampa.glb` | [Microscope](https://poly.pizza/m/05VXLT8kN4k), Colonel Cthulu | [CC-BY 3.0](https://creativecommons.org/licenses/by/3.0/) |
| Электрокардиограф | `elektrokardiograf.glb` | собрана для каталога (`server/tools/models3d.py`) | CC0 |
