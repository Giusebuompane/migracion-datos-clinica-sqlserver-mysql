/* =========================================================
   SCRIPT ÚNICO (UN CLICK) - PERSONAS -> person_dup + VIEW dbo.clients
   + verificaciones y joins (SIN TOP)
   ========================================================= */

USE CLINICA_ORIGEN;
GO

/* =========================================================
   1) LIMPIEZA PARA RE-EJECUCIÓN
   ========================================================= */
IF OBJECT_ID('dbo.clients', 'V') IS NOT NULL
    DROP VIEW dbo.clients;
GO

IF OBJECT_ID('dbo.person_dup', 'U') IS NOT NULL
    DROP TABLE dbo.person_dup;
GO


/* =========================================================
   2) INSPECCIÓN BÁSICA PERSONA (TODOS LOS REGISTROS)
   ========================================================= */
SELECT * FROM dbo.persona;
GO

-- Con nombre y apellido1 informados
SELECT *
FROM dbo.persona
WHERE nombre IS NOT NULL AND LTRIM(RTRIM(nombre)) <> ''
  AND apellido1 IS NOT NULL AND LTRIM(RTRIM(apellido1)) <> '';
GO

-- Con datos faltantes
SELECT *
FROM dbo.persona
WHERE nombre IS NULL OR LTRIM(RTRIM(nombre)) = ''
   OR apellido1 IS NULL OR LTRIM(RTRIM(apellido1)) = '';
GO


/* =========================================================
   3) CREAR person_dup (copia exacta + identity personaID)
   ========================================================= */
SELECT *
INTO dbo.person_dup
FROM dbo.persona;
GO

ALTER TABLE dbo.person_dup
ADD personaID INT IDENTITY(1,1) NOT NULL;
GO

SELECT personaID, codpersona, nombre, apellido1, apellido2
FROM dbo.person_dup
ORDER BY personaID;
GO


/* =========================================================
   4) VER DUPLICADOS (TODOS)
   ========================================================= */
WITH personas_filtradas AS (
    SELECT *
    FROM dbo.person_dup
    WHERE nombre IS NOT NULL AND LTRIM(RTRIM(nombre)) <> ''
      AND apellido1 IS NOT NULL AND LTRIM(RTRIM(apellido1)) <> ''
),
duplicados AS (
    SELECT *,
           DENSE_RANK() OVER (
               PARTITION BY nombre, apellido1, apellido2
               ORDER BY codpersona
           ) AS rank_duplicados
    FROM personas_filtradas
)
SELECT *
FROM duplicados
WHERE rank_duplicados > 1
ORDER BY nombre, apellido1, apellido2, codpersona;
GO


/* =========================================================
   5) CREAR VIEW dbo.clients (deduplicada) (personaID 2ª columna)
   ========================================================= */
