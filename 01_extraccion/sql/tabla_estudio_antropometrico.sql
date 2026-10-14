
-- estudio antropometrico (cliente 177) quitar el filtro VISITA MEDICA

SELECT
    p.personaID,
    p.nombre,
    p.apellido1,
    p.apellido2,

    f.codempresa,
    f.codpersona,
    f.codclinica,
    f.codunidad,
    f.codnumtrat,
    f.subcodtrat,
    f.titulo,
    COALESCE(f.fechamodificacion, f.fechacreacion) AS fecha, -- si f.fechamodificacion tiene valor → fecha = fechamodificacion si f.fechamodificacion es NULL → fecha = fechacreacion

    ea.peso,
    ea.talla,
    ea.imc,
    ea.pesodeseable,
    ea.get,

    ea.actividad,
    CASE ea.actividad
        WHEN 1 THEN N'Muy ligera'
        WHEN 2 THEN N'Ligera'
        WHEN 3 THEN N'Moderada'
        WHEN 4 THEN N'Intensa'
        WHEN 5 THEN N'Muy intensa'
        ELSE NULL
    END AS actividad__fisica_desc,

    ea.complexion,
    CASE ea.complexion
        WHEN 1 THEN N'Pequeña'
        WHEN 2 THEN N'Mediana'
        WHEN 3 THEN N'Grande'
        ELSE NULL
    END AS complexion_desc,

    ea.estres,  -- pendiente de mapear

    d.codcampo,
    pa.campo AS nombre_campo,
    d.medida1,
    d.medida2,
    d.medida3,
    d.medidax
FROM dbo.fichamedica f
JOIN dbo.person_dup p
  ON p.codpersona = f.codpersona
JOIN dbo.estudioantropometrico ea
  ON ea.codempresa  = f.codempresa
 AND ea.codpersona  = f.codpersona
 AND ea.codclinica  = f.codclinica
 AND ea.codunidad   = f.codunidad
 AND ea.codnumtrat  = f.codnumtrat
 AND ea.subcodtrat  = f.subcodtrat
JOIN dbo.estudioantropometricodetalles d
  ON d.codempresa   = ea.codempresa
 AND d.codpersona   = ea.codpersona
 AND d.codclinica   = ea.codclinica
 AND d.codunidad    = ea.codunidad
 AND d.codnumtrat   = ea.codnumtrat
 AND d.subcodtrat   = ea.subcodtrat
LEFT JOIN dbo.paramestudioantropometrico pa
  ON pa.codcampo = d.codcampo
WHERE p.personaID = 177
ORDER BY fecha DESC, f.codnumtrat DESC, d.codcampo;

-- 7657 Jose Sanchaz Jimenez

-- WHERE f.titulo = 'VISITA MEDICA'


/* 
Objetivo: inspeccionar los campos codificados (complexion, estres, actividad) en estudioantropometrico.

1) La primera consulta devuelve un resumen:
   - MIN/MAX de complexion (rango de códigos que aparecen)
   - COUNT(DISTINCT) de complexion/estres/actividad (cuántos códigos distintos existen en los datos)

2) Las 3 consultas siguientes listan los valores/códigos distintos (hasta 50) de cada campo.
   Esto sirve para:
   - validar qué códigos existen realmente en la BD
   - saber qué mapeos/diccionarios hay que buscar o construir (código -> descripción)
*/

SELECT
  MIN(complexion) AS min_complexion,
  MAX(complexion) AS max_complexion,
  COUNT(DISTINCT complexion) AS n_complexion,
  COUNT(DISTINCT estres) AS n_estres,
  COUNT(DISTINCT actividad) AS n_actividad
FROM dbo.estudioantropometrico;

SELECT DISTINCT TOP 50 complexion FROM dbo.estudioantropometrico ORDER BY complexion;
SELECT DISTINCT TOP 50 estres FROM dbo.estudioantropometrico ORDER BY estres;
SELECT DISTINCT TOP 50 actividad FROM dbo.estudioantropometrico ORDER BY actividad;