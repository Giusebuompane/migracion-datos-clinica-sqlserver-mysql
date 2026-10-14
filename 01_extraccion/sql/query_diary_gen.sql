SELECT
    a.codclinica,
    a.codgabinete,
    a.fecha,
    a.horacita,
    a.horafin,
    a.fechacreacion,
    a.anotaciones,

    cli.personaID  AS ClientID,
    prof.personaID AS DiaryGUserID

FROM agenda AS a
LEFT JOIN person_dup AS cli
    ON cli.codpersona = a.codpersona
   AND cli.codempresa = a.codempresa
LEFT JOIN person_dup AS prof
    ON prof.codpersona = a.codprofesional
   AND prof.codempresa = a.codempresa

WHERE a.codpersona <> '00000000-0000-0000-0000-000000000000'
    AND a.fecha >= DATEADD(DAY, 1, CAST(GETDATE() AS DATE));