CREATE OR ALTER VIEW dbo.clients
AS
WITH clients AS (
    SELECT *
    FROM dbo.person_dup
    WHERE nombre IS NOT NULL AND LTRIM(RTRIM(nombre)) <> ''
      AND apellido1 IS NOT NULL AND LTRIM(RTRIM(apellido1)) <> ''
),
duplicados AS (
    SELECT *,
           DENSE_RANK() OVER (
               PARTITION BY nombre, apellido1, apellido2
               ORDER BY codpersona
           ) AS rank_duplicados
    FROM clients
)
SELECT
    codempresa,
    personaID,
    codpersona,
    nombre,
    apellido1,
    apellido2,
    codclinica,
    saldoclinica,
    fechacliniwin,
    fechaalta,
    fechabaja,
    codmotivobaja,
    facturaauto,
    letrasidexis,
    codunidad,
    codprofesionaldefecto,
    codenfermeradefecto,
    saldoinicial,
    saldounidad,
    fechaprimeravisita,
    fechaultimavisita,
    fechaultimarevision,
    codprofultimarev,
    avisoshistoriaclinica,
    codnumpersona,
    codnumpersona2,
    codnumpersona3,
    activo,
    conretencion,
    dnicif,
    razonsocial,
    codpersonatitular,
    codnumpersonatitular,
    tipotitular,
    nombretitular,
    apellido1titular,
    apellido2titular,
    dniciftitular,
    razonsocialtitular,
    conretenciontitular,
    direcciontitular,
    portaltitular,
    puertatitular,
    escaleratitular,
    codigopostaltitular,
    poblaciontitular,
    provinciatitular,
    telefonofijo,
    movil,
    fax,
    email,
    anotacionestelefonicas,
    nombreavisarcontacto,
    telefonoavisarcontacto,
    redessociales,
    direccion,
    portal,
    puerta,
    escalera,
    codigopostal,
    poblacion,
    provincia,
    codseguro,
    polizaseguro,
    codmutualidad,
    polizamutualidad,
    codtipopublicidad,
    remitidopor,
    sexo,
    codestadocivil,
    nhijos,
    profesion,
    centrotrabajo,
    codsituacionlaboral,
    descuento,
    saldototal,
    anotaciones,
    anotacionesocultas,
    foto,
    fechanacimiento,
    fechadeuda,
    excluirmailing,
    codtipoenvio,
    codidiomaenvios,
    moroso,
    fallecido,
    familiasiono,
    cabezafamilia,
    impuntual,
    fallon,
    niveleconomico,
    nivelauto,
    imprimir,
    codnacionalidad,
    codpersonaclinica,
    codclinicahabitual,
    fotoperfil,
    numerocolegiado,
    usuariocreacion,
    usuariomodificacion,
    fechacreacion,
    fechamodificacion,
    havisitadoweb,
    esdocumentoextranjero,
    paisexpedido,
    nombrepaisexpedido,
    fechahistoriaactualizada
FROM duplicados
WHERE rank_duplicados = 1;
GO


/* =========================================================
   6) VER CLIENTS (TODOS)
   ========================================================= */
SELECT *
FROM dbo.clients
ORDER BY personaID;
GO


/* =========================================================
   7) JOIN person_dup/profesionales (TODOS)
   ========================================================= */
SELECT
    per.personaID,
    per.nombre,
    per.apellido1,
    per.codpersona,
    pro.*
FROM dbo.person_dup AS per
RIGHT JOIN dbo.profesionales AS pro
    ON per.codpersona = pro.codpersona;
GO


/* =========================================================
   8) JOIN person_dup/usuarios (VER USUARIOS) (TODOS)
   ========================================================= */
SELECT
    per.personaID,
    per.nombre,
    per.apellido1,
    per.codpersona,
    u.*
FROM dbo.person_dup AS per
RIGHT JOIN dbo.usuarios AS u
    ON per.codpersona = u.codpersona;
GO


/* =========================================================
   9) AGENDA + personaID del profesional (TODOS)
   ========================================================= */
SELECT
    a.*,
    p_prof.personaID AS DiaryGUserID
FROM dbo.agenda a
LEFT JOIN dbo.person_dup p_prof
    ON p_prof.codpersona = a.codprofesional;
GO


/* =========================================================
   10) Consulta diaryGen (agenda futuro 2026) (TODOS)
   ========================================================= */
SELECT
    a.*,
    cli.nombre     AS NombrePaciente,
    cli.apellido1  AS ApellidoPaciente,
    prof.nombre    AS NombreMedico,
    prof.apellido1 AS ApellidoMedico,
    cli.personaID  AS ClientID,
    prof.personaID AS DiaryGUserID
FROM dbo.agenda AS a
LEFT JOIN dbo.person_dup AS cli
    ON cli.codpersona = a.codpersona
   AND cli.codempresa = a.codempresa
LEFT JOIN dbo.person_dup AS prof
    ON prof.codpersona = a.codprofesional
   AND prof.codempresa = a.codempresa
WHERE a.codpersona <> '00000000-0000-0000-0000-000000000000'
  AND YEAR(a.fecha) = 2026;
GO
