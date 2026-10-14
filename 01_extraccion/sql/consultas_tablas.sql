-- 11832
select * from persona;


-- tot 6194 campos nombre y apellidos informados 

SELECT *
FROM persona
WHERE nombre IS NOT NULL AND nombre <> ''
  and apellido1 IS NOT NULL AND apellido1 <> '';

  -- 5638 registros con nombres y apellidos no informados
  SELECT *
FROM persona
WHERE nombre  IS  NULL or nombre = ''
  or apellido1 IS  NULL or apellido1 = '';


  -- verificamos duplicados de los 6194 y los quitamos ( seria nuestra tabla clientes) 60 duplicados
  -- 6194 -  923 duplicados = 5271 cargados
WITH personas_filtradas AS (
    SELECT *
    FROM persona
    WHERE nombre IS NOT NULL AND nombre <> ''
      AND apellido1 IS NOT NULL AND apellido1 <> ''
),
duplicados AS (
    SELECT *,
           DENSE_RANK() OVER (PARTITION BY nombre, apellido1, apellido2 ORDER BY codpersona) AS rank_duplicados
    FROM personas_filtradas
)
SELECT *
FROM duplicados
 where rank_duplicados = 1;

 -- 1 Duplicar la tabla Persona con todas las columnas y creamos nuevo id personaiD con autoincrement 

SELECT *
INTO person_dup
FROM persona;

-- 2 Añadir columna autonumérica
ALTER TABLE person_dup
ADD personaID INT IDENTITY(1,1);



 --- Creamos VIEW clients -- campo relacional `codpersona`

create or alter VIEW clients
AS
WITH personas_filtradas AS (
    SELECT *
    FROM person_dup
    WHERE nombre IS NOT NULL AND nombre <> ''
      AND apellido1 IS NOT NULL AND apellido1 <> ''
),
duplicados AS (
    SELECT *,
           DENSE_RANK() OVER (
               PARTITION BY nombre, apellido1, apellido2
               ORDER BY codpersona
           ) AS rank_duplicados
    FROM personas_filtradas
)
SELECT
    *
FROM duplicados
WHERE rank_duplicados = 1;


  
  
-- join persona/profesionales para ver solo profesionales ( 27 con algun fantasma)

SELECT per.personaID,per.nombre, per.apellido1,per.codpersona
  FROM person_dup as per
  right join profesionales as pro 
  on per.codpersona=pro.codpersona;




  SELECT
    a.*,
    p_prof.personaID AS DiaryGUserID
FROM agenda a
LEFT JOIN person_dup p_prof
    ON p_prof.codpersona = a.codprofesional;


    -- alteramos View clients y movemos campo personaID en segunda posición
CREATE OR ALTER VIEW dbo.clients
AS
WITH clients AS (
    SELECT *
    FROM person_dup
    WHERE nombre IS NOT NULL AND nombre <> ''
      AND apellido1 IS NOT NULL AND apellido1 <> ''
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
    personaID,              --  movida a segunda posición
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
    codtipoclasifpaciente,
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

select * from clients;

 -- consultamos capos PK y GUI de la tabla persona

    EXEC sp_help 'persona';


    -- Consulta tabla  diaryGen a partir de mañana (agenda a Futuro ) 
    -- hay 1 solo campo null del profesional he puesto por defecto el profesional codigo 0 ( nadie)
    -- es un regordatorio agendado como cita : 'LLAMAR PARA DARLE HORA BOTOX O DERMA' 

SELECT
cli.nombre,
cli.apellido1,
cli.apellido2,
    a.codclinica,
    a.codgabinete,
    a.fecha,
    a.horacita,
    a.horafin,
    a.fechacreacion,
    a.anotaciones,

    cli.personaID  AS ClientID,
    prof.personaID AS DiaryGUserID,
    prof.nombre,
    prof.apellido1

FROM agenda AS a
LEFT JOIN person_dup AS cli
    ON cli.codpersona = a.codpersona
   AND cli.codempresa = a.codempresa
LEFT JOIN person_dup AS prof
    ON prof.codpersona = a.codprofesional
   AND prof.codempresa = a.codempresa

WHERE a.codpersona <> '00000000-0000-0000-0000-000000000000'
    AND a.fecha >= DATEADD(DAY, 1, CAST(GETDATE() AS DATE));





 
 SELECT *
    FROM person_dup
    WHERE nombre IS NOT NULL AND nombre <> ''
      AND apellido1 IS NOT NULL AND apellido1 <> ''