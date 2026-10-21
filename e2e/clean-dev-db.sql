-- Очистка базы разработки от следов прогонов e2e: тестовые здания (все, кроме оставляемых
-- ниже), их этажи, помещения, предметы, проекты, учёт, документы, ссылки; учётные записи,
-- склады, типы, слои и назначения с суффиксом прогона (unique() в tests/helpers.ts);
-- записи журнала о них; файлы, на которые больше никто не ссылается.
--
--   (cat e2e/clean-dev-db.sql; echo 'ROLLBACK;') | docker exec -i planuchet-devdb psql -U app -d app -q   — проба
--   (cat e2e/clean-dev-db.sql; echo 'COMMIT;')   | docker exec -i planuchet-devdb psql -U app -d app -q   — по-настоящему
--
-- Только для базы разработки, не для рабочей установки. Файлы на диске (server/.dev-data),
-- которые остались без записи, этим не удаляются.
\set ON_ERROR_STOP on
BEGIN;
SET LOCAL journal.purge = 'on';

CREATE TEMP TABLE keep_b AS SELECT id FROM building.building WHERE name IN ('Поликлиника', 'Лабораторный корпус', 'Тестовое');
CREATE TEMP TABLE dead_b AS SELECT id FROM building.building WHERE id NOT IN (SELECT id FROM keep_b);
CREATE TEMP TABLE dead_f AS SELECT id FROM building.floor WHERE building_id IN (SELECT id FROM dead_b);
CREATE TEMP TABLE dead_r AS SELECT id FROM building.room WHERE building_id IN (SELECT id FROM dead_b);
CREATE TEMP TABLE dead_dr AS SELECT id, file_id FROM building.drawing WHERE building_id IN (SELECT id FROM dead_b);
CREATE TEMP TABLE dead_l AS SELECT id FROM building.lift WHERE building_id IN (SELECT id FROM dead_b);
CREATE TEMP TABLE dead_i AS SELECT id FROM planning.item WHERE building_id IN (SELECT id FROM dead_b);
CREATE TEMP TABLE dead_p AS SELECT id FROM projects.project WHERE building_id IN (SELECT id FROM dead_b);
CREATE TEMP TABLE dead_w AS SELECT id FROM inventory.warehouse
  WHERE name ~ '^Склад m[a-z0-9]{7}$' OR building_id IN (SELECT id FROM dead_b) OR room_id IN (SELECT id FROM dead_r);
CREATE TEMP TABLE dead_pl AS
  SELECT 'r:' || id AS k FROM dead_r
  UNION SELECT 'w:' || id FROM dead_w
  UNION SELECT 'c:' || id FROM inventory.cell WHERE warehouse_id IN (SELECT id FROM dead_w);
CREATE TEMP TABLE dead_u AS SELECT id FROM inventory.unit
  WHERE place IN (SELECT k FROM dead_pl) OR building_id IN (SELECT id FROM dead_b);
CREATE TEMP TABLE dead_d AS SELECT DISTINCT d.id FROM inventory.document d
  LEFT JOIN inventory.doc_line l ON l.document_id = d.id
  WHERE d.from_place IN (SELECT k FROM dead_pl) OR d.to_place IN (SELECT k FROM dead_pl)
     OR l.from_place IN (SELECT k FROM dead_pl) OR l.to_place IN (SELECT k FROM dead_pl)
     OR l.unit_id IN (SELECT id FROM dead_u)
     OR d.id IN (SELECT document_id FROM inventory.count_place WHERE place IN (SELECT k FROM dead_pl));
CREATE TEMP TABLE dead_a AS SELECT id FROM access.account WHERE login ~ 'm[a-z0-9]{7}$';
CREATE TEMP TABLE dead_s AS SELECT id FROM access.share_link WHERE building_id IN (SELECT id FROM dead_b);
CREATE TEMP TABLE dead_t AS SELECT id FROM catalog.item_type
  WHERE name ~ ' m[a-z0-9]{7}$' OR name ~ '^[бвгджзклмнпрстфхцчшщ]{12}$';
