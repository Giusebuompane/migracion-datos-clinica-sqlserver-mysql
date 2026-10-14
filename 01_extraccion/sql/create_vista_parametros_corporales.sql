CREATE OR ALTER VIEW parametros_corporales AS
SELECT
    p.personaID as ClientID,
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
    COALESCE(f.fechamodificacion, f.fechacreacion) AS fecha,

    ea.peso,
    ea.talla,
    ea.imc,
    ea.pesodeseable,
    ea.get as get_kcal_dia,

    ea.actividad,
    CASE ea.actividad
        WHEN 1 THEN N'Muy ligera'
        WHEN 2 THEN N'Ligera'
        WHEN 3 THEN N'Moderada'
        WHEN 4 THEN N'Intensa'
        WHEN 5 THEN N'Muy intensa'
        ELSE NULL
    END AS actividad_fisica,

    ea.complexion,
    CASE ea.complexion
        WHEN 1 THEN N'Pequeña'
        WHEN 2 THEN N'Mediana'
        WHEN 3 THEN N'Grande'
        ELSE NULL
    END AS complexion_desc,

    ea.estres,

    d.codcampo,
    pa.campo AS parte_del_cuerpo,
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
  ON pa.codcampo = d.codcampo;