CREATE TEMP TABLE dead_m AS SELECT id FROM catalog.model WHERE type_id IN (SELECT id FROM dead_t);
CREATE TEMP TABLE dead_c AS SELECT id FROM catalog.characteristic WHERE type_id IN (SELECT id FROM dead_t);
CREATE TEMP TABLE dead_layer AS SELECT id FROM catalog.layer WHERE name ~ ' m[a-z0-9]{7}$';
CREATE TEMP TABLE dead_purpose AS SELECT id FROM catalog.purpose WHERE name ~ ' m[a-z0-9]{7}$';

-- проверки: тестовое не должно задевать то, что остаётся (все — нули)
SELECT 'документы тестовых мест с единицами, что остаются' AS check,
  count(*) FROM inventory.doc_line WHERE document_id IN (SELECT id FROM dead_d) AND unit_id IS NOT NULL AND unit_id NOT IN (SELECT id FROM dead_u)
UNION ALL SELECT 'предметы сохраняемых зданий, связанные с тестовыми единицами',
  count(*) FROM planning.item WHERE unit_id IN (SELECT id FROM dead_u) AND id NOT IN (SELECT id FROM dead_i)
UNION ALL SELECT 'помещения сохраняемых зданий с тестовым назначением',
  count(*) FROM building.room WHERE building_id IN (SELECT id FROM keep_b) AND purpose_id IN (SELECT id::text FROM dead_purpose);

SELECT 'здания' AS what, count(*) FROM dead_b UNION ALL SELECT 'этажи', count(*) FROM dead_f
UNION ALL SELECT 'помещения', count(*) FROM dead_r UNION ALL SELECT 'предметы', count(*) FROM dead_i
UNION ALL SELECT 'проекты', count(*) FROM dead_p UNION ALL SELECT 'склады', count(*) FROM dead_w
UNION ALL SELECT 'единицы', count(*) FROM dead_u UNION ALL SELECT 'документы', count(*) FROM dead_d
UNION ALL SELECT 'учётные записи', count(*) FROM dead_a UNION ALL SELECT 'ссылки', count(*) FROM dead_s
UNION ALL SELECT 'типы', count(*) FROM dead_t UNION ALL SELECT 'слои', count(*) FROM dead_layer
UNION ALL SELECT 'назначения', count(*) FROM dead_purpose;

-- журнал: записи, что касаются удаляемого и не касаются сохраняемых зданий
CREATE TEMP TABLE dead_ref AS
  SELECT 'building:' || id AS r FROM dead_b UNION SELECT 'floor:' || id FROM dead_f
  UNION SELECT 'room:' || id FROM dead_r UNION SELECT 'item:' || id FROM dead_i
  UNION SELECT 'drawing:' || id FROM dead_dr UNION SELECT 'lift:' || id FROM dead_l
  UNION SELECT 'project:' || id FROM dead_p UNION SELECT 'warehouse:' || id FROM dead_w
  UNION SELECT 'unit:' || id FROM dead_u UNION SELECT 'document:' || id FROM dead_d
  UNION SELECT 'user:' || id FROM dead_a UNION SELECT 'share:' || id FROM dead_s
  UNION SELECT 'type:' || id FROM dead_t UNION SELECT 'model:' || id FROM dead_m
  UNION SELECT 'characteristic:' || id FROM dead_c UNION SELECT 'layer:' || id FROM dead_layer
  UNION SELECT 'purpose:' || id FROM dead_purpose;
CREATE TEMP TABLE keep_ref AS SELECT 'building:' || id AS r FROM keep_b;
WITH gone AS (
  DELETE FROM journal.entry e
  WHERE (e.refs && (SELECT array_agg(r)::varchar[] FROM dead_ref) OR e.entity IN (SELECT r FROM dead_ref)
         OR e.actor_id IN (SELECT id FROM dead_a))
    AND NOT e.refs && (SELECT array_agg(r)::varchar[] FROM keep_ref)
  RETURNING 1)
SELECT 'записи журнала' AS what, count(*) FROM gone;

-- файлы, на которые ссылается удаляемое (решаем после удаления, нужны ли они ещё)
CREATE TEMP TABLE maybe_files AS
  SELECT file_id AS id FROM dead_dr
  UNION SELECT photo_file_id FROM inventory.unit WHERE id IN (SELECT id FROM dead_u) AND photo_file_id IS NOT NULL
  UNION SELECT file_id FROM inventory.unit_file WHERE unit_id IN (SELECT id FROM dead_u)
  UNION SELECT file_id FROM inventory.doc_file WHERE document_id IN (SELECT id FROM dead_d)
  UNION SELECT photo_file_id FROM inventory.count_extra WHERE document_id IN (SELECT id FROM dead_d) AND photo_file_id IS NOT NULL
  UNION SELECT model_file_id FROM catalog.item_type WHERE id IN (SELECT id FROM dead_t) AND model_file_id IS NOT NULL
  UNION SELECT (f.plan -> 'underlay' ->> 'file_id')::uuid FROM building.floor f
        WHERE f.id IN (SELECT id FROM dead_f) AND f.plan -> 'underlay' ->> 'file_id' IS NOT NULL;

-- удаление: сверху вниз по уровням модулей
DELETE FROM inventory.stock_move WHERE document_id IN (SELECT id FROM dead_d) OR place IN (SELECT k FROM dead_pl);
DELETE FROM inventory.unit_event WHERE document_id IN (SELECT id FROM dead_d) OR unit_id IN (SELECT id FROM dead_u);
DELETE FROM inventory.document WHERE id IN (SELECT id FROM dead_d);
DELETE FROM planning.item WHERE id IN (SELECT id FROM dead_i);
DELETE FROM inventory.room_label WHERE room_id IN (SELECT id FROM dead_r);
DELETE FROM inventory.unit WHERE id IN (SELECT id FROM dead_u);
DELETE FROM inventory.warehouse WHERE id IN (SELECT id FROM dead_w);
DELETE FROM access.share_link WHERE id IN (SELECT id FROM dead_s);
DELETE FROM access.building_grant WHERE building_id IN (SELECT id FROM dead_b);
DELETE FROM access.account WHERE id IN (SELECT id FROM dead_a);
DELETE FROM building.building WHERE id IN (SELECT id FROM dead_b);
DELETE FROM catalog.item_type WHERE id IN (SELECT id FROM dead_t);
DELETE FROM catalog.layer WHERE id IN (SELECT id FROM dead_layer);
DELETE FROM catalog.purpose WHERE id IN (SELECT id FROM dead_purpose);
DELETE FROM core.job WHERE status IN ('done', 'failed')
  AND (payload ->> 'building_id' IN (SELECT id::text FROM dead_b)
       OR payload ->> 'drawing_id' IN (SELECT id::text FROM dead_dr)
       OR created_by IN (SELECT id FROM dead_a)
       OR kind = 'reports.full_export');

-- файлы, на которые больше никто не ссылается
CREATE TEMP TABLE dead_files AS SELECT id FROM maybe_files m WHERE id IS NOT NULL
  AND NOT EXISTS (SELECT 1 FROM building.drawing WHERE file_id = m.id)
  AND NOT EXISTS (SELECT 1 FROM building.floor WHERE plan -> 'underlay' ->> 'file_id' = m.id::text)
  AND NOT EXISTS (SELECT 1 FROM catalog.item_type WHERE model_file_id = m.id)
  AND NOT EXISTS (SELECT 1 FROM inventory.unit WHERE photo_file_id = m.id)
  AND NOT EXISTS (SELECT 1 FROM inventory.unit_file WHERE file_id = m.id)
  AND NOT EXISTS (SELECT 1 FROM inventory.doc_file WHERE file_id = m.id)
  AND NOT EXISTS (SELECT 1 FROM inventory.count_extra WHERE photo_file_id = m.id);
WITH gone AS (DELETE FROM files.file WHERE id IN (SELECT id FROM dead_files) RETURNING sha256)
SELECT 'файлы' AS what, count(*) FROM gone;

SELECT 'осталось зданий' AS what, count(*) FROM building.building
UNION ALL SELECT 'единиц', count(*) FROM inventory.unit
UNION ALL SELECT 'документов', count(*) FROM inventory.document
UNION ALL SELECT 'учётных записей', count(*) FROM access.account
UNION ALL SELECT 'типов каталога', count(*) FROM catalog.item_type
UNION ALL SELECT 'записей журнала', count(*) FROM journal.entry;
